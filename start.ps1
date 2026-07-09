# Seeed Tech Support Agent - 启动脚本
# 一键启动所有服务：Qdrant (Docker) + Pipeline 构建 + FastAPI Agent + Streamlit UI

param(
    [switch]$SkipQdrant,
    [switch]$SkipIndex,
    [switch]$OnlyAPI,
    [switch]$OnlyUI
)

$projectRoot = "D:/tech-support-agent"
Set-Location $projectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Seeed Tech Support Agent 启动脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# ---- 0. 加载 .env（不打印 key 明文） ----
$envFile = Join-Path $projectRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$') {
            $name = $matches[1]
            $value = $matches[2]
            if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
    Write-Host "  ✓ 已加载 .env (mask 模式：key 不回显)" -ForegroundColor Green
}

# ---- 1. 启动 Qdrant ----
if (-not $SkipQdrant) {
    Write-Host "[1/4] 启动 Qdrant..." -ForegroundColor Yellow

    # 优先路径：Qdrant Windows native binary
    $qdrantBin = Join-Path $projectRoot "tools\qdrant\qdrant.exe"
    $qdrantBinAlt = "D:\tech-support-agent\tools\qdrant\qdrant.exe"

    $dockerOk = $true
    try {
        docker version --format '{{.Server.Version}}' 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { $dockerOk = $false }
    } catch { $dockerOk = $false }

    $portInUse = (Get-NetTCPConnection -LocalPort 6333 -State Listen -ErrorAction SilentlyContinue) -ne $null

    if ($portInUse) {
        Write-Host "  ✓ Qdrant 端口 6333 已被占用（应是已起好的服务）" -ForegroundColor Green
    }
    elseif (Test-Path $qdrantBin) {
        # 用 native binary 起（后台），数据落到 tools/qdrant/storage
        $qdrantHome = Join-Path $projectRoot "tools\qdrant"
        $storageDir = Join-Path $qdrantHome "storage"
        if (-not (Test-Path $storageDir)) { New-Item -ItemType Directory -Path $storageDir -Force | Out-Null }
        $env:QDRANT__SERVICE__HTTP_PORT = "6333"
        $env:QDRANT__SERVICE__GRPC_PORT = "6334"
        $env:QDRANT__STORAGE__STORAGE_PATH = $storageDir
        Write-Host "  → 使用 native binary: $qdrantBin" -ForegroundColor Cyan
        $qdrantPid = Start-Process -FilePath $qdrantBin -PassThru -WindowStyle Hidden -WorkingDirectory $qdrantHome
        Write-Host "  ✓ Qdrant native 启动 PID=$($qdrantPid.Id)" -ForegroundColor Green
        Start-Sleep -Seconds 3
    }
    elseif (Test-Path $qdrantBinAlt) {
        $env:QDRANT__SERVICE__HTTP_PORT = "6333"
        $env:QDRANT__SERVICE__GRPC_PORT = "6334"
        $qdrantPid = Start-Process -FilePath $qdrantBinAlt -PassThru -WindowStyle Hidden
        Write-Host "  ✓ Qdrant native 启动 PID=$($qdrantPid.Id)" -ForegroundColor Green
        Start-Sleep -Seconds 3
    }
    elseif ($dockerOk) {
        Write-Host "  → 通过 Docker 启动" -ForegroundColor Cyan
        $qdrantExists = docker ps -a --filter "name=qdrant" --format "{{.Names}}" 2>$null
        if ($qdrantExists -eq "qdrant") {
            $running = docker ps --filter "name=qdrant" --format "{{.Names}}" 2>$null
            if ($running -eq "qdrant") {
                Write-Host "  ✓ Qdrant 已在运行" -ForegroundColor Green
            } else {
                docker start qdrant 2>$null | Out-Null
                Write-Host "  ✓ Qdrant 已启动" -ForegroundColor Green
            }
        } else {
            docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant 2>$null | Out-Null
            Write-Host "  ✓ Qdrant 容器已创建并启动" -ForegroundColor Green
        }
        Start-Sleep -Seconds 2
    }
    else {
        Write-Host "  ⚠ Docker Desktop 不可达、本地无 qdrant.exe — 向量检索暂不可用" -ForegroundColor DarkYellow
        Write-Host "    解决方法：启 Docker Desktop 或解压 tools/qdrant/qdrant.exe" -ForegroundColor DarkYellow
    }
}

# ---- 2. 构建索引 ----
if (-not $SkipIndex -and -not $OnlyUI) {
    Write-Host "[2/4] 构建 Wiki 向量索引..." -ForegroundColor Yellow
    if (-not (Test-Path "D:/tech-support-agent/data/index.json")) {
        python -m pipeline.main
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ✗ Pipeline 失败" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "  ✓ index.json 已存在，跳过构建" -ForegroundColor Green
    }
}

# ---- 3. 启动 FastAPI Agent ----
if (-not $OnlyUI -and -not $OnlyAPI -or $OnlyAPI) {
    Write-Host "[3/4] 启动 FastAPI Agent..." -ForegroundColor Yellow
    $apiPid = Start-Process -FilePath "python" -ArgumentList "-m","agent.main" -PassThru -WindowStyle Hidden
    Write-Host "  ✓ FastAPI 启动 PID=$($apiPid.Id)" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

if ($OnlyUI) {
    # 只启动 UI
    Write-Host "[4/4] 启动 Streamlit UI..." -ForegroundColor Yellow
    streamlit run ui/app.py --server.port 8501
    exit
}

# ---- 4. 启动 Streamlit UI ----
Write-Host "[4/4] 启动 Streamlit UI..." -ForegroundColor Yellow
Write-Host ""
Write-Host "服务地址：" -ForegroundColor Magenta
Write-Host "  - FastAPI:  http://localhost:8000" -ForegroundColor White
Write-Host "  - Streamlit: http://localhost:8501" -ForegroundColor White
Write-Host "  - Qdrant:   http://localhost:6333/dashboard" -ForegroundColor White
Write-Host ""
Write-Host "按 Ctrl+C 停止所有服务" -ForegroundColor Gray

streamlit run ui/app.py --server.port 8501
