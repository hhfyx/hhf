import os
import re
import argparse
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
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


def parse_yolo_labels(txt_path):
    bboxes = []
    with open(txt_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                class_id = int(parts[0])
                cx = float(parts[1])
                cy = float(parts[2])
                w = float(parts[3])
                h = float(parts[4])
            except (ValueError, IndexError):
                continue
            if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < w <= 1 and 0 < h <= 1):
                continue
            bboxes.append((class_id, cx, cy, w, h))
    return bboxes


def crop_foreground(img, bbox, padding_ratio=0.0):
    h, w = img.shape[:2]
    class_id, cx, cy, bw, bh = bbox

    x1 = int((cx - bw / 2) * w)
    y1 = int((cy - bh / 2) * h)
    x2 = int((cx + bw / 2) * w)
    y2 = int((cy + bh / 2) * h)

    if padding_ratio > 0:
        pad_w = int(bw * w * padding_ratio)
        pad_h = int(bh * h * padding_ratio)
        x1 = max(0, x1 - pad_w)
        y1 = max(0, y1 - pad_h)
        x2 = min(w, x2 + pad_w)
        y2 = min(h, y2 + pad_h)

    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return None

    crop = img[y1:y2, x1:x2]
    return crop


def main():
    parser = argparse.ArgumentParser(description="YOLO bbox foreground cropping")
    parser.add_argument("--data_dir", type=str, default=r"d:\git\实践\test\data")
    parser.add_argument("--output_dir", type=str, default=r"d:\git\实践\test\data_foreground")
    parser.add_argument("--padding", type=float, default=0.05, help="extra padding ratio around bbox")
    parser.add_argument("--min_size", type=int, default=20, help="minimum crop size in pixels")
    parser.add_argument("--max_size", type=int, default=512, help="resize crops to this square size, 0 to skip")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    jpgs = sorted([p for p in data_dir.glob("*.jpg") if "副本" not in p.name])

    stats = defaultdict(lambda: {"cropped": 0, "skipped_small": 0, "no_label": 0})

    total_crops = 0
    for jpg_path in tqdm(jpgs, desc="Cropping foreground"):
        txt_path = jpg_path.with_suffix(".txt")
        if not txt_path.exists():
            stats["__no_txt__"]["no_label"] += 1
            continue

        bboxes = parse_yolo_labels(str(txt_path))
        if not bboxes:
            continue

        img = imread_unicode(str(jpg_path))
        if img is None:
            continue

        scene_type = jpg_path.stem.split("_")[-1]

        for i, bbox in enumerate(bboxes):
            crop = crop_foreground(img, bbox, padding_ratio=args.padding)
            if crop is None:
                continue

            if crop.shape[0] < args.min_size or crop.shape[1] < args.min_size:
                stats[str(bbox[0])]["skipped_small"] += 1
                continue

            if args.max_size > 0:
                max_dim = max(crop.shape[0], crop.shape[1])
                if max_dim > 0:
                    scale = args.max_size / max_dim
                    new_w = int(crop.shape[1] * scale)
                    new_h = int(crop.shape[0] * scale)
                    crop = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

            class_id = bbox[0]
            class_dir = output_dir / f"class_{class_id}"
            class_dir.mkdir(exist_ok=True)

            base_name = jpg_path.stem
            out_name = f"{base_name}_crop{i:02d}_scene{scene_type}.png"
            out_path = class_dir / out_name
            imwrite_unicode(str(out_path), crop)

            stats[str(class_id)]["cropped"] += 1
            total_crops += 1

    print(f"\nDone! {total_crops} foreground crops in {output_dir}")
    for cls in sorted(stats.keys()):
        s = stats[cls]
        print(f"  class_{cls}: {s['cropped']} cropped, {s.get('skipped_small',0)} skipped(small), {s.get('no_label',0)} no label")


if __name__ == "__main__":
    main()
