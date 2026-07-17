# SAG PostgreSQL 快速修复方案（绕过Docker）

**问题:** Docker API版本不兼容，无法启动PostgreSQL容器  
**解决:** 使用本地PostgreSQL或修改SAG使用SQLite

---

## 方案1: 使用本地PostgreSQL（推荐）

端口5433上已经有PostgreSQL在运行，我们直接使用它。

### 步骤1: 找到psql工具

```powershell
# 常见位置
C:\Program Files\PostgreSQL\16\bin\psql.exe
C:\Program Files\PostgreSQL\15\bin\psql.exe
C:\PostgreSQL\bin\psql.exe

# 或者搜索
where psql.exe
```

### 步骤2: 连接PostgreSQL（尝试不同方式）

```powershell
# 方式1: 使用postgres用户（无密码）
psql -h localhost -p 5433 -U postgres

# 方式2: 使用postgres用户（有密码）
psql -h localhost -p 5433 -U postgres -W
# 输入密码: postgres / admin / root

# 方式3: 使用当前Windows用户
psql -h localhost -p 5433 -U $env:USERNAME
```

### 步骤3: 创建SAG数据库

连接成功后，执行以下SQL：

```sql
-- 创建用户
CREATE USER sag_lite WITH PASSWORD 'sag_lite_pass';

-- 创建数据库
CREATE DATABASE sag_lite OWNER sag_lite;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE sag_lite TO sag_lite;

-- 退出
\q
```

### 步骤4: 运行数据库迁移

```powershell
cd D:\SAG
npm run db:migrate
```

### 步骤5: 重启SAG服务

```powershell
# 如果SAG还在运行，先停止（Ctrl+C）
npm run dev
```

---

## 方案2: 修复Docker（如果时间允许）

### 选项A: 重启Docker Desktop

```powershell
# 1. 完全退出Docker Desktop
Stop-Process -Name "Docker Desktop" -Force

# 2. 等待5秒
Start-Sleep -Seconds 5

# 3. 重新启动Docker Desktop
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"

# 4. 等待Docker完全启动（约30秒）
Start-Sleep -Seconds 30

# 5. 再次尝试
cd D:\SAG
docker-compose up -d
```

### 选项B: 重置Docker设置

1. 打开Docker Desktop
2. 点击设置图标（右上角）
3. 选择 "Troubleshoot"
4. 点击 "Reset to factory defaults"
5. 等待重置完成后重试

---

## 方案3: 使用SQLite（最简单但功能受限）

如果PostgreSQL太麻烦，SAG可以临时使用SQLite：

### 修改 D:\SAG\.env

```bash
# 注释掉PostgreSQL配置
# DATABASE_URL=postgres://sag_lite:sag_lite_pass@localhost:5433/sag_lite

# 使用SQLite
DATABASE_URL=sqlite:./sag_lite.db
```

### 重启SAG

```powershell
cd D:\SAG
npm run db:migrate
npm run dev
```

**注意:** SQLite不支持pgvector扩展，向量搜索功能会受限。

---

## 快速验证脚本

创建 `test_postgres.ps1`:

```powershell
# 测试PostgreSQL连接
$env:PGPASSWORD="sag_lite_pass"
psql -h localhost -p 5433 -U sag_lite -d sag_lite -c "SELECT version();"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ PostgreSQL连接成功！" -ForegroundColor Green
    
    # 测试SAG API
    $health = Invoke-RestMethod -Uri "http://localhost:4173/health"
    if ($health.ok) {
        Write-Host "✅ SAG服务正常！" -ForegroundColor Green
    }
} else {
    Write-Host "❌ PostgreSQL连接失败" -ForegroundColor Red
    Write-Host "请执行方案1的步骤创建数据库" -ForegroundColor Yellow
}
```

---

## 推荐执行顺序

### 最快路径（5分钟）：

1. **找到psql** (1分钟)
   ```powershell
   where psql.exe
   ```

2. **连接并创建数据库** (2分钟)
   ```powershell
   psql -h localhost -p 5433 -U postgres
   # 执行CREATE USER和CREATE DATABASE命令
   ```

3. **运行迁移** (1分钟)
   ```powershell
   cd D:\SAG
   npm run db:migrate
   ```

4. **重启SAG** (1分钟)
   ```powershell
   npm run dev
   ```

5. **访问Web界面**
   - http://localhost:5174
   - 创建项目并上传文档

---

## 常见PostgreSQL密码

如果不知道密码，尝试这些：
- `postgres`
- `admin`
- `root`
- `password`
- `123456`
- (空密码)

---

## 如果所有方法都失败

### 终极方案: 临时绕过PostgreSQL

1. 修改SAG代码使用内存数据库（开发测试用）
2. 或者直接通过Tech Support Agent使用（已优化完成）
3. SAG作为可选增强功能，暂时跳过

**记住:** Tech Support Agent已经完全优化并可用，不依赖SAG！

---

## 需要帮助？

如果遇到问题，请提供：

```powershell
# 1. PostgreSQL版本
psql --version

# 2. 端口占用
netstat -ano | findstr :5433

# 3. 尝试连接的错误信息
psql -h localhost -p 5433 -U postgres 2>&1

# 4. SAG日志
cd D:\SAG
cat .output 2>&1
```

---

**更新时间:** 2026-07-09  
**预计修复时间:** 5-10分钟（方案1）

**重要提醒:** Tech Support Agent (http://localhost:8000) 已完全优化，
可以立即使用，不受PostgreSQL问题影响！
