# SAG PostgreSQL 最终修复方案

**当前状态:** 5433端口被占用但无法连接

---

## 快速解决方案

### 方案1: 停止占用端口的进程并使用Docker（推荐）

**在PowerShell（管理员）中执行：**

```powershell
# 1. 停止占用5433端口的进程
taskkill /F /PID 9472

# 2. 重启Docker Desktop（完全退出并重新打开）
# 方式A: 通过任务管理器
# - 找到 "Docker Desktop" 进程
# - 右键 → 结束任务
# - 从开始菜单重新打开Docker Desktop

# 方式B: 通过命令
Stop-Process -Name "Docker Desktop" -Force
Start-Sleep -Seconds 10
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# 3. 等待Docker完全启动（约1分钟）
Start-Sleep -Seconds 60

# 4. 启动PostgreSQL容器
cd D:\SAG
docker-compose up -d

# 5. 验证
docker ps | findstr postgres
curl http://localhost:4173/health
```

---

### 方案2: 使用PostgreSQL 16并配置远程连接

如果Docker持续有问题，配置本地PostgreSQL：

#### 步骤1: 找到PostgreSQL配置文件

```powershell
# 通常在这里
cd "C:\Program Files\PostgreSQL\16\data"
notepad pg_hba.conf
```

#### 步骤2: 修改 pg_hba.conf

在文件中添加（允许本地连接）：

```conf
# 在文件末尾添加
host    all             all             127.0.0.1/32            trust
host    sag_lite        sag_lite        127.0.0.1/32            md5
```

#### 步骤3: 修改 postgresql.conf

```powershell
notepad postgresql.conf
```

找到并修改：
```conf
listen_addresses = 'localhost'
port = 5433
```

如果port不是5433，改为5433或者修改SAG配置使用正确端口。

#### 步骤4: 重启PostgreSQL服务

```powershell
# 查找PostgreSQL服务名
Get-Service | Where-Object {$_.Name -like '*postgres*'}

# 重启服务（服务名可能是 postgresql-x64-16）
Restart-Service postgresql-x64-16
```

#### 步骤5: 创建SAG数据库

```powershell
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -p 5433 -U postgres -c "CREATE USER sag_lite WITH PASSWORD 'sag_lite_pass';"
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -p 5433 -U postgres -c "CREATE DATABASE sag_lite OWNER sag_lite;"
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -p 5433 -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sag_lite TO sag_lite;"
```

#### 步骤6: 运行SAG迁移

```powershell
cd D:\SAG
npm run db:migrate
npm run dev
```

---

### 方案3: 修改SAG使用默认PostgreSQL端口

如果PostgreSQL在5432端口运行：

#### 修改 D:\SAG\.env

```bash
# 改为5432端口
DATABASE_URL=postgres://sag_lite:sag_lite_pass@localhost:5432/sag_lite
```

然后执行方案2的步骤5和步骤6。

---

## 验证成功

修复后执行：

```powershell
# 1. 测试PostgreSQL连接
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -p 5433 -U sag_lite -d sag_lite -c "SELECT version();"

# 2. 测试SAG API
curl http://localhost:4173/health

# 3. 访问Web界面
# 浏览器打开: http://localhost:5174
```

如果看到以下结果表示成功：
- PostgreSQL返回版本信息 ✅
- SAG返回 `{"ok":true,"service":"sag"}` ✅
- Web界面可以访问 ✅

---

## 一键检查脚本

创建 `check_sag.ps1`:

```powershell
Write-Host "=== SAG系统检查 ===" -ForegroundColor Cyan

# 检查端口
Write-Host "`n1. 检查端口5433..." -ForegroundColor Yellow
$port = netstat -ano | findstr :5433 | findstr LISTENING
if ($port) {
    Write-Host "  ✅ 端口5433已监听" -ForegroundColor Green
} else {
    Write-Host "  ❌ 端口5433未监听" -ForegroundColor Red
}

# 检查PostgreSQL连接
Write-Host "`n2. 检查PostgreSQL连接..." -ForegroundColor Yellow
$env:PGPASSWORD = "sag_lite_pass"
$result = & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -h localhost -p 5433 -U sag_lite -d sag_lite -c "SELECT 1;" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✅ PostgreSQL连接成功" -ForegroundColor Green
} else {
    Write-Host "  ❌ PostgreSQL连接失败" -ForegroundColor Red
    Write-Host "  错误: $result" -ForegroundColor Red
}

# 检查SAG API
Write-Host "`n3. 检查SAG API..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "http://localhost:4173/health" -ErrorAction Stop
    if ($health.ok) {
        Write-Host "  ✅ SAG API正常" -ForegroundColor Green
    }
} catch {
    Write-Host "  ❌ SAG API无响应" -ForegroundColor Red
}

# 检查Web界面
Write-Host "`n4. 检查Web界面..." -ForegroundColor Yellow
try {
    $web = Invoke-WebRequest -Uri "http://localhost:5174" -UseBasicParsing -ErrorAction Stop
    Write-Host "  ✅ Web界面可访问" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Web界面无响应" -ForegroundColor Red
}

Write-Host "`n=== 检查完成 ===" -ForegroundColor Cyan
```

---

## 推荐执行顺序

1. **首选方案1**（如果能停止进程）
   - 停止占用5433的进程
   - 重启Docker Desktop
   - 启动PostgreSQL容器
   - 预计时间: 3-5分钟

2. **备选方案2**（如果Docker持续有问题）
   - 配置本地PostgreSQL
   - 创建数据库
   - 预计时间: 10-15分钟

3. **最后方案3**（如果PostgreSQL在其他端口）
   - 修改SAG配置
   - 预计时间: 2分钟

---

## 需要帮助？

如果所有方案都失败，请提供：

```powershell
# 运行以下命令收集信息
netstat -ano | findstr :5433 > D:\sag_debug.txt
Get-Service | Where-Object {$_.Name -like '*postgres*'} >> D:\sag_debug.txt
docker ps -a >> D:\sag_debug.txt
Get-Process -Id 9472 -ErrorAction SilentlyContinue >> D:\sag_debug.txt
```

将 `D:\sag_debug.txt` 的内容提供给技术支持。

---

**更新时间:** 2026-07-09  
**状态:** 等待执行
