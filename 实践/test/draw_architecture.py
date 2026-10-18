"""
生成图2.1：SD+LoRA 网络架构图 — 修复文字重叠
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
import os

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 200
plt.rcParams['savefig.dpi'] = 200

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'report_figures')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def draw_sd_lora_architecture():
    fig, ax = plt.subplots(1, 1, figsize=(18, 14))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 14)
    ax.axis('off')

    # ========== 颜色方案 ==========
    C = {
        'vae':        '#4C72B0',
        'unet_bg':    '#E8F0FE',
        'unet_bd':    '#4C72B0',
        'te':         '#55A868',
        'lora':       '#C44E52',
        'noise':      '#8172B2',
        'output':     '#CCB974',
        'arrow':      '#555555',
        'prompt':     '#64B5CD',
    }

    def box(ax, x, y, w, h, color, label, sub=None, lw=2, alpha=0.15):
        """圆角矩形"""
        p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.1",
                           facecolor=color, edgecolor=color, linewidth=lw, alpha=alpha)
        ax.add_patch(p)
        ax.text(x + w/2, y + h/2, label, ha='center', va='center',
                fontsize=9, fontweight='bold', color='#222')
        if sub:
            ax.text(x + w/2, y + h*0.2, sub, ha='center', va='center',
                    fontsize=7, color='#666')

    def lora_tag(ax, x, y, w, h, txt, color='#C44E52'):
        """LoRA 标记（放在模块右侧外）"""
        tx, ty = x + w + 0.05, y + h/2 - 0.25
        p = FancyBboxPatch((tx, ty), 0.9, 0.5, boxstyle="round,pad=0.05",
                           facecolor=color, edgecolor='white', linewidth=1)
        ax.add_patch(p)
        ax.text(tx + 0.45, ty + 0.25, txt, ha='center', va='center',
                fontsize=7, fontweight='bold', color='white')

    # ================================================================
    # 左侧: Text Encoder
    # ================================================================
    te_x, te_y, te_w, te_h = 0.8, 6.5, 3.5, 4.5
    box(ax, te_x, te_y, te_w, te_h, C['te'], "Text Encoder\n(CLIP ViT-L/14)", lw=2, alpha=0.12)
    ax.text(te_x+te_w/2, te_y+te_h-0.35, "参数量: 123M", ha='center', fontsize=8, color=C['te'])

    # TE 内部子模块
    for i, (label, sub) in enumerate([
        ("Token Embedding\n49408 → 49409", None),
        ("12× Transformer\n(因果注意力)", None),
        ("输出: [77, 768]", None),
    ]):
        cy = te_y + 3.0 - i * 1.2
        box(ax, te_x+0.3, cy, te_w-0.6, 0.8, C['te'], label, lw=1, alpha=0.2)

    # LoRA tag（TE 右侧外部）
    lora_tag(ax, te_x, te_y, te_w, te_h, "LoRA")
    ax.text(te_x+te_w+0.5, te_y+0.8, "k_proj /\nv_proj /\nq_proj /\nout_proj",
            ha='center', fontsize=6, color=C['lora'])

    # TE 上方 prompt
    ax.text(te_x+te_w/2, te_y+te_h+0.6, '"A photo of <defect>"',
            ha='center', fontsize=9, color=C['prompt'], fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor=C['prompt'], alpha=0.8))

    # ================================================================
    # 中间: UNet（核心）
    # ================================================================
    unet_x, unet_y, unet_w, unet_h = 6.0, 1.2, 6.0, 10.5
    box(ax, unet_x, unet_y, unet_w, unet_h, C['unet_bg'],
        "UNet (Inpainting, 9ch)", "参数量: 860M | 可训练: 2.18M (LoRA)", lw=2, alpha=0.3)

    # Input Conv
    box(ax, unet_x+0.4, unet_y+9.2, unet_w-0.8, 0.6,
        C['unet_bd'], "Input Conv (9→320)", lw=1, alpha=0.1)

    # DownBlock ×3（带右侧 LoRA 标签）
    dl = [
        ("DownBlock 0\n320→320", "ResBlock + Attn"),
        ("DownBlock 1\n320→640", "ResBlock + Attn"),
        ("DownBlock 2\n640→1280", "ResBlock + Attn"),
    ]
    for i, (title, sub) in enumerate(dl):
        dy = unet_y + 6.8 - i * 1.3
        box(ax, unet_x+0.4, dy, unet_w-0.8, 0.8, C['unet_bd'], title, lw=1, alpha=0.08)
        ax.text(unet_x+unet_w/2, dy+0.15, sub, ha='center', va='center',
                fontsize=6.5, color='#888')
        lora_tag(ax, unet_x+0.4, dy, unet_w-0.8, 0.8, "+LoRA")

    # MiddleBlock
    box(ax, unet_x+0.4, unet_y+3.2, unet_w-0.8, 0.8,
        C['unet_bd'], "MiddleBlock\n1280→1280", lw=1.5, alpha=0.15)
    ax.text(unet_x+unet_w/2, unet_y+3.45, "ResBlock + Attn",
            ha='center', va='center', fontsize=6.5, color='#888')
    lora_tag(ax, unet_x+0.4, unet_y+3.2, unet_w-0.8, 0.8, "+LoRA")

    # UpBlock ×3
    ul = [
        ("UpBlock 2\n1280→640", "ResBlock + Attn"),
        ("UpBlock 1\n640→320", "ResBlock + Attn"),
        ("UpBlock 0\n320→320", "ResBlock + Attn"),
    ]
    for i, (title, sub) in enumerate(ul):
        uy = unet_y + 2.2 - i * 1.3
        box(ax, unet_x+0.4, uy, unet_w-0.8, 0.8, C['unet_bd'], title, lw=1, alpha=0.08)
        ax.text(unet_x+unet_w/2, uy+0.15, sub, ha='center', va='center',
                fontsize=6.5, color='#888')
        lora_tag(ax, unet_x+0.4, uy, unet_w-0.8, 0.8, "+LoRA")

    # Output Conv
    box(ax, unet_x+0.4, unet_y+0.0, unet_w-0.8, 0.6,
        C['unet_bd'], "Output Conv (320→4)", lw=1, alpha=0.1)

    # ================================================================
    # 右侧: VAE
    # ================================================================
    vae_x, vae_y, vae_w, vae_h = 14.0, 5.5, 2.2, 4.0
    box(ax, vae_x, vae_y, vae_w, vae_h, C['vae'], "VAE (冻结)", lw=2, alpha=0.12)
    ax.text(vae_x+vae_w/2, vae_y+vae_h-0.3, "84M", ha='center', fontsize=8, color=C['vae'])
    box(ax, vae_x+0.2, vae_y+2.5, vae_w-0.4, 0.8, C['vae'],
        "Encoder\n512→64×4", lw=1, alpha=0.15)
    box(ax, vae_x+0.2, vae_y+1.2, vae_w-0.4, 0.8, C['vae'],
        "Decoder\n64×4→512", lw=1, alpha=0.15)
    ax.text(vae_x+vae_w/2, vae_y+0.3, "scale=0.182", ha='center', fontsize=7, color=C['vae'])

    # ================================================================
    # 输入 / 输出
    # ================================================================
    # 输入（在 UNet 上方）
    box(ax, unet_x+0.3, unet_y+unet_h+0.2, unet_w-0.6, 0.55, C['noise'],
        "随机噪声 [1,4,64,64]", lw=1.5, alpha=0.15)
    # 零 mask 输入在噪声右侧
    box(ax, unet_x+unet_w+0.3, unet_y+unet_h+0.2, 2.5, 0.55, '#DDDDDD',
        "零 mask [1,1,64] + 零 masked [1,4,64]", lw=1, alpha=0.5)

    # UNet 输出 → VAE Decoder 箭头标注
    ax.text(unet_x+unet_w/2, unet_y-0.4, "预测噪声 [1,4,64,64]",
            ha='center', fontsize=8, color=C['output'], fontweight='bold')

    # ================================================================
    # 箭头
    # ================================================================
    # TE → UNet (Cross-Attention 箭头)
    ax.annotate('', xy=(unet_x, te_y+2.5), xytext=(te_x+te_w, te_y+2.5),
                arrowprops=dict(arrowstyle='->', color=C['te'], lw=2, connectionstyle='arc3,rad=0.3'))
    # Cross-Attention 标签放在 TE 和 UNet 之间、偏上位置
    ax.text((te_x+te_w+unet_x)/2, te_y+3.8, "Cross-Attention\nK / V",
            ha='center', fontsize=8, color=C['te'], fontweight='bold')

    # 噪声输入箭头（水平 → UNet 顶部）
    ax.annotate('', xy=(unet_x, unet_y+unet_h+0.5), xytext=(unet_x-2, unet_y+unet_h+0.5),
                arrowprops=dict(arrowstyle='->', color=C['noise'], lw=1.5))
    # 零 mask 输入箭头
    ax.annotate('', xy=(unet_x+unet_w, unet_y+unet_h+0.5), xytext=(unet_x+unet_w+2.3, unet_y+unet_h+0.5),
                arrowprops=dict(arrowstyle='->', color='#888888', lw=1.5))

    # UNet 输出箭头（向下）
    ax.annotate('', xy=(unet_x+unet_w/2, unet_y+0.6), xytext=(unet_x+unet_w/2, unet_y-0.5),
                arrowprops=dict(arrowstyle='->', color=C['output'], lw=2))

    # UNet → VAE Decoder（虚线连接）
    ax.annotate('', xy=(vae_x, vae_y+1.6), xytext=(unet_x+unet_w, unet_y+0.3),
                arrowprops=dict(arrowstyle='->', color=C['vae'], lw=1.5,
                                connectionstyle='arc3,rad=-0.3'))
    ax.text(unet_x+unet_w+1.5, unet_y-0.2, "→ VAE Decode → 512×512 缺陷图",
            ha='center', fontsize=8, color=C['vae'], fontweight='bold')

    # 训练说明（右侧空白区域）
    note_x, note_y = 14.6, 10.0
    ax.text(note_x, note_y,
            "训练流程:\n"
            "1. 图片→VAE→latent (预计算缓存)\n"
            "2. latent + 噪声 → noisy_latent\n"
            "3. UNet 预测噪声\n"
            "4. MSE(预测, 真实) → 更新 LoRA",
            fontsize=7, color=C['arrow'], va='top',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white',
                      edgecolor=C['arrow'], alpha=0.8))

    # 推理说明
    ax.text(note_x, note_y-3.2,
            "推理流程:\n"
            "1. 纯随机噪声\n"
            "2. UNet 逐歩去噪 (50步)\n"
            "3. VAE Decode → 缺陷图",
            fontsize=7, color=C['noise'], va='top',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white',
                      edgecolor=C['noise'], alpha=0.8))

    # ================================================================
    # 图号
    # ================================================================
    ax.text(9, 13.8, '图 2.1  SD+LoRA 网络架构图',
            ha='center', fontsize=16, fontweight='bold')

    # ================================================================
    # 图例
    # ================================================================
    legend_elements = [
        mpatches.Patch(facecolor=C['te'], alpha=0.3, label='Text Encoder (LoRA)'),
        mpatches.Patch(facecolor=C['unet_bd'], alpha=0.3, label='UNet (LoRA)'),
        mpatches.Patch(facecolor=C['vae'], alpha=0.3, label='VAE (冻结)'),
        mpatches.Patch(facecolor=C['lora'], alpha=0.5, label='LoRA (rank=8)'),
        mpatches.Patch(facecolor=C['noise'], alpha=0.3, label='噪声/latent 流'),
    ]
    ax.legend(handles=legend_elements, loc='lower center', fontsize=8,
              ncol=5, bbox_to_anchor=(0.5, -0.02), framealpha=0.9)

    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, 'fig2_1_sd_lora_architecture.png')
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


if __name__ == '__main__':
    draw_sd_lora_architecture()
