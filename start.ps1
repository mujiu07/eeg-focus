# 专注小蛙 - Windows 一键启动
# 用法: 右键“使用 PowerShell 运行”，或在项目目录执行  .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$Python = Join-Path $PSScriptRoot ".venv-win\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "[1/2] 未找到 .venv-win，正在创建虚拟环境并安装依赖（首次约需 2-5 分钟）..."
    python -m venv .venv-win
    if (-not $?) { throw "创建虚拟环境失败，请确认已安装 Python 3.10+ 并加入 PATH" }
    & $Python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    & $Python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
}

Write-Host "[2/2] 启动服务: http://127.0.0.1:8000  (Ctrl+C 停止)"
& $Python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
