# 游戏配置管理

针对本机硬件优化：**i5-13500H / RTX 4050 Laptop 6GB / 16GB RAM / 2560×1600 @165Hz**

## 快速使用

双击或在终端执行：

```bat
switch.bat cs2        :: 切 CS2 流畅档
switch.bat delta      :: 切 三角洲 流畅档
switch.bat baseline   :: 还原原始配置
```

也支持数字：`1`=baseline，`2`=delta，`3`=cs2。

PowerShell 用户：

```powershell
.\switch.ps1 cs2
.\switch.ps1 delta
.\switch.ps1 baseline
```

## 配置档案

目录 `profiles\` 下：

| 目录 | 显示名 | 内容 |
|---|---|---|
| `baseline` | 原始基线 | CS2 + 三角洲 共 3 个文件的原始备份（**唯一权威原始版本**）|
| `cs2` | CS2-流畅 | `cs2_video.txt`（实际有改动）|
| `delta-force` | 三角洲-流畅 | `UserSystemSettingHD.ini`（实际有改动）+ `GameUserSettings.ini`（无改动，见下）|
| `_线上自动备份` | 自动备份 | 每次切换前自动留存，带时间戳 |

> 目录名用 ASCII 是为了绕开 cmd/PowerShell 的中文编码问题，脚本内部已做好映射。

## 生效文件对照

| 游戏 | 实际生效位置 | 由哪些档案管理 | 切换时会变化？ |
|---|---|---|---|
| CS2 画质 | `D:\steam\userdata\1185089847\730\local\cfg\cs2_video.txt` | baseline / cs2 | ✅ 会 |
| 三角洲 画质 | `...\WindowsClient\UserSystemSettingHD.ini` | baseline / delta-force | ✅ 会 |
| 三角洲 分辨率/全屏 | `...\WindowsClient\GameUserSettings.ini` | baseline / delta-force | ❌ **不会**（两档内容相同）|

**互不干扰**：切 CS2 只写 cs2_video.txt，切三角洲只写两个 ini。

### 关于 `GameUserSettings.ini`（空转文件）

`delta-force\GameUserSettings.ini` 与 `baseline\GameUserSettings.ini` **逐字节相同**，所以切到流畅档时它不会产生任何变化。

之所以仍然保留并由脚本覆盖，是为了**防止游戏自行改写**这个文件后（比如你手滑在游戏里改了分辨率/窗口模式）导致配置回不去——覆盖一次等于把分辨率和全屏模式强制拉回原始状态。属于"无变化但有防护"的备份项。

如果你确认不需要这层保护，可以从 `delta-force` 里删掉它，脚本会自动跳过（`Apply-File` 会打印"该配置不含此文件，跳过"）。

## 安全机制

1. **进程守卫**：检测到 `cs2.exe` 或 `DeltaForceClient-Win64-Shipping.exe` 在运行，直接拒绝执行并退出。
   - 原因：游戏退出时会把内存中的旧设置写回文件，覆盖你的修改。
   - 确认进程残留可用 `-Force` 跳过：`.\switch.ps1 cs2 -Force`
2. **切换前自动备份**：线上原文件先复制到 `profiles\_线上自动备份\<时间戳>_<文件名>`。
3. **写入后哈希校验**：绿字"已应用"表示内容确实落地，红字"校验失败"表示权限或占用问题。

## 流畅档具体改动

**三角洲-流畅**（相比基线，10 项；DLSS 保持原档不变）
| 项目 | 基线 | 流畅 |
|---|---|---|
| GraphicsPreset 全局预设 | 3（高） | 1（低） |
| ReflectionQuality 反射 | 3 | 1 |
| AmbientOcclusionQuality 环境光遮蔽 | 3 | 1 |
| ParticleQuality 粒子 | 3 | 1 |
| DistortionQuality 色彩失真 | 3 | 1 |
| SceneDetailLevel 场景细节 | 3 | 1 |
| GIQuality 全局光照 | 3 | 1 |
| ViewDistanceLevel 视距 | 3 | 1 |
| PostProcessQuality 后处理 | 2 | 0 |
| VolumetricFogQuality 体积雾 | 2 | 0 |
| SuperResolutionQualityDLSS | 2 | 2（**保持不变**，不吃渲染分辨率）|

分辨率保持 2560×1600，独占全屏（`FullscreenMode=0`，UE 枚举中 0=独占全屏）。
`NVIDIAReflexMode=2` 保持不变（Reflex 开启+加速）。

**CS2-流畅**（相比基线，11 项）
| 项目 | 基线 | 流畅 |
|---|---|---|
| fullscreen 显示模式 | 0（无边框） | 1（独占全屏） |
| nowindowborder 无边框 | 1 | 0 |
| mat_vsync 垂直同步 | 1（开） | 0（关） |
| msaa_samples 多重采样 | 4 | 0（关） |
| r_csgo_cmaa_enable CMAA2 | 0 | 1（开） |
| shaderquality 着色器 | 1 | 0 |
| r_texturefilteringquality 纹理过滤 | 3 | 0 |
| videocfg_shadow_quality 阴影 | 2 | 1 |
| videocfg_texture_detail 纹理 | 2 | 1 |
| videocfg_particle_detail 粒子 | 2 | 0 |
| videocfg_ao_detail 环境光遮蔽 | 2 | 0 |

分辨率保持原生 2560×1600。

## 注意事项

- **切换前必须先退出游戏**（脚本已强制检查）。
- CS2 首次启动新配置若弹"检测到配置变化"，选"保留我的设置"。
- 三角洲键位/灵敏度存在 `Input.ini` 和 `UserSystemSetting.ini`，本方案不动这些，**不影响键位**。
- 想在游戏内调参：调好 → 退出游戏 → 让我把线上文件存回档案目录，否则下次切换会被覆盖。
- 游戏大版本更新后若画质选项异常，重跑一次切换即可。
- **纹理建议**：纹理主要吃显存不显著影响帧数。6GB 显存在 2560×1600 下可尝试把 CS2 的 `videocfg_texture_detail` 调回 2、三角洲 `TextureFilteringQuality` 调回 2~3，画质提升明显。

## 预期帧率

- CS2：大部分地图 200+ FPS
- 三角洲大战场：100~140 FPS