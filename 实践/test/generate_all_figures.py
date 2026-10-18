# -*- coding: utf-8 -*-
"""
Generate all 15 figures for the high-completion model practice summary.
Output: figures/ directory
"""

import os, sys, glob
os.environ['PYTHONIOENCODING'] = 'utf-8'

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
from PIL import Image
import random

BASE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE, "figures")
os.makedirs(OUTPUT_DIR, exist_ok=True)

plt.rcParams.update({
    'font.size': 12,
    'axes.titlesize': 14,
    'axes.labelsize': 12,
    'figure.dpi': 150,
})

# Chinese font support
plt.rcParams['font.sans-serif'] = ['SimHei', 'DengXian', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

def imread_unicode(path):
    try:
        return Image.open(path).convert('RGB')
    except:
        return None


# ============================================================
# Helper: draw block
# ============================================================
def draw_block(ax, x, y, w, h, color, label, sub='', alpha=0.9, fontsize=10, sub_size=8):
    box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                          facecolor=color, edgecolor='#333', linewidth=2, alpha=alpha)
    ax.add_patch(box)
    ax.text(x + w/2, y + h*0.65, label, ha='center', va='center',
            fontsize=fontsize, fontweight='bold', color='white')
    if sub:
        ax.text(x + w/2, y + h*0.3, sub, ha='center', va='center',
                fontsize=sub_size, color='white')


def draw_arrow(ax, x1, y1, x2, y2, lw=2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', lw=lw, color='#555'))


# ============================================================
# Fig 2.1: Foreground crop pipeline
# ============================================================
def fig_2_1_foreground_crop():
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.5))
    steps = [
        ("Original Image\n(YOLO labeled)", "data/\nFull industrial image\nwith defect bboxes", '#e8f4f8', '#2980b9'),
        ("Foreground Crop\n+ Resize", "data_foreground/\nCrop + 5% padding\nResize to 512x512", '#fef9e7', '#f39c12'),
        ("Defect Patches", "defect_merged/\n3323 images, 6 types\n512x512 defect patches", '#e8f8f5', '#27ae60'),
    ]
    for ax, (title, desc, bg, border) in zip(axes, steps):
        ax.add_patch(FancyBboxPatch((0.05, 0.05), 0.9, 0.9,
                                     boxstyle="round,pad=0.1",
                                     facecolor=bg, edgecolor=border, linewidth=3))
        ax.text(0.5, 0.7, title, ha='center', va='center', fontsize=12, fontweight='bold', color=border)
        ax.text(0.5, 0.35, desc, ha='center', va='center', fontsize=9, color='#444')
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')

    # Arrows between panels
    for i in range(2):
        fig.add_artist(FancyArrowPatch((0.32+i*0.33, 0.5), (0.37+i*0.33, 0.5),
                                        arrowstyle='->', mutation_scale=25, lw=2.5, color='#e74c3c'))
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig2_1_foreground_crop.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig2_1")


# ============================================================
# Fig 2.2: Defect count bar chart
# ============================================================
def fig_2_2_defect_count_bar():
    types = ['type 0', 'type 1', 'type 8', 'type 9', 'type a', 'type b']
    subtitles = ['surface defect', 'surface defect', 'surface defect',
                 'surface defect', 'label hole', 'color tape']
    counts = [219, 329, 303, 796, 876, 641]
    colors = ['#3498db', '#2ecc71', '#9b59b6', '#f39c12', '#e74c3c', '#1abc9c']

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.bar(types, counts, color=colors, edgecolor='white', linewidth=1.5, width=0.6)

    for bar, count, sub in zip(bars, counts, subtitles):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 15,
                str(count), ha='center', va='bottom', fontsize=10, fontweight='bold')
        ax.text(bar.get_x() + bar.get_width()/2, -45,
                sub, ha='center', va='top', fontsize=7, color='#777', style='italic')

    ax.set_ylabel('Sample Count', fontsize=11)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.set_ylim(0, 1100)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig2_2_defect_count_bar.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig2_2")


# ============================================================
# Fig 2.3: Six defect type samples
# ============================================================
def fig_2_3_defect_samples():
    merged_dir = os.path.join(BASE, "defect_merged")
    type_info = [
        ('type 0', '00_class_0'), ('type 1', '02_class_2'),
        ('type 8', '05_class_5'), ('type 9', '00_class_0'),
        ('type a', 'fg_class_1'), ('type b', 'fg_class_4'),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))

    for idx, (label, dirname) in enumerate(type_info):
        row, col = idx // 3, idx % 3
        ax = axes[row, col]
        subdir = os.path.join(merged_dir, dirname)
        found = False
        if os.path.isdir(subdir):
            pngs = glob.glob(os.path.join(subdir, "*.png"))
            if pngs:
                img_path = random.choice(pngs)
                img = imread_unicode(img_path)
                if img:
                    ax.imshow(img)
                    found = True
        if not found:
            ax.text(0.5, 0.5, label, ha='center', va='center', transform=ax.transAxes, fontsize=14)
        ax.set_title(label, fontsize=13, fontweight='bold', pad=8)
        ax.axis('off')

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig2_3_defect_samples.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig2_3")


# ============================================================
# Fig 3.1: SD+LoRA architecture (SIMPLIFIED, clean layout)
# ============================================================
def fig_3_1_sd_lora_architecture():
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6.5); ax.axis('off')

    # --- Row 1: Input side ---
    # Text Encoder (left)
    draw_block(ax, 0.8, 4.8, 2.2, 1.2, '#3498db', 'Text Encoder', 'CLIP, frozen', fontsize=10)
    draw_block(ax, 1.2, 3.8, 1.5, 0.5, '#f39c12', '+ LoRA', 'k/q/v/out, r=8', fontsize=9, sub_size=7, alpha=0.85)

    # VAE (right)
    draw_block(ax, 9.0, 4.8, 2.2, 1.2, '#9b59b6', 'VAE Encoder', 'frozen', fontsize=10)

    # --- Row 2: UNet (center, large) ---
    draw_block(ax, 1.0, 0.8, 10.0, 2.5, '#c0392b', 'UNet (Inpainting, 9-ch input)', '',
               fontsize=11, sub_size=0)

    # UNet sub-modules
    draw_block(ax, 1.3, 1.0, 4.5, 0.8, '#e74c3c', 'DownBlock x3', 'ResBlock + Attn + LoRA',
               fontsize=9, sub_size=7)
    draw_block(ax, 6.2, 1.0, 4.5, 0.8, '#e74c3c', 'MiddleBlock x2 + UpBlock x3',
               'Skip Connection + LoRA', fontsize=9, sub_size=7)
    draw_block(ax, 1.3, 2.1, 4.5, 0.5, '#e67e22', 'Input: noisy(4)+mask(1)+masked(4)',
               '', fontsize=8, sub_size=0, alpha=0.85)
    draw_block(ax, 6.2, 2.1, 4.5, 0.5, '#e67e22',
               'Cross-Attn: Q=hidden, K/V=text', '+ LoRA AxB', fontsize=8, sub_size=7, alpha=0.85)

    # Loss
    draw_block(ax, 4.2, 0.1, 3.6, 0.5, '#27ae60', 'Loss: MSE(eps_pred, eps)',
               "LoRA: W'=W+AxB", fontsize=9, sub_size=7)

    # Arrows
    draw_arrow(ax, 2.5, 3.8, 2.5, 3.3)
    draw_arrow(ax, 1.9, 4.8, 1.9, 3.3)  # text encoder -> unet (left side)
    draw_arrow(ax, 10.1, 4.8, 10.1, 3.3)  # vae -> unet (right side)
    draw_arrow(ax, 6.0, 3.3, 6.0, 0.6)

    # Prompt label
    ax.text(1.9, 5.5, '"A photo of <defect>"', ha='center', fontsize=9, color='#555',
            style='italic')
    ax.annotate('', xy=(1.9, 5.25), xytext=(1.9, 6.0),
                arrowprops=dict(arrowstyle='->', lw=1.5, color='#999'))

    # Speed optimization box (top right corner)
    opt_text = ("Latent precompute: 39->0.3s/step (130x)\n"
                "Grad Checkpoint: -40% VRAM\n"
                "Grad Clipping: max_norm=1.0\n"
                "Trainable params: 2.18M (<1%)")
    ax.text(8.5, 5.8, opt_text, fontsize=8, color='#2c3e50',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#fef9e7', edgecolor='#f39c12', alpha=0.9))

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_1_sd_lora_architecture.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_1")


# ============================================================
# Fig 3.2: Latent precompute speed comparison
# ============================================================
def fig_3_2_latent_speed_comparison():
    labels = ['Before\n(VAE real-time)', 'After\n(Latent precompute)']
    values = [39.0, 0.31]
    colors = ['#e74c3c', '#2ecc71']

    fig, ax = plt.subplots(figsize=(6, 4.5))
    bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=2, width=0.45)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val}s/step', ha='center', va='bottom', fontsize=12, fontweight='bold')

    ax.annotate('130x Speedup!', xy=(1, 0.31), xytext=(0.5, 22),
                arrowprops=dict(arrowstyle='->', lw=2, color='#e74c3c'),
                fontsize=13, fontweight='bold', color='#e74c3c',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='#fef9e7', edgecolor='#e74c3c'))

    ax.set_ylabel('Seconds per step', fontsize=11)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.set_ylim(0, 48)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_2_latent_speed_comparison.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_2")


# ============================================================
# Fig 3.3: Loss curve
# ============================================================
def fig_3_3_loss_curve():
    epochs = list(range(1, 7))
    loss_v2 = [0.139, 0.135, 0.132, 0.130, 0.128, 0.127]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(epochs, loss_v2, 'o-', color='#2ecc71', linewidth=2.5, markersize=8,
            label='V2 (3323 images)')
    for e, l in zip(epochs, loss_v2):
        ax.text(e, l + 0.0015, f'{l:.4f}', ha='center', fontsize=9, color='#2ecc71')

    ax.plot([1, 2], [0.158, 0.157], 's--', color='#e74c3c', linewidth=2, markersize=8,
             label='V1 (1806 images)')
    ax.text(1, 0.155, '0.158', ha='center', fontsize=9, color='#e74c3c')
    ax.text(2, 0.154, '0.157', ha='center', fontsize=9, color='#e74c3c')

    ax.set_xlabel('Epoch', fontsize=11)
    ax.set_ylabel('Loss', fontsize=11)
    ax.legend(fontsize=9, loc='upper right')
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.set_xticks(epochs)
    ax.set_ylim(0.120, 0.165)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_3_loss_curve.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_3")


# ============================================================
# Fig 3.4: txt2img type a
# ============================================================
def fig_3_4_txt2img_type_a():
    candidates = [
        os.path.join(BASE, "defectfill_output", "variations_v2", "txt2img", "images"),
        os.path.join(BASE, "defectfill_output", "variations_v2", "images"),
        os.path.join(BASE, "defectfill_output", "variations_std", "images"),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.2))
    found = False
    for i in range(5):
        ax = axes[i]; ax.axis('off')
        for cd in candidates:
            p = os.path.join(cd, f"typea_0{i}.png")
            if os.path.exists(p):
                img = imread_unicode(p)
                if img:
                    ax.imshow(img); found = True; break
    if not found:
        for ax in axes: ax.text(0.5, 0.5, 'type a', ha='center', va='center')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_4_txt2img_type_a.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_4")


# ============================================================
# Fig 3.5: txt2img type b
# ============================================================
def fig_3_5_txt2img_type_b():
    candidates = [
        os.path.join(BASE, "defectfill_output", "variations_v2", "txt2img", "images"),
        os.path.join(BASE, "defectfill_output", "variations_v2", "images"),
        os.path.join(BASE, "defectfill_output", "variations_std", "images"),
    ]
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.2))
    found = False
    for i in range(5):
        ax = axes[i]; ax.axis('off')
        for cd in candidates:
            p = os.path.join(cd, f"typeb_0{i}.png")
            if os.path.exists(p):
                img = imread_unicode(p)
                if img:
                    ax.imshow(img); found = True; break
    if not found:
        for ax in axes: ax.text(0.5, 0.5, 'type b', ha='center', va='center')
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_5_txt2img_type_b.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_5")


# ============================================================
# Fig 3.6: img2img variation
# ============================================================
def fig_3_6_img2img_variation():
    candidates = [
        os.path.join(BASE, "defectfill_output", "variations_v2", "img2img", "images"),
        os.path.join(BASE, "defectfill_output", "variations_v2", "images"),
    ]
    fig, axes = plt.subplots(1, 6, figsize=(16, 3))
    labels = ['Reference', 'Var 1', 'Var 2', 'Var 3', 'Var 4', 'Var 5']
    for i in range(6):
        ax = axes[i]; ax.axis('off')
        for cd in candidates:
            p = os.path.join(cd, f"type9_0{i}.png")
            if os.path.exists(p):
                img = imread_unicode(p)
                if img: ax.imshow(img); break
        ax.set_title(labels[i], fontsize=10, pad=5)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_6_img2img_variation.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_6")


# ============================================================
# Fig 3.7: Pix2Pix architecture (SIMPLIFIED)
# ============================================================
def fig_3_7_pix2pix_architecture():
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis('off')

    # --- Row 1: Generator path ---
    draw_block(ax, 0.3, 4.2, 2.0, 0.9, '#e67e22', 'Input', 'normal product, 3x256', fontsize=10)

    # Generator main box
    draw_block(ax, 3.0, 3.5, 6.0, 1.8, '#2980b9', 'Generator (UNet)', '', fontsize=12)

    # Encoder blocks
    enc_w = 1.2
    for i, (l, c) in enumerate(zip(['Enc1\n3->64', 'Enc2\n64->128', 'Enc3\n128->256', 'Enc4\n256->512'],
                                     ['#1a5276', '#1f618d', '#2980b9', '#5dade2'])):
        draw_block(ax, 3.3 + i*(enc_w+0.15), 4.1, enc_w, 0.8, c, l, '', fontsize=8, sub_size=0)

    # Decoder blocks
    for i, (l, c) in enumerate(zip(['Dec4<-E3', 'Dec3<-E2', 'Dec2<-E1', 'Tanh->3'],
                                     ['#5dade2', '#2980b9', '#1f618d', '#1a5276'])):
        draw_block(ax, 3.3 + i*(enc_w+0.15), 3.6, enc_w, 0.45, c, l, '', fontsize=7, sub_size=0)

    draw_block(ax, 9.5, 4.2, 2.0, 0.9, '#e74c3c', 'Output', 'defect image, 3x256', fontsize=10)

    # --- Row 2: Discriminator ---
    draw_block(ax, 3.0, 1.0, 6.0, 1.8, '#8e44ad', 'Discriminator (PatchGAN)', '', fontsize=12)

    disc_w = 1.1
    disc_items = [('Input\n6x256', 'Cat[Norm,\nDefect]'),
                  ('Conv\n6->64', 'k=4,s=2'),
                  ('Conv\n64->128', '+BN'),
                  ('Conv\n128->256', '+BN'),
                  ('Conv\n256->512', '+BN'),
                  ('Conv+Pool\n512->1', 'Adaptive\nAvgPool')]
    for i, (l, s) in enumerate(disc_items[:5]):
        draw_block(ax, 3.3 + i*(disc_w+0.1), 1.4, disc_w, 0.7, '#6c3483', l, s, fontsize=7, sub_size=6)
    draw_block(ax, 8.9, 1.4, 1.2, 0.7, '#6c3483', 'Output\nBx1', 'real/\nfake', fontsize=7, sub_size=6)

    # --- Row 3: Loss ---
    loss_text = ("L_G = BCE(D(fake), 1) + 10 * L1(G(x), y)\n"
                 "L_D = 0.5 * [BCE(D(fake), 0) + BCE(D(real), 1)]")
    draw_block(ax, 3.0, 0.1, 6.0, 0.7, '#27ae60', 'Loss', loss_text, fontsize=9, sub_size=7)

    # Arrows
    draw_arrow(ax, 2.3, 4.65, 3.0, 4.4)
    draw_arrow(ax, 9.0, 4.2, 9.5, 4.65)
    draw_arrow(ax, 6.0, 3.5, 6.0, 2.8)

    # Data labels
    ax.text(6.0, 3.05, 'concatenate [normal, defect]', ha='center', fontsize=8, color='#555')
    draw_arrow(ax, 9.5, 4.2, 9.5, 2.8, lw=1.5)
    ax.text(9.8, 3.5, 'skip', fontsize=7, color='#999')

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_7_pix2pix_architecture.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_7")


# ============================================================
# Fig 3.8: Pix2Pix results
# ============================================================
def fig_3_8_pix2pix_results():
    pix2pix_output = os.path.normpath(os.path.join(BASE, "..", "pix2pix", "output"))
    fig, axes = plt.subplots(2, 5, figsize=(16, 6))
    chinese_names = ['can_body_tape', 'weld_defect', 'lid_damage', 'barcode_stain', 'oil_stain']
    display_names = ['Can Body Tape', 'Weld Defect', 'Lid Damage', 'Barcode Stain', 'Oil Stain']

    for i in range(5):
        for j in range(2):
            ax = axes[j, i]; ax.axis('off')
            p = os.path.join(pix2pix_output, f"{chinese_names[i]}_{j+1}.png")
            if os.path.exists(p):
                img = imread_unicode(p)
                if img: ax.imshow(img)
            ax.set_title(f'{display_names[i]}\nsample {j+1}', fontsize=8, linespacing=1.2)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_8_pix2pix_results.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_8")


# ============================================================
# Fig 3.9: DefectFill architecture (SIMPLIFIED)
# ============================================================
def fig_3_9_defectfill_architecture():
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_xlim(0, 12); ax.set_ylim(0, 6); ax.axis('off')

    # --- Row 1: Base SD components ---
    draw_block(ax, 0.5, 4.5, 2.5, 1.0, '#3498db', 'Text Encoder + LoRA', '', fontsize=10)
    draw_block(ax, 3.5, 4.5, 3.0, 1.0, '#c0392b', 'UNet + LoRA', 'Inpainting, 9-ch', fontsize=10, sub_size=7)
    draw_block(ax, 7.0, 4.5, 2.5, 1.0, '#9b59b6', 'VAE', 'Frozen', fontsize=10)

    # Arrow from TE and VAE to UNet
    draw_arrow(ax, 1.75, 4.5, 3.5, 4.5, lw=1)
    draw_arrow(ax, 8.25, 4.5, 6.5, 4.5, lw=1)

    # --- Row 2: AttentionStoreProcessor ---
    draw_block(ax, 2.0, 3.0, 6.0, 1.2, '#f39c12',
               'AttentionStoreProcessor (Custom Hook)', '', fontsize=10)
    attn_detail = ("Captures up_blocks cross-attention:\n"
                   "Q=to_q(hidden) K=to_k(text)\n"
                   "-> store attention maps -> compute L_attn")
    ax.text(5.0, 3.1, attn_detail, ha='center', va='center', fontsize=8, color='#2c3e50')

    draw_arrow(ax, 5.0, 4.5, 5.0, 4.2)

    # --- Row 3: Three losses ---
    draw_block(ax, 0.5, 0.5, 3.5, 1.5, '#27ae60', 'L_def (lambda=0.5)', 'mask * (eps_pred-eps)^2\nweighted by defect mask',
               fontsize=9, sub_size=7)
    draw_block(ax, 4.3, 0.5, 3.5, 1.5, '#27ae60', 'L_obj (lambda=0.2)', 'random mask completion\nobject integrity loss',
               fontsize=9, sub_size=7)
    draw_block(ax, 8.1, 0.5, 3.5, 1.5, '#27ae60', 'L_attn (lambda=0.05)', 'MSE(avg attn map, mask)\nattention alignment',
               fontsize=9, sub_size=7)

    # Total loss
    ax.text(6.0, 0.15, 'L_total = 0.5*L_def + 0.2*L_obj + 0.05*L_attn',
            ha='center', fontsize=10, fontweight='bold', color='#27ae60',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='#e8f8f5', edgecolor='#27ae60'))

    draw_arrow(ax, 5.0, 3.0, 5.0, 2.0)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_9_defectfill_architecture.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_9")


# ============================================================
# Fig 3.10: DefectFill results
# ============================================================
def fig_3_10_defectfill_results():
    candidates = [
        os.path.join(BASE, "defectfill_output", "variations_v2", "images"),
        os.path.join(BASE, "defectfill_output", "variations_v2", "img2img", "images"),
        os.path.join(BASE, "defectfill_output", "variations_std", "images"),
    ]
    fig, axes = plt.subplots(2, 5, figsize=(14, 5.5))
    for ax in axes.flat: ax.axis('off')
    img_idx = 0
    for st in ['type0', 'type1', 'type8', 'type9', 'typea', 'typeb']:
        for cd in candidates:
            p = os.path.join(cd, f"{st}_00.png")
            if os.path.exists(p):
                img = imread_unicode(p)
                if img and img_idx < 10:
                    r, c = img_idx // 5, img_idx % 5
                    axes[r, c].imshow(img)
                    axes[r, c].set_title(st, fontsize=10)
                    axes[r, c].axis('off')
                    img_idx += 1
                break
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig3_10_defectfill_results.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig3_10")


# ============================================================
# Fig 4.1: Model comparison
# ============================================================
def fig_4_1_model_comparison():
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    models = ['SD+LoRA', 'DefectFill', 'Pix2Pix']
    colors = ['#e74c3c', '#2ecc71', '#f39c12']

    datasets = [
        ('分辨率', [512, 512, 256]),
        ('多样性', [5, 3, 2]),
        ('真实感', [4, 3, 3]),
        ('可控性', [3, 1, 5]),
        ('推理速度', [5, 8, 0.5]),
        ('复现难度', [2, 7, 3]),
    ]

    for ax, (name, vals) in zip(axes.flat, datasets):
        bars = ax.bar(models, vals, color=colors, edgecolor='white', linewidth=1.5, width=0.5)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{val}', ha='center', va='bottom', fontsize=9, fontweight='bold')
        ax.set_title(name, fontsize=10, fontweight='bold')
        ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.tick_params(axis='x', rotation=20)

    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig4_1_model_comparison.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig4_1")


# ============================================================
# Fig 4.2: mAP50 comparison
# ============================================================
def fig_4_2_map50_comparison():
    models = ['SD+LoRA', 'Pix2Pix', 'DefectFill']
    map50 = [0.78, 0.85, 0.74]
    map50_95 = [0.52, 0.58, 0.48]
    colors = ['#e74c3c', '#f39c12', '#2ecc71']

    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(models)); w = 0.35

    ax.bar(x - w/2, map50, w, label='mAP@50', color=colors, edgecolor='white', linewidth=1.5)
    ax.bar(x + w/2, map50_95, w, label='mAP@50:95',
           color=[c+'99' for c in ['#e74c3c', '#c0392b', '#f39c12', '#2ecc71', '#3498db']],
           edgecolor='white', linewidth=1.5)

    for i, v in enumerate(map50):
        ax.text(i - w/2, v + 0.01, f'{v:.2f}', ha='center', va='bottom', fontsize=8, fontweight='bold')
    for i, v in enumerate(map50_95):
        ax.text(i + w/2, v + 0.01, f'{v:.2f}', ha='center', va='bottom', fontsize=7, color='#555')

    ax.set_ylabel('mAP', fontsize=11)
    ax.set_xticks(x); ax.set_xticklabels(models, fontsize=8)
    ax.legend(fontsize=9)
    ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)
    ax.set_ylim(0, 1.0); ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, 'fig4_2_map50_comparison.png'), bbox_inches='tight', dpi=150)
    plt.close()
    print("  [OK] fig4_2")


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 50)
    print(f"Generating 15 figures -> {OUTPUT_DIR}/")
    print("=" * 50)

    print("\n[Dataset]")
    fig_2_1_foreground_crop()
    fig_2_2_defect_count_bar()
    fig_2_3_defect_samples()

    print("\n[Architecture & Results]")
    fig_3_1_sd_lora_architecture()
    fig_3_2_latent_speed_comparison()
    fig_3_3_loss_curve()
    fig_3_4_txt2img_type_a()
    fig_3_5_txt2img_type_b()
    fig_3_6_img2img_variation()
    fig_3_7_pix2pix_architecture()
    fig_3_8_pix2pix_results()
    fig_3_9_defectfill_architecture()
    fig_3_10_defectfill_results()

    print("\n[Comparison]")
    fig_4_1_model_comparison()
    fig_4_2_map50_comparison()

    print("\n" + "=" * 50)
    print("Completed! 15 figures saved.")
    print("=" * 50)
