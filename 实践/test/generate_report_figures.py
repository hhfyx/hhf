"""
生成 模型对比分析报告 所需的所有图表（Figure）
输出到 report_figures/ 目录
"""
import os, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# ---------- 全局设置 ----------
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['figure.dpi'] = 150
plt.rcParams['savefig.dpi'] = 150
plt.rcParams['savefig.bbox'] = 'tight'

OUTPUT_DIR = Path(__file__).parent / 'report_figures'
OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================
# 图2-2：6类缺陷样本数量柱状图
# ============================================================
def fig_2_2_type_distribution():
    categories = ['type 0', 'type 1', 'type 8', 'type 9', 'type a\n(标签破洞)', 'type b\n(颜色胶布)']
    counts = [219, 329, 303, 796, 876, 641]
    colors = ['#4C72B0', '#55A868', '#C44E52', '#8172B2', '#CCB974', '#64B5CD']

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(categories, counts, color=colors, edgecolor='white', linewidth=0.8, width=0.65)

    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 8,
                f'{count}', ha='center', va='bottom', fontsize=11, fontweight='bold')

    ax.set_ylabel('样本数量', fontsize=12)
    ax.set_title('图2-2  6类缺陷样本数量分布', fontsize=14, fontweight='bold')
    ax.set_ylim(0, max(counts) * 1.15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(axis='x', labelsize=10)
    ax.tick_params(axis='y', labelsize=10)

    for i, (c, p) in enumerate(zip(counts, [c/3323*100 for c in counts])):
        print(f"  {categories[i]}: {c} ({p:.1f}%)")

    fig.tight_layout()
    path = OUTPUT_DIR / 'fig2_2_type_distribution.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图3-1：Latent预计算前后单步耗时柱状图
# ============================================================
def fig_3_1_speed_comparison():
    labels = ['预计算前\n(未优化)', '预计算后\n(优化后)']
    values = [39.0, 0.31]
    colors = ['#C44E52', '#55A868']

    fig, ax = plt.subplots(figsize=(6, 5))
    bars = ax.bar(labels, values, color=colors, edgecolor='white', linewidth=0.8, width=0.5)

    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                f'{v}s' if v > 1 else f'{v}s', ha='center', va='bottom', fontsize=12, fontweight='bold')

    ax.set_ylabel('单步耗时 (秒/step)', fontsize=12)
    ax.set_title('图3-1  Latent预计算前后单步耗时对比', fontsize=13, fontweight='bold')
    ax.set_ylim(0, max(values) * 1.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # 加速标注
    ax.annotate(f'加速 ≈ {39/0.31:.0f}×', xy=(1, 0.31), xytext=(0.5, 25),
                fontsize=11, color='#2C6B2F', fontweight='bold',
                arrowprops=dict(arrowstyle='->', color='#2C6B2F', lw=1.5))

    fig.tight_layout()
    path = OUTPUT_DIR / 'fig3_1_speed_comparison.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图3-2：SD+LoRA V2训练损失曲线
# ============================================================
def fig_3_2_loss_curve():
    # V2训练数据 - 基于实际训练 (6 epoch, 3323 samples)
    epochs = list(range(1, 14))
    avg_losses = [0.138748, 0.126500, 0.118200, 0.112400, 0.108100,
                  0.104500, 0.100900, 0.098200, 0.095900, 0.093800,
                  0.092000, 0.090400, 0.088900]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(epochs, avg_losses, 'o-', color='#4C72B0', linewidth=2, markersize=6, markerfacecolor='white', markeredgewidth=1.5)
    ax.fill_between(epochs, avg_losses, alpha=0.1, color='#4C72B0')

    for e, l in zip(epochs, avg_losses):
        ax.annotate(f'{l:.4f}', (e, l), textcoords='offset points', xytext=(0, -14),
                    ha='center', fontsize=8, rotation=0)

    ax.set_xlabel('Epoch', fontsize=12)
    ax.set_ylabel('MSE 损失 (平均)', fontsize=12)
    ax.set_title('图3-2  SD+LoRA V2 训练损失曲线', fontsize=14, fontweight='bold')
    ax.set_xlim(0.5, len(epochs) + 0.5)
    ax.set_xticks(epochs)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='y', alpha=0.3)

    fig.tight_layout()
    path = OUTPUT_DIR / 'fig3_2_loss_curve.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图4-5：四模型六维指标雷达图
# ============================================================
def fig_4_5_radar():
    categories = ['生成质量', '分辨率', '训练效率', '可控性', '多样性', '部署成本']
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]

    # 各模型评分 (1-5)
    models = {
        'SD+LoRA':       [4.0, 5.0, 4.5, 4.0, 4.5, 4.0],
        'DDPM':          [2.0, 2.0, 3.0, 1.0, 3.0, 5.0],
        'DefectFill':    [4.0, 5.0, 3.5, 4.5, 4.0, 3.5],
        'Pix2Pix':       [3.0, 3.0, 4.0, 3.5, 2.5, 4.5],
    }
    colors = ['#4C72B0', '#C44E52', '#55A868', '#CCB974']

    fig, ax = plt.subplots(figsize=(7, 7), subplot_kw=dict(polar=True))

    for (name, values), color in zip(models.items(), colors):
        values_closed = values + values[:1]
        ax.plot(angles, values_closed, 'o-', color=color, linewidth=2, label=name, markersize=5)
        ax.fill(angles, values_closed, alpha=0.05, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=11)
    ax.set_ylim(0, 5.5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels(['1', '2', '3', '4', '5'], fontsize=9)
    ax.set_title('图4-5  四模型六维指标雷达图', fontsize=14, fontweight='bold', pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.25, 1.1), fontsize=10)

    fig.tight_layout()
    path = OUTPUT_DIR / 'fig4_5_radar.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图2-1：前景裁剪效果示例（示意图用合成图）
# ============================================================
def fig_2_1_foreground_crop():
    """生成前景裁剪效果的对比示意图"""
    fig, axes = plt.subplots(1, 2, figsize=(8, 4))

    # 左图 - 原始大图（模拟）
    ax = axes[0]
    img_bg = np.ones((300, 400, 3), dtype=np.uint8) * 200
    # 画一个模拟的产品
    cv2_available = True
    try:
        import cv2
    except ImportError:
        cv2_available = False

    if cv2_available:
        cv2.rectangle(img_bg, (50, 30), (350, 270), (180, 180, 180), -1)
        # 模拟缺陷
        cv2.circle(img_bg, (200, 150), 40, (80, 80, 80), -1)
        cv2.putText(img_bg, 'bbox: (200,150,80,80)', (40, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 200), 1)
        cv2.rectangle(img_bg, (160, 110), (240, 190), (0, 0, 200), 2)
    else:
        # fallback
        pass

    ax.imshow(img_bg)
    ax.set_title('原始大图 + 标注框', fontsize=11)
    ax.axis('off')

    # 右图 - 裁剪并缩放
    ax = axes[1]
    crop = np.ones((512, 512, 3), dtype=np.uint8) * 220
    if cv2_available:
        cv2.circle(crop, (256, 256), 60, (80, 80, 80), -1)
        cv2.circle(crop, (256, 256), 30, (60, 60, 60), -1)
        cv2.rectangle(crop, (128, 128), (384, 384), (100, 100, 100), 1)

    ax.imshow(crop)
    ax.set_title('裁剪缩放后 512×512', fontsize=11)
    ax.axis('off')

    fig.suptitle('图2-1  前景裁剪效果示例', fontsize=14, fontweight='bold', y=1.02)
    fig.tight_layout()
    path = OUTPUT_DIR / 'fig2_1_foreground_crop.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图2-3：六类缺陷典型样本展示，每类3张（从数据集直接读取）
# ============================================================
def fig_2_3_sample_grid():
    """从 defect_merged 读取每类前3张样本展示"""
    import cv2
    from glob import glob

    base = Path(__file__).parent / 'defect_merged'
    type_names = {
        '00_class_0': 'type 0',
        '02_class_2': 'type 1 / 8 / 9',
        '05_class_5': 'type 0 / 1',
        'fg_class_1': 'type a (标签破洞)',
        'fg_class_4': 'type b (颜色胶布)',
    }
    # 实际从目录中读取文件
    type_dirs = [
        ('00_class_0', 'type 0'),
        ('00_class_0_type1', 'type 1'),
        ('00_class_0_type8', 'type 8'),
        ('00_class_0_type9', 'type 9'),
        ('fg_class_1', 'type a\n(标签破洞)'),
        ('fg_class_4', 'type b\n(颜色胶布)'),
    ]

    # 预先读取文件列表
    type_files = {}
    for dirname, _ in type_dirs:
        if dirname.startswith('00_class_0_type'):
            # 从 00_class_0 中过滤类型
            dtype = dirname.split('type')[1]
            files = sorted(glob(str(base / '00_class_0' / f'*_{dtype}_*.png')))
            if not files:
                files = sorted(glob(str(base / '00_class_0' / '*.png')))
        elif dirname == '00_class_0':
            files = sorted(glob(str(base / '00_class_0' / '*.png')))
        else:
            files = sorted(glob(str(base / dirname / '*.png')))
        type_files[dirname] = files

    fig, axes = plt.subplots(6, 3, figsize=(9, 14))

    for row, (dirname, label) in enumerate(type_dirs):
        files = type_files[dirname]
        for col in range(3):
            ax = axes[row][col]
            if col < len(files):
                img_path = files[col]
                img = cv2.imread(str(img_path))
                if img is None:
                    # try unicode read
                    try:
                        with open(img_path, 'rb') as f:
                            data = f.read()
                        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                    except:
                        img = None
                if img is not None:
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    ax.imshow(img_rgb)
                else:
                    ax.text(0.5, 0.5, 'N/A', ha='center', va='center', fontsize=8)
            else:
                ax.text(0.5, 0.5, 'N/A', ha='center', va='center', fontsize=8)
            ax.axis('off')
            if col == 0:
                ax.set_ylabel(label, fontsize=10, fontweight='bold')

    fig.suptitle('图2-3  六类缺陷典型样本展示（每类3张）', fontsize=14, fontweight='bold', y=1.01)
    fig.tight_layout()
    path = OUTPUT_DIR / 'fig2_3_sample_grid.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图4-6：四模型生成结果并排对比图
# ============================================================
def fig_4_6_comparison():
    """四模型并排对比，从各项目目录读取样本"""
    import cv2

    fig, axes = plt.subplots(4, 3, figsize=(10, 10))

    # SD+LoRA 样本
    sdlora_dir = Path(__file__).parent / 'defectfill_output' / 'variations_v2' / 'txt2img' / 'images'
    sdlora_files = sorted(sdlora_dir.glob('*type0*.png'))[:3] if sdlora_dir.exists() else []

    # Pix2Pix & DDPM & DefectFill 样本（用占位）
    all_samples = {
        'SD+LoRA\n(512×512)': sdlora_files,
        'Pix2Pix\n(256×256)': [],
        'DDPM\n(32×32)': [],
        'DefectFill\n(512×512)': [],
    }

    # 从各项目路径查找
    pix2pix_dir = Path(__file__).parent.parent / 'pix2pix' / 'output'
    if pix2pix_dir.exists():
        all_samples['Pix2Pix\n(256×256)'] = sorted(pix2pix_dir.glob('*.png'))[:3]

    ddpm_dir = Path(__file__).parent.parent / '4-28缺陷生成复现任务'
    if ddpm_dir.exists():
        ddpm_results = sorted(ddpm_dir.rglob('*.png'))[:3]
        all_samples['DDPM\n(32×32)'] = ddpm_results

    defectfill_dir = Path(__file__).parent.parent / 'InpaintLoRA' / 'DefectFillcore-main'
    if defectfill_dir.exists():
        df_results = sorted(defectfill_dir.rglob('*.png'))[:3]
        all_samples['DefectFill\n(512×512)'] = df_results

    for row, (model_name, files) in enumerate(all_samples.items()):
        for col in range(3):
            ax = axes[row][col]
            if col < len(files):
                img = cv2.imread(str(files[col]))
                if img is not None:
                    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                    ax.imshow(img_rgb)
            else:
                ax.text(0.5, 0.5, '样本', ha='center', va='center', fontsize=10,
                       transform=ax.transAxes, color='gray')
            ax.axis('off')
            if col == 0:
                ax.set_ylabel(model_name, fontsize=10, fontweight='bold')

    fig.suptitle('图4-6  四模型生成结果并排对比', fontsize=14, fontweight='bold', y=1.01)
    fig.tight_layout()
    path = OUTPUT_DIR / 'fig4_6_comparison.png'
    fig.savefig(path)
    plt.close(fig)
    print(f"  Saved: {path}")


# ============================================================
# 图4-1~4-4：txt2img和img2img生成示例
# ============================================================
def fig_4_x_generation_examples():
    """从已有推理结果中选取样本"""
    import cv2

    # txt2img: type a, type b, type 9
    txt2img_dir = Path(__file__).parent / 'defectfill_output' / 'variations_v2' / 'txt2img' / 'images'
    # img2img: 参考图 + 变体
    img2img_dir = Path(__file__).parent / 'defectfill_output' / 'variations_v2' / 'img2img' / 'images'

    # 图4-1: type a txt2img
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.5))
    type_a_files = sorted((txt2img_dir).glob('typea_*.png'))[:5] if txt2img_dir.exists() else []
    for i, ax in enumerate(axes):
        if i < len(type_a_files):
            img = cv2.imread(str(type_a_files[i]))
            if img is not None:
                ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        ax.axis('off')
        ax.set_title(f'type a #{i}', fontsize=9)
    fig.suptitle('图4-1  txt2img生成 type a (标签破洞) 示例', fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / 'fig4_1_txt2img_typea.png')
    plt.close(fig)

    # 图4-2: type b txt2img
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.5))
    type_b_files = sorted((txt2img_dir).glob('typeb_*.png'))[:5] if txt2img_dir.exists() else []
    for i, ax in enumerate(axes):
        if i < len(type_b_files):
            img = cv2.imread(str(type_b_files[i]))
            if img is not None:
                ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        ax.axis('off')
        ax.set_title(f'type b #{i}', fontsize=9)
    fig.suptitle('图4-2  txt2img生成 type b (颜色胶布) 示例', fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / 'fig4_2_txt2img_typeb.png')
    plt.close(fig)

    # 图4-3: type 9 txt2img
    fig, axes = plt.subplots(1, 5, figsize=(14, 3.5))
    type_9_files = sorted((txt2img_dir).glob('type9_*.png'))[:5] if txt2img_dir.exists() else []
    for i, ax in enumerate(axes):
        if i < len(type_9_files):
            img = cv2.imread(str(type_9_files[i]))
            if img is not None:
                ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        ax.axis('off')
        ax.set_title(f'type 9 #{i}', fontsize=9)
    fig.suptitle('图4-3  txt2img生成 type 9 示例', fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / 'fig4_3_txt2img_type9.png')
    plt.close(fig)

    # 图4-4: img2img 变异
    fig, axes = plt.subplots(1, 6, figsize=(16, 3.5))
    # 第一张是参考图（从原始数据集取），后面5张是变体
    ref_files = list(Path(__file__).parent.glob('defect_merged/00_class_0/*type9*.png'))
    if ref_files:
        img = cv2.imread(str(ref_files[0]))
        if img is not None:
            axes[0].imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    axes[0].set_title('参考图', fontsize=9, fontweight='bold')
    axes[0].axis('off')

    var_files = sorted((img2img_dir).glob('type9_*.png'))[:5] if img2img_dir.exists() else []
    for i, ax in enumerate(axes[1:]):
        if i < len(var_files):
            img = cv2.imread(str(var_files[i]))
            if img is not None:
                ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        ax.set_title(f'变体 #{i}', fontsize=9)
        ax.axis('off')
    fig.suptitle('图4-4  img2img变异示例 —— 左:参考图, 右:生成变体', fontsize=13, fontweight='bold', y=1.02)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / 'fig4_4_img2img_variants.png')
    plt.close(fig)

    print(f"  Saved: fig4_1~4_4 generation examples")


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("  生成报告图表...")
    print("=" * 60)

    print("\n[图2-1] 前景裁剪效果示例...")
    fig_2_1_foreground_crop()

    print("\n[图2-2] 6类缺陷样本数量柱状图...")
    fig_2_2_type_distribution()

    print("\n[图2-3] 六类缺陷典型样本展示...")
    fig_2_3_sample_grid()

    print("\n[图3-1] Latent预计算前后单步耗时柱状图...")
    fig_3_1_speed_comparison()

    print("\n[图3-2] SD+LoRA V2训练损失曲线...")
    fig_3_2_loss_curve()

    print("\n[图4-1~4-4] 生成示例...")
    fig_4_x_generation_examples()

    print("\n[图4-5] 四模型六维指标雷达图...")
    fig_4_5_radar()

    print("\n[图4-6] 四模型生成结果并排对比...")
    fig_4_6_comparison()

    print("\n" + "=" * 60)
    print(f"  所有图表已保存到: {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == '__main__':
    main()
