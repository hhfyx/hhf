# 游戏配置切换脚本
# 用法: .\switch.ps1 <配置名>
#   baseline   | current | 1   -> 原始基线（还原）
#   delta-force| delta   | 2   -> 三角洲-流畅
#   cs2        | cs2     | 3   -> CS2-流畅
# 中文名也可用: 当前配置 / 三角洲-流畅 / CS2-流畅

param(
    [Parameter(Mandatory=$true)]
    [string]$Profile,

    # 跳过游戏进程检查（仅在确认游戏已退出但进程残留时使用）
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root       = "D:\git\前沿\游戏配置\profiles"
$Cs2CfgDir  = "D:\steam\userdata\1185089847\730\local\cfg"
$DfCfgDir   = "D:\steam\steamapps\common\Delta Force\Game\DeltaForce\Saved\Config\WindowsClient"

$Aliases = @{
    "current"     = "baseline"
    "restore"     = "baseline"
    "1"           = "baseline"
    "baseline"    = "baseline"
    "delta"       = "delta-force"
    "delta-force" = "delta-force"
    "df"          = "delta-force"
    "2"           = "delta-force"
    "cs2"         = "cs2"
    "3"           = "cs2"
    "当前配置"    = "baseline"
    "三角洲-流畅" = "delta-force"
    "CS2-流畅"    = "cs2"
}

$Display = @{
    "baseline"    = "原始基线"
    "delta-force" = "三角洲-流畅"
    "cs2"         = "CS2-流畅"
}

$key = $Profile.ToLower()
if ($Aliases.ContainsKey($key)) {
    $Profile = $Aliases[$key]
} else {
    Write-Host "可用配置: baseline(1) | delta-force(2) | cs2(3)" -ForegroundColor Yellow
    Write-Host "中文名: 当前配置 | 三角洲-流畅 | CS2-流畅" -ForegroundColor Yellow
    exit 1
}

$GameProcesses = @("cs2", "DeltaForceClient-Win64-Shipping")

# --- 进程守卫 ---
if (-not $Force) {
    $running = Get-Process -Name $GameProcesses -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "[拒绝] 检测到游戏正在运行：" -ForegroundColor Red
        $running | ForEach-Object {
            Write-Host ("    - {0}  (PID {1})" -f $_.ProcessName, $_.Id) -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "请先完全退出游戏再运行本脚本。" -ForegroundColor Yellow
        Write-Host "原因：游戏退出时会把内存中的旧设置写回配置文件，覆盖本次修改。" -ForegroundColor Yellow
        exit 1
    }
}

$SrcDir = Join-Path $Root $Profile
if (-not (Test-Path $SrcDir)) {
    Write-Host "配置目录不存在: $SrcDir" -ForegroundColor Red
    exit 1
}

# --- 覆盖前自动备份 ---
$BackupDir = Join-Path $Root "_线上自动备份"
New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Apply-File {
    param([string]$Source, [string]$Target, [string]$Label)

    if (-not (Test-Path $Source)) {
        Write-Host "[$Label] 该配置不含此文件，跳过" -ForegroundColor DarkGray
        return
    }
    if (-not (Test-Path $Target)) {
        Write-Host "[$Label] 目标路径不存在: $Target" -ForegroundColor Red
        return
    }

    $leaf = Split-Path $Target -Leaf
    Copy-Item $Target (Join-Path $BackupDir "$Stamp`_$leaf") -Force
    Copy-Item $Source $Target -Force

    $ok = (Get-FileHash $Source).Hash -eq (Get-FileHash $Target).Hash
    if ($ok) {
        Write-Host "[$Label] 已应用 -> $leaf" -ForegroundColor Green
    } else {
        Write-Host "[$Label] 写入后校验失败 -> $leaf" -ForegroundColor Red
    }
}

# --- CS2 ---
if ($Profile -in @("baseline", "cs2")) {
    Apply-File -Source (Join-Path $SrcDir "cs2_video.txt") -Target (Join-Path $Cs2CfgDir "cs2_video.txt") -Label "CS2"
} else {
    Write-Host "[CS2] 未改动" -ForegroundColor DarkGray
}

# --- 三角洲 ---
if ($Profile -in @("baseline", "delta-force")) {
    Apply-File -Source (Join-Path $SrcDir "UserSystemSettingHD.ini") -Target (Join-Path $DfCfgDir "UserSystemSettingHD.ini") -Label "三角洲"
    Apply-File -Source (Join-Path $SrcDir "GameUserSettings.ini") -Target (Join-Path $DfCfgDir "GameUserSettings.ini") -Label "三角洲"
} else {
    Write-Host "[三角洲] 未改动" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host ("完成。当前: " + $Display[$Profile]) -ForegroundColor Cyan
Write-Host "覆盖前原文件已备份到: $BackupDir" -ForegroundColor Cyan