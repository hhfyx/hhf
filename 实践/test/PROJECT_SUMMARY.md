# 缺陷图像生成项目总结

---

## 一、项目概述

基于 **Stable Diffusion Inpainting + LoRA（DreamBooth）** 微调，学习工业缺陷数据集的多种缺陷样式，生成具有相似特征的新缺陷图像，用于数据增强和缺陷检测任务。

### 核心目标

| 目标 | 说明 |
|------|------|
| **缺陷生成** | 根据已有的缺陷图（裂纹、划痕、破洞、胶布等），生成类似但不同的新缺陷 |
| **多类型支持** | 支持 6 种缺陷类型，每种可独立推演 |
| **数据增强** | 为下游缺陷检测/分类模型扩充训练数据 |

---

## 二、数据集

### 2.1 数据来源

项目涉及两个原始数据集，经过处理合并为统一的训练集：

| 数据源 | 路径 | 原始内容 | 用途 |
|--------|------|---------|------|
| **缺陷切片** | `defect_patches_512_full/` | 1806 张产品表面缺陷图（512×512） | 核心训练数据 |
| **前景裁剪** | `data/` + `data_foreground/` | 420 张原始图 → 前景裁剪后 1517 张 | 补充训练数据 |

### 2.2 数据预处理

**Step 1: 前景分割（`data/` → `data_foreground/`）**

- 从 `data/` 的 YOLO 标注（class_id cx cy w h）中提取目标 bbox
- 裁剪出每个前景目标，加 5% padding，等比缩放到最大边 512
- 按 class_id 分目录存储：`class_1/`（标签破洞，876张）、`class_4/`（颜色胶布，641张）
- 过滤掉无标签（23张）和过小目标（3张）
- 脚本：`foreground_crop.py`

**Step 2: 数据合并（→ `defect_merged/`）**

- 将 `defect_patches_512_full/` 与 `data_foreground/` 合并
- 文件名统一为 `{base}_{defect_type}__box{id}.png` 格式（兼容训练脚本解析）
- class_1 映射为缺陷类型 `a`，class_4 映射为 `b`，避免与已有类型 1 冲突
- 脚本：`merge_datasets.py`

### 2.3 最终训练数据集（`defect_merged/`）

| 目录 | 数量 | 缺陷类型 | 类型含义 |
|------|------|---------|---------|
| `00_class_0` | 1687 | 0/1/8/9 | 产品表面缺陷（胶囊等） |
| `02_class_2` | 111 | 0/1/8/9 | 产品表面缺陷 |
| `05_class_5` | 8 | 0/1 | 产品表面缺陷（少量） |
| `fg_class_1` | 876 | **a** | 标签破洞缺陷 |
| `fg_class_4` | 641 | **b** | 颜色胶布缺陷 |
| **合计** | **3323** | **6 种** | |

### 2.4 缺陷类型分布总览

```
type 9: 796 张 (23.9%)  ████████████
type a: 876 张 (26.4%)  █████████████
type b: 641 张 (19.3%)  ██████████
type 1: 329 张 ( 9.9%)  █████
type 8: 303 张 ( 9.1%)  █████
type 0: 219 张 ( 6.6%)  ███
其他:   159 张 ( 4.8%)  ██
```

### 2.5 按产品类别 × 缺陷类型交叉分布（原始切片）

| 产品类别 | type 0 | type 1 | type 8 | type 9 | type a | type b | 合计 |
|---------|--------|--------|--------|--------|--------|--------|------|
| 00_class_0 | 145 | 286 | 302 | 795 | — | — | 1528 |
| 02_class_2 | 71 | 38 | 1 | 1 | — | — | 111 |
| 05_class_5 | 3 | 5 | 0 | 0 | — | — | 8 |
| fg_class_1 | — | — | — | — | 876 | — | 876 |
| fg_class_4 | — | — | — | — | — | 641 | 641 |

---

## 三、技术方案

### 3.1 模型架构

```
┌──────────────────────────────────────────────┐
│          Stable Diffusion Inpainting          │
│  ┌─────────┐  ┌──────────────────────────┐   │
│  │Text     │  │  UNet (Inpainting, 9ch)  │   │
│  │Encoder  │  │  + LoRA adapters         │   │
│  │+ LoRA   │  │                          │   │
│  └─────────┘  └──────────────────────────┘   │
│  ┌─────────┐  ┌──────────────────────────┐   │
│  │ VAE     │  │  Scheduler (DDIM)        │   │
│  │(frozen) │  │                          │   │
│  └─────────┘  └──────────────────────────┘   │
└──────────────────────────────────────────────┘
```

- **基座模型**: `runwayml/stable-diffusion-inpainting`（本地缓存）
- **微调方式**: LoRA (Low-Rank Adaptation)，rank=8
  - UNet Attention 层: `to_k`, `to_q`, `to_v`, `to_out.0`
  - Text Encoder 层: `k_proj`, `v_proj`, `q_proj`, `out_proj`
- **可训练参数**: **2,184,192**（约 218 万），占模型总参数 < 1%
- **冻结参数**: VAE、非注意力层、Scheduler
- **占位词**: `<defect>` 新增到 tokenizer 词表

### 3.2 训练策略（DreamBooth 风格）

```
训练流程:
  1. 原始缺陷图 → VAE 编码 → latent（预计算缓存）
  2. latent + 随机噪声 → 含噪 latent
  3. UNet 输入: [noisy_latent, zero_mask, zero_masked]  (9通道)
  4. Text Encoder 输入: "A photo of <defect>"
  5. UNet 输出: 噪声预测
  6. Loss: MSE(预测噪声, 真实噪声)
```

- **范式**: 标准扩散训练，非 inpainting 任务
- **mask 处理**: 复用 Inpainting UNet，mask 和 masked_image 通道填零
- **Latent 缩放**: 使用 VAE 的 `scaling_factor`（约 0.18215）

### 3.3 核心原理：训练 vs 推理

> **不是在原图基础上增加噪声再进行处理，生成是从纯随机噪声开始的，没有任何原图参与。**

#### 推理过程 (纯噪声 → 图像)

```
Step 0: z_T = 纯高斯随机噪声（完全随机，不是任何图像）

Step 1: UNet 预测"这一步应该去掉多少噪声" → 减去一部分

Step 2~24: 重复 23 次，逐步去噪

Step 25: z_0 = 干净的潜在表示 → VAE Decoder → 512×512 RGB 图像
```

```
纯噪声  ░▒▓█▓▒░  ──→  每步去噪  ──→  缺陷纹理图
```

#### 对比: 训练 vs 推理

| | 训练 | 推理 |
|--------|------|------|
| **输入** | 真实图片 | 纯随机噪声 |
| **过程** | 给真实图片加噪声 → 让 UNet 学会预测噪声 | UNet 从噪声中逐步减去预测的噪声 |
| **有原图吗** | ✅ 有（训练数据） | ❌ 没有，从零生成 |
| **数学** | 前向扩散 q(xt\|x0) | 逆向去噪 p(xt-1\|xt) |

#### 为什么能生成"像训练数据"的图

训练时 LoRA 让 UNet 学会了：给定 prompt `"color tape blemish with <defect>"`，在去噪的每一步应该预测什么样的噪声方向，才能让最终图像落在"缺陷纹理"的分布上。推理时 UNet 用这个学到的方向引导纯噪声逐步收敛到训练数据的纹理分布。

### 3.4 关键优化

| 优化项 | 效果 | 说明 |
|--------|------|------|
| **Latent 预计算** | 39s/step → 0.3s/step | 所有图片一次性 VAE 编码缓存，训练时直接加载 |
| **LoRA 参数冻结** | 仅 2.1M 参数可训 | 降低 99%+ 显存占用，减少过拟合 |
| **Gradient Checkpointing** | 节省 ~40% 显存 | 训练 UNet 时启用 |
| **梯度裁剪** | max_norm=1.0 | 防止单步异常梯度破坏训练 |
| **每 epoch 存 checkpoint** | 支持断点续训和选最优 | 可 `--resume_from` 恢复 |

### 3.4 推理策略（双模式）

#### 模式一：txt2img（从噪声生成全新缺陷）

```
推理流程:
  1. 随机噪声 latent (纯随机)
  2. CFG 引导去噪 (guidance_scale=7.5)
  3. Prompt: "A photo of a {object} with <defect>"
  4. VAE 解码 → 全新缺陷图
```

- 无需参考图，从**零**生成全新缺陷
- 缺陷位置、形态、纹理完全随机
- 适合数据增强（扩充训练集）

#### 模式二：img2img（基于参考图变异）

```
推理流程:
  1. 参考缺陷图 → VAE 编码 → init_latent
  2. 按 strength 比例添加噪声
  3. CFG 引导去噪 (guidance_scale=7.5)
  4. Prompt: "A photo of a {object} with <defect>"
  5. VAE 解码 → 变异缺陷图
```

- 保留参考图的结构骨架，细节纹理重新生成
- **strength=0.85**: 变异程度（越大越不像原图，推荐 0.8~0.95）
- 适合生成"类似但不相同"的缺陷变体

| 参数 | txt2img | img2img |
|------|---------|---------|
| 输入 | 纯随机噪声 | 参考缺陷图 |
| strength | 不适用 | **0.85**（默认） |
| guidance_scale | 7.5 | 7.5 |
| steps | 50 | 50 |
| 创新度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 可控度 | ⭐⭐ | ⭐⭐⭐⭐ |

---

## 四、训练对比（V1 vs V2）

| 指标 | V1（旧版） | V2（新版） |
|------|-----------|-----------|
| **数据集** | `defect_patches_512_full` | `defect_merged` |
| **数据量** | 1806 张 | **3323 张**（+84%） |
| **缺陷类型** | 4 种 (0/1/8/9) | **6 种** (+a/b) |
| **Epoch 数** | 2（中断） | **6+**（建议 20） |
| **Epoch 1 loss** | 0.158151 | **0.138748** ↓12% |
| **训练速度** | ~2s/step | **~0.31s/step**（3.23 it/s） |
| **每 epoch 耗时** | ~1 小时 | **~17 分钟** |
| **Checkpoint** | `defect_generator_checkpoints/` | `defect_generator_checkpoints_v2/` |
| **推理模式** | img2img only | **txt2img + img2img 双模式** |
| **img2img strength** | 0.75 | **0.85**（更大变异） |
| **输出目录** | `defectfill_output/variations_per_type/` | `defectfill_output/variations_v2/` |

---

## 五、使用方法

### 5.1 环境要求

- **Python**: `D:\conda_envs\defectfill2\`
- **GPU**: CUDA（NVIDIA GPU）
- **主要依赖**: `diffusers`, `transformers`, `peft`, `torch`, `opencv-python`, `pillow`, `numpy`, `tqdm`

### 5.2 训练

```powershell
# 标准训练（30 epoch）
D:\conda_envs\defectfill2\python.exe train_defect_generator.py `
    --dataset_root defect_merged `
    --output_dir defect_generator_checkpoints_v2 `
    --epochs 30 --lr 1e-4

# 断点续训
D:\conda_envs\defectfill2\python.exe train_defect_generator.py `
    --dataset_root defect_merged `
    --output_dir defect_generator_checkpoints_v2 `
    --epochs 30 --lr 1e-4 `
    --resume_from defect_generator_checkpoints_v2\checkpoint_epoch_6
```

### 5.3 推理（双模式）

```powershell
# 两种模式都跑（每种类型各 5 张，共 60 张）
D:\conda_envs\defectfill2\python.exe generate_per_type.py `
    --mode both --per_type 5 --steps 50 --strength 0.85

# 只要 txt2img（全新缺陷）
D:\conda_envs\defectfill2\python.exe generate_per_type.py `
    --mode txt2img --per_type 5 --steps 50

# 只要 img2img（参考图变异）
D:\conda_envs\defectfill2\python.exe generate_per_type.py `
    --mode img2img --per_type 5 --steps 50 --strength 0.9

# 自定义参数
D:\conda_envs\defectfill2\python.exe generate_per_type.py `
    --dataset_root defect_merged `
    --checkpoint_dir defect_generator_checkpoints_v2\checkpoint_epoch_6 `
    --output_dir output\custom `
    --mode both --per_type 10 --steps 50 --strength 0.85 --guidance 8
```

**输出结构：**
```
defectfill_output/variations_v2/
  txt2img/images/    ← 纯噪声生成（6类型 × N张）
  txt2img/labels/    ← 对应标签
  img2img/images/    ← 参考图变异（6类型 × N张）
  img2img/labels/
```

### 5.4 前景分割

```powershell
# 从原始大图裁剪前景目标
D:\conda_envs\defectfill2\python.exe foreground_crop.py `
    --data_dir data --output_dir data_foreground `
    --padding 0.05 --max_size 512 --min_size 20
```

---

## 六、项目文件结构

```
d:\git\实践\test\
├── 📂 defect_merged/                          ← 【训练数据集】3323 张，6 种类型
│   ├── 00_class_0/    (1687)
│   ├── 02_class_2/    (111)
│   ├── 05_class_5/    (8)
│   ├── fg_class_1/    (876)  type a - 标签破洞
│   └── fg_class_4/    (641)  type b - 颜色胶布
│
├── 📂 defect_generator_checkpoints_v2/        ← 【V2 训练权重】
│   ├── checkpoint_epoch_1~6/
│   │   ├── unet/adapter_model.safetensors     (UNet LoRA)
│   │   ├── text_encoder/adapter_model.safetensors (TE LoRA)
│   │   └── training_state.pt                  (optimizer/epoch)
│   └── latents_cache.pt                       (预计算 latent)
│
├── 📂 defect_generator_checkpoints/           ← 【V1 训练权重】（旧版）
│   ├── checkpoint_epoch_1~2/
│   └── latents_cache.pt
│
├── 📂 defectfill_output/                      ← 【生成结果】
│   ├── variations/            (随机采样 10 张)
│   ├── variations_per_type/   (按类型 20 张, V1)
│   └── variations_v2/         (按类型双模式, V2)
│       ├── txt2img/           (纯噪声生成)
│       └── img2img/           (参考图变异)
│
├── 📂 data/                                    ← 原始大图 + YOLO 标签
├── 📂 data_foreground/                         ← 前景裁剪结果
│   ├── class_1/    (876)
│   └── class_4/    (641)
│
├── 📂 defect_patches_512_full/                ← 原始缺陷切片
├── defect_patches_512_full.zip                ← 数据集压缩包
│
├── 🐍 train_defect_generator.py               ← 训练脚本
├── 🐍 generate_per_type.py                    ← 按类型推理脚本
├── 🐍 generate_variations.py                  ← 随机推理脚本
├── 🐍 foreground_crop.py                      ← 前景分割脚本
├── 📋 PROJECT_SUMMARY.md                      ← 本文档
├── 📄 train_gen_20260515_222213.log           ← 训练日志 (V1)
└── 📄 train_gen_20260515_222431.log           ← 训练日志 (V1 未优化版)
```

---

## 七、训练参数详解

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset_root` | `defect_merged` | 训练数据目录 |
| `--output_dir` | `defect_generator_checkpoints_v2` | 输出目录 |
| `--model_id` | Inpainting 本地缓存 | 基座模型路径 |
| `--epochs` | 30 | 训练轮数 |
| `--lr` | 1e-4 | 学习率 |
| `--lora_rank` | 8 | LoRA 秩（越大参数越多） |
| `--device` | cuda | 训练设备 |
| `--resume_from` | None | 断点续训路径 |

---

## 八、推理参数详解

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dataset_root` | `defect_merged` | 参考数据集（img2img 用作参考来源） |
| `--checkpoint_dir` | `.../checkpoint_epoch_6` | 模型权重路径 |
| `--output_dir` | `defectfill_output/variations_v2` | 输出路径 |
| `--mode` | `both` | 生成模式：`txt2img` / `img2img` / `both` |
| `--per_type` | 5 | 每种类型生成数量 |
| `--steps` | 50 | 推理步数（越大越精细但越慢） |
| `--strength` | 0.85 | img2img 噪声强度（0=不变，1=完全随机，推荐 0.8~0.95） |
| `--guidance` | 7.5 | CFG 引导强度（越大越遵循 prompt，推荐 5~12） |

### 模式选择指南

| 场景 | 推荐模式 | 参数 |
|------|---------|------|
| 扩充训练集（产生多样性） | `txt2img` | `--mode txt2img --guidance 8` |
| 生成缺陷变体（保留参考特征） | `img2img` | `--mode img2img --strength 0.85` |
| 对比两种效果 | `both` | 默认参数即可 |

---

## 九、训练日志摘要

### V2 训练（3323 张，latent 预计算）

| Epoch | Global Step | 速度 | 备注 |
|-------|-------------|------|------|
| 1 | 3,323 | 3.23 it/s | avg loss 0.138748 |
| 2 | 6,646 | 3.23 it/s | — |
| 3 | 9,969 | — | — |
| 4 | 13,292 | — | — |
| 5 | 16,615 | — | — |
| 6 | 19,938 | — | ✅ 当前推理用 |

> 💡 **建议续训**: `--epochs 20 --resume_from checkpoint_epoch_6`

### V1 训练（1806 张，旧版）

| Epoch | Avg Loss | 速度 |
|-------|----------|------|
| 1 | 0.158151 | ~2s/step |
| 2 | 0.156930 | ~3s/step |

---

## 十、后续改进方向

| 方向 | 说明 |
|------|------|
| **续训到 20 epoch** | 当前仅 6 epoch，模型远未收敛，训到 15-20 效果明显提升 |
| **减小学习率** | loss 稳定后可用 `--lr 5e-5` 精调 |
| **txt2img 效果验证** | 当前训练基于 Inpainting UNet，txt2img 效果可能受限 |
| **迁移到标准 Pipeline** | 如 txt2img 效果差，可迁移 LoRA 到 `StableDiffusionPipeline`（4ch UNet） |
| **数据均衡** | type a/b 较多，可考虑按类型采样均衡 |
| **缺陷类型命名** | type 0/1/8/9 可结合实际业务场景命名 |
| **更多数据** | 收集更多缺陷类型和产品类别的数据 |
| **多参考图融合** | img2img 用同类型多张参考图加权生成，提高多样性 |
| **CFG 调优** | 调整 guidance_scale 找到最佳生成质量 |
| **质量评估** | 引入 FID/IS 等指标量化生成质量 |

---

## 十一、已知问题

| 问题 | 状态 | 说明 |
|------|------|------|
| 中文路径兼容性 | ✅ 已修复 | 使用 `imread_unicode` / `imwrite_unicode` |
| 训练速度慢 | ✅ 已优化 | Latent 预计算加速 15-20 倍 |
| img2img 生成跟原图一样 | ⚠️ 调参中 | 改 txt2img 模式 + 提高 strength 到 0.85 |
| txt2img 质量 | ⚠️ 待验证 | Inpainting UNet 做 txt2img 天然受限 |
| 训练不足 | ⚠️ 待续训 | 仅 6 epoch，建议训到 20 |
| 类型不均衡 | ⚠️ 存在 | type 0 仅 6.6%，可考虑 oversampling |
