import os
import argparse
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm


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


def imwrite_unicode(path, img):
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg']:
            ext = '.png'
        result, encoded_img = cv2.imencode(ext, img, [int(cv2.IMWRITE_PNG_COMPRESSION), 3])
        if result:
            with open(path, 'wb') as f:
                f.write(encoded_img.tobytes())
            return True
        return False
    except:
        return False


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


OBJECT_NAMES = {
    '0': 'capsule', '1': 'capsule', '8': 'capsule', '9': 'capsule',
    '2': 'bottle', '3': 'cable', '4': 'carpet', '5': 'grid',
    '6': 'hazelnut', '7': 'leather',
    'a': 'label', 'b': 'package',
}


class DefectVariationGenerator:
    def __init__(self, model_path, checkpoint_dir, device="cuda"):
        self.device = device
        import diffusers
        print("Loading inpainting pipeline...", flush=True)
        self.pipe = diffusers.StableDiffusionInpaintPipeline.from_pretrained(
            model_path,
            torch_dtype=torch.float16,
            safety_checker=None,
        )
        self.pipe = self.pipe.to(device)

        self.placeholder_token = "<defect>"
        self.pipe.tokenizer.add_tokens([self.placeholder_token])
        self.pipe.text_encoder.resize_token_embeddings(len(self.pipe.tokenizer))

        if checkpoint_dir and os.path.exists(checkpoint_dir):
            self._load_checkpoint(checkpoint_dir)

    def _load_checkpoint(self, checkpoint_dir):
        from peft import PeftModel
        unet_path = os.path.join(checkpoint_dir, "unet")
        if os.path.exists(unet_path):
            self.pipe.unet = PeftModel.from_pretrained(self.pipe.unet, unet_path)
            self.pipe.unet = self.pipe.unet.merge_and_unload()
            print("  LoRA merged", flush=True)
        te_path = os.path.join(checkpoint_dir, "text_encoder")
        if os.path.exists(te_path):
            self.pipe.text_encoder = PeftModel.from_pretrained(self.pipe.text_encoder, te_path)
            self.pipe.text_encoder = self.pipe.text_encoder.merge_and_unload()

    def _get_prompt(self, defect_type):
        object_name = OBJECT_NAMES.get(str(defect_type), 'object')
        return f"A photo of a {object_name} with {self.placeholder_token}"

    @torch.no_grad()
    def generate_txt2img(self, defect_type, image_size=(512, 512), num_samples=4,
                         steps=50, guidance=7.5):
        prompt = self._get_prompt(defect_type)
        latent_h = image_size[0] // 8
        latent_w = image_size[1] // 8

        latents = torch.randn(
            num_samples, 4, latent_h, latent_w,
            device=self.device, dtype=self.pipe.vae.dtype,
        )

        pos_ids = self.pipe.tokenizer(
            [prompt] * num_samples, padding="max_length",
            max_length=self.pipe.tokenizer.model_max_length, truncation=True,
            return_tensors="pt",
        ).input_ids.to(self.device)
        pos_emb = self.pipe.text_encoder(pos_ids)[0]

        neg_ids = self.pipe.tokenizer(
            [""] * num_samples, padding="max_length",
            max_length=self.pipe.tokenizer.model_max_length, truncation=True,
            return_tensors="pt",
        ).input_ids.to(self.device)
        neg_emb = self.pipe.text_encoder(neg_ids)[0]

        text_emb = torch.cat([neg_emb, pos_emb])

        self.pipe.scheduler.set_timesteps(steps, device=self.device)
        timesteps = self.pipe.scheduler.timesteps

        latents = latents * self.pipe.scheduler.init_noise_sigma

        mask_blank = torch.zeros(num_samples * 2, 1, latent_h, latent_w,
                                 device=self.device, dtype=latents.dtype)
        masked_blank = torch.zeros(num_samples * 2, 4, latent_h, latent_w,
                                   device=self.device, dtype=latents.dtype)

        for t in timesteps:
            latent_input = torch.cat([latents] * 2)
            latent_input = self.pipe.scheduler.scale_model_input(latent_input, t)
            unet_input = torch.cat([latent_input, mask_blank, masked_blank], dim=1)

            noise_pred = self.pipe.unet(
                unet_input, t.expand(num_samples * 2),
                encoder_hidden_states=text_emb,
                return_dict=False,
            )[0]

            noise_pred_uncond, noise_pred_text = noise_pred.chunk(2)
            noise_pred = noise_pred_uncond + guidance * (noise_pred_text - noise_pred_uncond)
            latents = self.pipe.scheduler.step(noise_pred, t, latents).prev_sample

        latents = latents / self.pipe.vae.config.scaling_factor
        decoded = self.pipe.vae.decode(latents).sample
        decoded = (decoded / 2 + 0.5).clamp(0, 1)
        decoded = decoded.permute(0, 2, 3, 1).cpu().float().numpy()
        decoded = (decoded * 255).astype(np.uint8)

        return [cv2.cvtColor(decoded[i], cv2.COLOR_RGB2BGR) for i in range(num_samples)]

    @torch.no_grad()
    def generate_img2img(self, reference_image, defect_type, num_samples=1,
                         steps=50, strength=0.75, guidance=7.5):
        prompt = self._get_prompt(defect_type)
        h, w = reference_image.shape[:2]

        ref_rgb = cv2.cvtColor(reference_image, cv2.COLOR_BGR2RGB)
        ref_pil = Image.fromarray(ref_rgb).resize((512, 512))
        ref_tensor = torch.from_numpy(np.array(ref_pil)).float().permute(2, 0, 1).unsqueeze(0) / 255.0
        ref_tensor = (ref_tensor - 0.5) * 2.0
        ref_tensor = ref_tensor.to(device=self.device, dtype=self.pipe.vae.dtype)

        init_latents = self.pipe.vae.encode(ref_tensor).latent_dist.sample()
        init_latents = init_latents * self.pipe.vae.config.scaling_factor
        init_latents = init_latents.repeat(num_samples, 1, 1, 1)

        pos_ids = self.pipe.tokenizer(
            [prompt] * num_samples, padding="max_length",
            max_length=self.pipe.tokenizer.model_max_length, truncation=True,
            return_tensors="pt",
        ).input_ids.to(self.device)
        pos_emb = self.pipe.text_encoder(pos_ids)[0]

        neg_ids = self.pipe.tokenizer(
            [""] * num_samples, padding="max_length",
            max_length=self.pipe.tokenizer.model_max_length, truncation=True,
            return_tensors="pt",
        ).input_ids.to(self.device)
        neg_emb = self.pipe.text_encoder(neg_ids)[0]

        text_emb = torch.cat([neg_emb, pos_emb])

        self.pipe.scheduler.set_timesteps(steps, device=self.device)
        timesteps = self.pipe.scheduler.timesteps

        init_timestep = min(int(steps * strength), steps - 1)
        t_start = timesteps[init_timestep]
        timesteps = timesteps[init_timestep:]

        noise = torch.randn(init_latents.shape, device=self.device, dtype=init_latents.dtype)
        latents = self.pipe.scheduler.add_noise(init_latents, noise, t_start.expand(num_samples))

        latent_h, latent_w = latents.shape[2], latents.shape[3]
        mask_blank = torch.zeros(num_samples * 2, 1, latent_h, latent_w,
                                 device=self.device, dtype=latents.dtype)
        masked_blank = torch.zeros(num_samples * 2, 4, latent_h, latent_w,
                                   device=self.device, dtype=latents.dtype)

        for t in timesteps:
            latent_input = torch.cat([latents] * 2)
            latent_input = self.pipe.scheduler.scale_model_input(latent_input, t)
            unet_input = torch.cat([latent_input, mask_blank, masked_blank], dim=1)

            noise_pred = self.pipe.unet(
                unet_input, t.expand(num_samples * 2),
                encoder_hidden_states=text_emb,
                return_dict=False,
            )[0]

            noise_pred_uncond, noise_pred_text = noise_pred.chunk(2)
            noise_pred = noise_pred_uncond + guidance * (noise_pred_text - noise_pred_uncond)
            latents = self.pipe.scheduler.step(noise_pred, t, latents).prev_sample

        latents = latents / self.pipe.vae.config.scaling_factor
        decoded = self.pipe.vae.decode(latents).sample
        decoded = (decoded / 2 + 0.5).clamp(0, 1)
        decoded = decoded.permute(0, 2, 3, 1).cpu().float().numpy()
        decoded = (decoded * 255).astype(np.uint8)

        results = []
        for i in range(num_samples):
            img = cv2.cvtColor(decoded[i], cv2.COLOR_RGB2BGR)
            img = cv2.resize(img, (w, h))
            results.append(img)
        return results


def run_mode(generator, mode, defect_groups, per_type, steps, guidance, strength, output_base):
    dtype_list = sorted(defect_groups.keys())
    out_dir = os.path.join(output_base, mode)
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "labels"), exist_ok=True)

    total = per_type * len(dtype_list)
    class_id_map = {dtype: idx for idx, dtype in enumerate(dtype_list)}

    if mode == "txt2img":
        print(f"\n{'='*60}")
        print(f"Mode: txt2img (从纯噪声生成全新缺陷)")
        print(f"{'='*60}")
        pbar = tqdm(total=total, desc="txt2img")
        for dtype in dtype_list:
            for i in range(per_type):
                results = generator.generate_txt2img(dtype, num_samples=1, steps=steps, guidance=guidance)
                out_name = f"type{dtype}_{i:02d}"
                imwrite_unicode(os.path.join(out_dir, "images", f"{out_name}.png"), results[0])
                with open(os.path.join(out_dir, "labels", f"{out_name}.txt"), 'w', encoding='utf-8') as f:
                    f.write(f"{class_id_map[dtype]} 0.5 0.5 1.0 1.0\n")
                pbar.update(1)
        pbar.close()

    elif mode == "img2img":
        print(f"\n{'='*60}")
        print(f"Mode: img2img (基于参考图变异, strength={strength})")
        print(f"{'='*60}")
        pbar = tqdm(total=total, desc="img2img")
        for dtype in dtype_list:
            items = defect_groups[dtype]
            for i in range(per_type):
                ref_path = items[i % len(items)]['path']
                ref_img = imread_unicode(ref_path)
                if ref_img is None:
                    continue
                results = generator.generate_img2img(ref_img, dtype, num_samples=1,
                                                     steps=steps, strength=strength, guidance=guidance)
                out_name = f"type{dtype}_{i:02d}"
                imwrite_unicode(os.path.join(out_dir, "images", f"{out_name}.png"), results[0])
                with open(os.path.join(out_dir, "labels", f"{out_name}.txt"), 'w', encoding='utf-8') as f:
                    f.write(f"{class_id_map[dtype]} 0.5 0.5 1.0 1.0\n")
                pbar.update(1)
        pbar.close()

    print(f"  → {total} images → {out_dir}")


def main():
    parser = argparse.ArgumentParser(description="Generate defect variations (txt2img + img2img)")
    parser.add_argument("--dataset_root", type=str,
                        default=r"d:\git\实践\test\defect_merged")
    parser.add_argument("--checkpoint_dir", type=str,
                        default=r"d:\git\实践\test\defect_generator_checkpoints_v2\checkpoint_epoch_6")
    parser.add_argument("--output_dir", type=str,
                        default=r"d:\git\实践\test\defectfill_output\variations_v2")
    parser.add_argument("--model_path", type=str,
                        default=r"d:\cache\hub\models--runwayml--stable-diffusion-inpainting\snapshots\8a4288a76071f7280aedbdb3253bdb9e9d5d84bb")
    parser.add_argument("--mode", type=str, default="both",
                        choices=["txt2img", "img2img", "both"])
    parser.add_argument("--per_type", type=int, default=5)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--strength", type=float, default=0.85)
    parser.add_argument("--device", type=str, default="cuda")
    args = parser.parse_args()

    print("=" * 60)
    print("Defect Generator")
    print(f"Mode: {args.mode}, Per type: {args.per_type}, Steps: {args.steps}, Guidance: {args.guidance}")
    if args.mode in ("img2img", "both"):
        print(f"img2img strength: {args.strength}")
    print("=" * 60)

    defect_groups = build_defect_dataset(args.dataset_root)
    dtype_list = sorted(defect_groups.keys())
    print(f"Dataset: {sum(len(v) for v in defect_groups.values())} defects, {len(dtype_list)} types: {dtype_list}")

    generator = DefectVariationGenerator(args.model_path, args.checkpoint_dir, args.device)

    modes = []
    if args.mode == "both":
        modes = ["txt2img", "img2img"]
    else:
        modes = [args.mode]

    for m in modes:
        run_mode(generator, m, defect_groups, args.per_type,
                 args.steps, args.guidance, args.strength, args.output_dir)

    print(f"\nAll done! Results in {args.output_dir}")


if __name__ == "__main__":
    main()
