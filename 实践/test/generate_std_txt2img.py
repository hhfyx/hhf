import os
import argparse
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
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


def build_standard_pipeline(inpaint_model_path, checkpoint_dir, device, dtype):
    import diffusers
    from peft import PeftModel

    print("Loading inpainting pipeline...", flush=True)
    inpaint_pipe = diffusers.StableDiffusionInpaintPipeline.from_pretrained(
        inpaint_model_path,
        torch_dtype=dtype,
        safety_checker=None,
    )
    inpaint_pipe = inpaint_pipe.to(device)

    print("Loading LoRA into UNet...", flush=True)
    unet_path = os.path.join(checkpoint_dir, "unet")
    te_path = os.path.join(checkpoint_dir, "text_encoder")

    if os.path.exists(unet_path):
        inpaint_pipe.unet = PeftModel.from_pretrained(inpaint_pipe.unet, unet_path)
        inpaint_pipe.unet = inpaint_pipe.unet.merge_and_unload()
        print("  UNet LoRA merged", flush=True)
    if os.path.exists(te_path):
        inpaint_pipe.tokenizer.add_tokens(["<defect>"])
        inpaint_pipe.text_encoder.resize_token_embeddings(len(inpaint_pipe.tokenizer))
        inpaint_pipe.text_encoder = PeftModel.from_pretrained(inpaint_pipe.text_encoder, te_path)
        inpaint_pipe.text_encoder = inpaint_pipe.text_encoder.merge_and_unload()
        print("  Text Encoder LoRA merged", flush=True)

    print("Converting Inpainting UNet (9ch) → Standard UNet (4ch)...", flush=True)
    inpaint_unet = inpaint_pipe.unet
    state_dict = inpaint_unet.state_dict()

    conv_in_weight = state_dict["conv_in.weight"]
    conv_in_bias = state_dict["conv_in.bias"]
    state_dict["conv_in.weight"] = conv_in_weight[:, :4].clone()
    state_dict["conv_in.bias"] = conv_in_bias.clone()

    unet_config = dict(inpaint_unet.config)
    unet_config["in_channels"] = 4

    from diffusers import UNet2DConditionModel
    std_unet = UNet2DConditionModel(**unet_config)
    std_unet.load_state_dict(state_dict, strict=True)
    std_unet = std_unet.to(device=device, dtype=dtype)
    print("  Done", flush=True)

    tokenizer = inpaint_pipe.tokenizer
    text_encoder = inpaint_pipe.text_encoder

    print("Building standard StableDiffusionPipeline...", flush=True)
    std_pipe = diffusers.StableDiffusionPipeline(
        vae=inpaint_pipe.vae,
        text_encoder=text_encoder,
        tokenizer=tokenizer,
        unet=std_unet,
        scheduler=inpaint_pipe.scheduler,
        safety_checker=None,
        feature_extractor=None,
        requires_safety_checker=False,
    )
    std_pipe = std_pipe.to(device)
    print("  Standard pipeline ready", flush=True)

    del inpaint_pipe
    torch.cuda.empty_cache()

    return std_pipe


def main():
    parser = argparse.ArgumentParser(description="Txt2Img Defect Generation (Standard SD Pipeline)")
    parser.add_argument("--dataset_root", type=str,
                        default=r"d:\git\实践\test\defect_merged")
    parser.add_argument("--checkpoint_dir", type=str,
                        default=r"d:\git\实践\test\defect_generator_checkpoints_v2\checkpoint_epoch_6")
    parser.add_argument("--output_dir", type=str,
                        default=r"d:\git\实践\test\defectfill_output\variations_std")
    parser.add_argument("--model_path", type=str,
                        default=r"d:\cache\hub\models--runwayml--stable-diffusion-inpainting\snapshots\8a4288a76071f7280aedbdb3253bdb9e9d5d84bb")
    parser.add_argument("--per_type", type=int, default=5)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=7.5)
    parser.add_argument("--device", type=str, default="cuda")
    args = parser.parse_args()

    dtype = torch.float16 if args.device == "cuda" else torch.float32

    print("=" * 60)
    print("Standard SD txt2img Defect Generator")
    print(f"UNet: 4ch (converted from Inpainting), Steps: {args.steps}, Guidance: {args.guidance}")
    print("=" * 60)

    defect_groups = build_defect_dataset(args.dataset_root)
    dtype_list = sorted(defect_groups.keys())
    print(f"Dataset: {sum(len(v) for v in defect_groups.values())} defects, {len(dtype_list)} types: {dtype_list}")

    pipe = build_standard_pipeline(args.model_path, args.checkpoint_dir, args.device, dtype)

    os.makedirs(os.path.join(args.output_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, "labels"), exist_ok=True)

    total = args.per_type * len(dtype_list)
    class_id_map = {dtype: idx for idx, dtype in enumerate(dtype_list)}
    placeholder = "<defect>"

    pbar = tqdm(total=total, desc="txt2img")
    for dtype in dtype_list:
        object_name = OBJECT_NAMES.get(str(dtype), 'object')
        prompt = f"A photo of a {object_name} with {placeholder}"

        for i in range(args.per_type):
            with torch.no_grad():
                result = pipe(
                    prompt=prompt,
                    num_inference_steps=args.steps,
                    guidance_scale=args.guidance,
                    output_type="np",
                ).images[0]

            img_bgr = cv2.cvtColor(result, cv2.COLOR_RGB2BGR)
            out_name = f"type{dtype}_{i:02d}"
            imwrite_unicode(os.path.join(args.output_dir, "images", f"{out_name}.png"), img_bgr)
            with open(os.path.join(args.output_dir, "labels", f"{out_name}.txt"), 'w', encoding='utf-8') as f:
                f.write(f"{class_id_map[dtype]} 0.5 0.5 1.0 1.0\n")

            pbar.update(1)

    pbar.close()
    print(f"\nDone! {total} images in {args.output_dir}")


if __name__ == "__main__":
    main()
