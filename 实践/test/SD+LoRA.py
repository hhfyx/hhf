import os, sys
import random
import argparse
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm
import traceback
import diffusers


def imread_unicode(path):
    try:
        with open(path, 'rb') as f:
            data = f.read()
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            img = cv2.imread(path, cv2.IMREAD_COLOR)
        return img
    except:
        return None


def parse_defect_patch_name(filename):
    parts = filename.replace('.png', '').split('_')
    if len(parts) < 4:
        return {'img_id': 'unknown', 'defect_type': '0', 'box_id': '0'}
    return {'img_id': parts[0], 'defect_type': parts[-3], 'box_id': parts[-1].replace('box', '')}


def build_defect_dataset(dataset_root):
    dataset_root = Path(dataset_root)
    defect_groups = defaultdict(list)
    for class_dir in dataset_root.iterdir():
        if not class_dir.is_dir():
            continue
        for img_file in class_dir.iterdir():
            if img_file.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                continue
            info = parse_defect_patch_name(img_file.name)
            info['path'] = str(img_file)
            info['class_name'] = class_dir.name
            defect_groups[info['defect_type']].append(info)
    return defect_groups


class LatentDataset(Dataset):
    def __init__(self, latents, dtype):
        self.latents = latents
        self.defect_types = [dtype] * len(latents)

    def __len__(self):
        return len(self.latents)

    def __getitem__(self, idx):
        return {
            'latent': self.latents[idx].clone(),
            'defect_type': self.defect_types[idx],
        }


def merge_to_batch(items):
    latents = torch.stack([item['latent'] for item in items], dim=0)
    defect_types = [item['defect_type'] for item in items]
    return {'latent': latents, 'defect_type': defect_types}


def collate_latents(items):
    return merge_to_batch(items)


def precompute_latents(vae, dataset_root, image_size, device, dtype, cache_dir, scaling_factor):
    cache_path = os.path.join(cache_dir, "latents_cache.pt")
    if os.path.exists(cache_path):
        print(f"Loading precomputed latents from {cache_path}...", flush=True)
        data = torch.load(cache_path, map_location="cpu")
        print(f"  Loaded {sum(len(v) for v in data.values())} latents", flush=True)
        return data

    print("Precomputing latents (one-time, ~2 min)...", flush=True)

    defect_groups = build_defect_dataset(dataset_root)
    all_latents = {}

    total = sum(len(items) for items in defect_groups.values())
    pbar = tqdm(total=total, desc="Encoding images")

    for dtype, items in defect_groups.items():
        latents_list = []
        for item in items:
            img = imread_unicode(item['path'])
            if img is None:
                img = np.zeros((image_size, image_size, 3), dtype=np.uint8)
            img = cv2.resize(img, (image_size, image_size))
            img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img_tensor = torch.from_numpy(img_rgb).float().permute(2, 0, 1) / 127.5 - 1.0
            vae_dtype = torch.float16 if device == "cuda" else torch.float32
            img_tensor = img_tensor.unsqueeze(0).to(device=device, dtype=vae_dtype)

            with torch.no_grad():
                latent = vae.encode(img_tensor).latent_dist.sample()
                latent = latent * scaling_factor
                latents_list.append(latent.squeeze(0).cpu())

            pbar.update(1)

        all_latents[dtype] = latents_list

    pbar.close()

    os.makedirs(cache_dir, exist_ok=True)
    torch.save(all_latents, cache_path)
    print(f"Latents cached to {cache_path}", flush=True)

    return all_latents


class DefectGeneratorTrainer:
    def __init__(self, model_id, device="cuda", lora_rank=8):
        self.device = device
        self.lora_rank = lora_rank

        print(f"Loading pipeline from {model_id}...", flush=True)
        self.pipe = diffusers.StableDiffusionInpaintPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            safety_checker=None,
        )
        self.pipe = self.pipe.to(device)

        self.vae = self.pipe.vae
        self.unet = self.pipe.unet
        self.text_encoder = self.pipe.text_encoder
        self.tokenizer = self.pipe.tokenizer
        self.scheduler = self.pipe.scheduler

        print("Setting up LoRA...", flush=True)
        self._setup_lora()
        print(f"Trainable params: {sum(p.numel() for p in self.trainable_params)}", flush=True)

        self.vae.requires_grad_(False)
        self.unet.enable_gradient_checkpointing()
        print("Trainer ready", flush=True)

        self.placeholder_token = "<defect>"
        self._add_placeholder_token()

    def _setup_lora(self):
        from peft import LoraConfig, get_peft_model

        unet_lora_config = LoraConfig(
            r=self.lora_rank,
            lora_alpha=self.lora_rank,
            target_modules=["to_k", "to_q", "to_v", "to_out.0"],
            lora_dropout=0.0,
        )
        self.unet = get_peft_model(self.unet, unet_lora_config)

        text_encoder_lora_config = LoraConfig(
            r=self.lora_rank,
            lora_alpha=self.lora_rank,
            target_modules=["k_proj", "v_proj", "q_proj", "out_proj"],
            lora_dropout=0.0,
        )
        self.text_encoder = get_peft_model(self.text_encoder, text_encoder_lora_config)

        self.unet.train()
        self.text_encoder.train()

        self.trainable_params = []
        for param in self.unet.parameters():
            if param.requires_grad:
                self.trainable_params.append(param)
        for param in self.text_encoder.parameters():
            if param.requires_grad:
                self.trainable_params.append(param)

        print(f"LoRA params: {sum(p.numel() for p in self.trainable_params)}")

    def _add_placeholder_token(self):
        num_added = self.tokenizer.add_tokens([self.placeholder_token])
        if num_added > 0:
            self.text_encoder.resize_token_embeddings(len(self.tokenizer))

    def get_text_embeddings(self, prompt, num_images_per_prompt=1):
        text_inputs = self.tokenizer(
            [prompt],
            padding="max_length",
            max_length=self.tokenizer.model_max_length,
            truncation=True,
            return_tensors="pt",
        )
        text_input_ids = text_inputs.input_ids.to(self.device)
        text_embeddings = self.text_encoder(text_input_ids)[0]
        if text_embeddings.dtype != self.unet.dtype:
            text_embeddings = text_embeddings.to(self.unet.dtype)
        if text_embeddings.shape[0] == 1 and num_images_per_prompt > 1:
            text_embeddings = text_embeddings.repeat(num_images_per_prompt, 1, 1)
        return text_embeddings

    def train_step(self, batch):
        latents = batch['latent'].to(device=self.device, dtype=self.unet.dtype)
        bsz = latents.shape[0]

        noise = torch.randn_like(latents)
        timesteps = torch.randint(
            0, self.scheduler.config.num_train_timesteps, (bsz,),
            device=self.device
        ).long()

        noisy_latents = self.scheduler.add_noise(latents, noise, timesteps)

        prompt = f"A photo of {self.placeholder_token}"
        text_embeddings = self.get_text_embeddings(prompt, num_images_per_prompt=bsz)

        latent_h, latent_w = noisy_latents.shape[2], noisy_latents.shape[3]
        zero_mask = torch.zeros(bsz, 1, latent_h, latent_w,
                                device=self.device, dtype=noisy_latents.dtype)
        zero_masked = torch.zeros(bsz, 4, latent_h, latent_w,
                                  device=self.device, dtype=noisy_latents.dtype)

        unet_input = torch.cat([noisy_latents, zero_mask, zero_masked], dim=1)

        noise_pred = self.unet(
            unet_input, timesteps,
            encoder_hidden_states=text_embeddings,
            return_dict=False,
        )[0]

        loss = F.mse_loss(noise_pred, noise)
        return loss

    def _save_checkpoint(self, checkpoint_path, optimizer, epoch, global_step):
        os.makedirs(checkpoint_path, exist_ok=True)
        self.unet.save_pretrained(os.path.join(checkpoint_path, "unet"))
        self.text_encoder.save_pretrained(os.path.join(checkpoint_path, "text_encoder"))
        torch.save({
            'epoch': epoch,
            'global_step': global_step,
            'optimizer_state_dict': optimizer.state_dict(),
            'lr': optimizer.param_groups[0]['lr'],
        }, os.path.join(checkpoint_path, "training_state.pt"))
        print(f"Checkpoint saved to {checkpoint_path}", flush=True)

    def _load_weights(self, checkpoint_path):
        from safetensors.torch import load_file

        unet_path = os.path.join(checkpoint_path, "unet", "adapter_model.safetensors")
        if os.path.exists(unet_path):
            state = load_file(unet_path)
            missing, unexpected = self.unet.load_state_dict(state, strict=False)
            print(f"  UNet: {len(missing)} missing, {len(unexpected)} unexpected", flush=True)

        te_path = os.path.join(checkpoint_path, "text_encoder", "adapter_model.safetensors")
        if os.path.exists(te_path):
            state = load_file(te_path)
            missing, unexpected = self.text_encoder.load_state_dict(state, strict=False)
            print(f"  TE: {len(missing)} missing, {len(unexpected)} unexpected", flush=True)

        self.trainable_params = []
        for param in self.unet.parameters():
            if param.requires_grad:
                self.trainable_params.append(param)
        for param in self.text_encoder.parameters():
            if param.requires_grad:
                self.trainable_params.append(param)
        print(f"  Trainable params: {len(self.trainable_params)}", flush=True)

    def train(self, all_latents, num_epochs=50, lr=1e-4, output_dir="./defectfill_checkpoints",
              resume_from=None):
        os.makedirs(output_dir, exist_ok=True)

        flat_data = []
        for dtype, latents in all_latents.items():
            for latent in latents:
                flat_data.append({'latent': latent, 'defect_type': dtype})

        print(f"Training data: {len(flat_data)} latent samples", flush=True)

        start_epoch = 0
        global_step = 0
        optimizer_state = None

        if resume_from is not None and os.path.exists(resume_from):
            print(f"Resuming from {resume_from}...", flush=True)
            self._load_weights(resume_from)
            state_path = os.path.join(resume_from, "training_state.pt")
            if os.path.exists(state_path):
                state = torch.load(state_path, map_location=self.device)
                optimizer_state = state.get('optimizer_state_dict')
                start_epoch = state.get('epoch', -1) + 1
                global_step = state.get('global_step', 0)
            print(f"  Loaded. Start epoch {start_epoch + 1}, step {global_step}", flush=True)

        optimizer = torch.optim.AdamW(self.trainable_params, lr=lr, weight_decay=1e-2)
        if optimizer_state is not None:
            optimizer.load_state_dict(optimizer_state)
            print("  Optimizer restored", flush=True)

        print(f"Training epoch {start_epoch + 1} -> {num_epochs}...", flush=True)

        for epoch in range(start_epoch, num_epochs):
            self.unet.train()
            self.text_encoder.train()
            epoch_loss = 0.0

            random.shuffle(flat_data)
            n = len(flat_data)

            pbar = tqdm(range(0, n), desc=f"Epoch {epoch + 1}/{num_epochs}")
            for i in pbar:
                batch = merge_to_batch([flat_data[i]])
                loss = self.train_step(batch)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.trainable_params, max_norm=1.0)
                optimizer.step()

                global_step += 1
                epoch_loss += loss.item()
                pbar.set_postfix({'loss': f"{loss.item():.5f}", 'avg': f"{epoch_loss / (i + 1):.5f}"})

            avg_loss = epoch_loss / n
            print(f"Epoch {epoch + 1} - Avg loss: {avg_loss:.6f}", flush=True)

            checkpoint_path = os.path.join(output_dir, f"checkpoint_epoch_{epoch + 1}")
            self._save_checkpoint(checkpoint_path, optimizer, epoch, global_step)

        final_path = os.path.join(output_dir, "final")
        self._save_checkpoint(final_path, optimizer, num_epochs - 1, global_step)
        print(f"Final model saved to {final_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Train Defect Generator (DreamBooth-style LoRA, fast)")
    parser.add_argument("--dataset_root", type=str,
                        default=r"d:\git\实践\test\defect_patches_512_full")
    parser.add_argument("--output_dir", type=str,
                        default=r"d:\git\实践\test\defect_generator_checkpoints")
    parser.add_argument("--model_id", type=str,
                        default=r"d:\cache\hub\models--runwayml--stable-diffusion-inpainting\snapshots\8a4288a76071f7280aedbdb3253bdb9e9d5d84bb")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--lora_rank", type=int, default=8)
    parser.add_argument("--device", type=str, default="cuda")
    parser.add_argument("--resume_from", type=str, default=None)
    args = parser.parse_args()

    print("=" * 60)
    print("Defect Generator Training (DreamBooth-style, precomputed latents)")
    print("=" * 60)
    print(f"Epochs: {args.epochs}, LR: {args.lr}")
    print("=" * 60)

    pipe = diffusers.StableDiffusionInpaintPipeline.from_pretrained(
        args.model_id,
        torch_dtype=torch.float16 if args.device == "cuda" else torch.float32,
        safety_checker=None,
    )
    pipe = pipe.to(args.device)

    latents_cache = precompute_latents(
        vae=pipe.vae,
        dataset_root=args.dataset_root,
        image_size=512,
        device=args.device,
        dtype=pipe.vae.dtype,
        cache_dir=args.output_dir,
        scaling_factor=pipe.vae.config.scaling_factor,
    )

    del pipe
    torch.cuda.empty_cache()
    print("VAE released from memory", flush=True)

    trainer = DefectGeneratorTrainer(
        model_id=args.model_id, device=args.device, lora_rank=args.lora_rank,
    )

    print("Starting training...", flush=True)
    trainer.train(all_latents=latents_cache, num_epochs=args.epochs, lr=args.lr,
                  output_dir=args.output_dir, resume_from=args.resume_from)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR: {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
