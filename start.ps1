# 专注小蛙 - Windows 一键启动
# 用法: 右键“使用 PowerShell 运行”，或在项目目录执行  .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# Xmuse OSC 接收配置（可在运行前覆盖）
# Xmuse Direct 默认把 OSC 推到 127.0.0.1:7000；
# 官方示例还会用 8000 / 8001 / 8002，所以默认同时监听 7000 和 8000。
if (-not $env:XMUSE_OSC_HOST) { $env:XMUSE_OSC_HOST = "127.0.0.1" }
if (-not $env:XMUSE_OSC_PORTS) { $env:XMUSE_OSC_PORTS = "7000,8000" }
if (-not $env:XMUSE_OSC_FS) { $env:XMUSE_OSC_FS = "256" }

$Python = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"

function Install-Deps {
    Write-Host "[1/3] 创建虚拟环境并安装依赖（首次约需 2-5 分钟）..."
    if (-not (Test-Path $Python)) {
        $created = $false
        try {
            & py -3 -m venv .venv-win
            $created = $?
        } catch {
            $created = $false
        }
        if (-not $created) {
            & python -m venv .venv-win
            if (-not $?) { throw "创建虚拟环境失败，请安装 Python 3.10+ 并勾选 Add to PATH" }
        }
    }
    & $Python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    & $Python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
}

if (-not (Test-Path $Python)) {
    Install-Deps
} else {
    # 兼容旧环境：缺少 python-osc 时自动补装依赖
    & $Python -c "import pythonosc" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[1/3] 检测到依赖缺失，正在补装..."
        & $Python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    } else {
        Write-Host "[1/3] 运行环境已就绪"
    }
}

Write-Host "[2/3] Xmuse OSC 监听 UDP $($env:XMUSE_OSC_HOST):$($env:XMUSE_OSC_PORTS)（HTTP 为 TCP 8000，互不冲突）"
Write-Host "      在 Xmuse Direct 中连接设备 -> 添加 OSC 输出 -> IP 127.0.0.1 / 端口 7000"
Write-Host "[3/3] 启动服务: http://127.0.0.1:8000  (Ctrl+C 停止)"
& $Python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
