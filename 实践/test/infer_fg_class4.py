"""
对 fg_class_4（颜色胶布缺陷）运行 img2img 推理
"""
import os, sys
import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from tqdm import tqdm
import diffusers
from peft import PeftModel


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


@torch.no_grad()
def generate_img2img(pipe, reference_image, prompt, num_samples=1,
                     steps=50, strength=0.85, guidance=7.5, device="cuda"):
    """对参考图做 img2img 变异"""
    h, w = reference_image.shape[:2]

    # 预处理参考图
    ref_rgb = cv2.cvtColor(reference_image, cv2.COLOR_BGR2RGB)
    ref_pil = Image.fromarray(ref_rgb).resize((512, 512))
    ref_tensor = torch.from_numpy(np.array(ref_pil)).float().permute(2, 0, 1).unsqueeze(0) / 255.0
    ref_tensor = (ref_tensor - 0.5) * 2.0
    ref_tensor = ref_tensor.to(device=device, dtype=pipe.vae.dtype)

    init_latents = pipe.vae.encode(ref_tensor).latent_dist.sample()
    init_latents = init_latents * pipe.vae.config.scaling_factor
    init_latents = init_latents.repeat(num_samples, 1, 1, 1)

    # Text embeddings
    pos_ids = pipe.tokenizer(
        [prompt] * num_samples, padding="max_length",
        max_length=pipe.tokenizer.model_max_length, truncation=True,
        return_tensors="pt",
    ).input_ids.to(device)
    pos_emb = pipe.text_encoder(pos_ids)[0]

    neg_ids = pipe.tokenizer(
        [""] * num_samples, padding="max_length",
        max_length=pipe.tokenizer.model_max_length, truncation=True,
        return_tensors="pt",
    ).input_ids.to(device)
    neg_emb = pipe.text_encoder(neg_ids)[0]

    text_emb = torch.cat([neg_emb, pos_emb])

    # Scheduler
    pipe.scheduler.set_timesteps(steps, device=device)
    all_timesteps = pipe.scheduler.timesteps

    init_timestep = min(int(steps * strength), steps - 1)
    t_start = all_timesteps[init_timestep]
    timesteps = all_timesteps[init_timestep:]

    noise = torch.randn(init_latents.shape, device=device, dtype=init_latents.dtype)
    latents = pipe.scheduler.add_noise(init_latents, noise, t_start.expand(num_samples))

    latent_h, latent_w = latents.shape[2], latents.shape[3]
    mask_blank = torch.zeros(num_samples * 2, 1, latent_h, latent_w,
                             device=device, dtype=latents.dtype)
    masked_blank = torch.zeros(num_samples * 2, 4, latent_h, latent_w,
                               device=device, dtype=latents.dtype)

    # Denoising loop
    pbar_steps = tqdm(timesteps, desc=f"Denoising", leave=False)
    for t in pbar_steps:
        latent_input = torch.cat([latents] * 2)
        latent_input = pipe.scheduler.scale_model_input(latent_input, t)
        unet_input = torch.cat([latent_input, mask_blank, masked_blank], dim=1)

        noise_pred = pipe.unet(
            unet_input, t.expand(num_samples * 2),
            encoder_hidden_states=text_emb,
            return_dict=False,
        )[0]

        noise_pred_uncond, noise_pred_text = noise_pred.chunk(2)
        noise_pred = noise_pred_uncond + guidance * (noise_pred_text - noise_pred_uncond)
        latents = pipe.scheduler.step(noise_pred, t, latents).prev_sample

    # Decode
    latents = latents / pipe.vae.config.scaling_factor
    decoded = pipe.vae.decode(latents).sample
    decoded = (decoded / 2 + 0.5).clamp(0, 1)
    decoded = decoded.permute(0, 2, 3, 1).cpu().float().numpy()
    decoded = (decoded * 255).astype(np.uint8)

    results = []
    for i in range(num_samples):
        img = cv2.cvtColor(decoded[i], cv2.COLOR_RGB2BGR)
        img = cv2.resize(img, (w, h))
        results.append(img)
    return results


def main():
    parser = argparse.ArgumentParser(description="Infer fg_class_4 with img2img")
    parser.add_argument("--data_dir", type=str,
                        default=r"d:\git\实践\test\defect_merged\fg_class_4")
    parser.add_argument("--checkpoint_dir", type=str,
                        default=r"d:\git\实践\test\defect_generator_checkpoints_v2\checkpoint_epoch_13")
    parser.add_argument("--model_path", type=str,
                        default=r"d:\cache\hub\models--runwayml--stable-diffusion-inpainting\snapshots\8a4288a76071f7280aedbdb3253bdb9e9d5d84bb")
    parser.add_argument("--output_dir", type=str,
                        default=r"d:\git\实践\test\defectfill_output\fg_class4_img2img")
    parser.add_argument("--num_samples", type=int, default=20,
                        help="每个参考图生成多少张变体")
    parser.add_argument("--ref_count", type=int, default=5,
                        help="选几张参考图")
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--strength", type=float, default=0.85)
    parser.add_argument("--guidance", type=float, default=7.5)
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    print("Loading pipeline...", flush=True)
    print(f"Output dir: {args.output_dir}", flush=True)
    pipe = diffusers.StableDiffusionInpaintPipeline.from_pretrained(
        args.model_path,
        torch_dtype=torch.float16,
        safety_checker=None,
    )
    pipe = pipe.to("cuda")

    # Add placeholder
    pipe.tokenizer.add_tokens(["<defect>"])
    pipe.text_encoder.resize_token_embeddings(len(pipe.tokenizer))
    print(f"  Tokenizer size: {len(pipe.tokenizer)}", flush=True)

    # Load LoRA
    if args.checkpoint_dir and os.path.exists(args.checkpoint_dir):
        print(f"  Loading checkpoint from {args.checkpoint_dir}", flush=True)
        unet_path = os.path.join(args.checkpoint_dir, "unet")
        if os.path.exists(unet_path):
            pipe.unet = PeftModel.from_pretrained(pipe.unet, unet_path)
            pipe.unet = pipe.unet.merge_and_unload()
            print("  UNet LoRA loaded & merged", flush=True)
        te_path = os.path.join(args.checkpoint_dir, "text_encoder")
        if os.path.exists(te_path):
            pipe.text_encoder = PeftModel.from_pretrained(pipe.text_encoder, te_path)
            pipe.text_encoder = pipe.text_encoder.merge_and_unload()
            print("  Text Encoder LoRA loaded & merged", flush=True)

    prompt = "A photo of a package with <defect>"

    # Collect reference images
    data_dir = Path(args.data_dir)
    img_paths = sorted([p for p in data_dir.iterdir() if p.suffix.lower() in ('.png', '.jpg', '.jpeg')])
    print(f"Found {len(img_paths)} images in fg_class_4", flush=True)

    # Select reference images
    ref_paths = img_paths[:args.ref_count]
    print(f"Using {len(ref_paths)} reference images", flush=True)

    # Run img2img for each reference
    total_gen = 0
    for ref_idx, ref_path in enumerate(ref_paths):
        ref_img = imread_unicode(str(ref_path))
        if ref_img is None:
            print(f"  Skipping {ref_path.name} (cannot read)", flush=True)
            continue

        print(f"\nReference [{ref_idx+1}/{len(ref_paths)}]: {ref_path.name}", flush=True)

        results = generate_img2img(
            pipe, ref_img, prompt,
            num_samples=args.num_samples,
            steps=args.steps,
            strength=args.strength,
            guidance=args.guidance,
            device="cuda",
        )

        for i, img in enumerate(results):
            out_name = f"fg4_ref{ref_idx:02d}_var{i:02d}.png"
            imwrite_unicode(os.path.join(args.output_dir, out_name), img)
            total_gen += 1

        print(f"  Generated {len(results)} variants", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"Done! {total_gen} images saved to {args.output_dir}", flush=True)
    # Verify files
    saved = list(Path(args.output_dir).glob("*.png"))
    print(f"Verified: {len(saved)} PNG files in output directory", flush=True)
    print(f"{'='*60}", flush=True)


if __name__ == "__main__":
    main()
