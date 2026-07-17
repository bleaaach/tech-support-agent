# SAG PostgreSQL 密码问题解决方案

**问题:** 用户 "sag_lite" Password 验证失败  
**原因:** 端口5433被其他PostgreSQL占用，密码不匹配

---

## 快速解决方案（推荐）

### 方法1: 使用管理员权限停止冲突进程

1. **以管理员身份打开PowerShell**
   - 右键点击开始菜单
   - 选择 "Windows PowerShell (管理员)" 或 "终端 (管理员)"

2. **停止占用5433端口的进程**
   ```powershell
   # 查找进程
   netstat -ano | findstr :5433
   
   # 停止进程（PID 9472）
   taskkill /F /PID 9472
   ```

3. **启动Docker PostgreSQL**
   ```powershell
   cd D:\SAG
   docker-compose up -d
   ```

4. **验证启动**
   ```powershell
   docker ps | findstr postgres
   curl http://localhost:4173/health
   ```

---

## 方法2: 手动配置现有PostgreSQL

如果不想停止现有PostgreSQL，可以在其中创建SAG需要的数据库：

### 步骤1: 找到PostgreSQL的psql工具

常见位置：
- `C:\Program Files\PostgreSQL\<version>\bin\psql.exe`
- `C:\PostgreSQL\<version>\bin\psql.exe`

### 步骤2: 连接到PostgreSQL

```bash
# 方式1: 使用postgres超级用户
psql -h localhost -p 5433 -U postgres

# 方式2: 如果有密码
psql -h localhost -p 5433 -U postgres -W
```

常见默认密码：
- `postgres`
- `admin`
- `root`
- (空密码)

### 步骤3: 创建SAG数据库和用户

连接成功后执行以下SQL：

```sql
-- 创建用户
CREATE USER sag_lite WITH PASSWORD 'sag_lite_pass';

-- 创建数据库
CREATE DATABASE sag_lite OWNER sag_lite;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE sag_lite TO sag_lite;

-- 切换到sag_lite数据库
\c sag_lite

-- 启用pgvector扩展（如果已安装）
CREATE EXTENSION IF NOT EXISTS vector;

-- 退出
\q
```

### 步骤4: 重启SAG服务

```bash
cd D:\SAG
# 停止当前SAG服务
# 按 Ctrl+C 停止正在运行的 npm run dev

# 重新启动
npm run dev
```

---

## 方法3: 更改SAG使用不同的端口

如果不想动现有的PostgreSQL，让SAG使用不同的端口：

### 1. 修改 D:\SAG\.env

```bash
# 改为其他端口，如5434
DATABASE_URL=postgres://postgres:你的密码@localhost:5433/sag_lite
```

### 2. 在现有PostgreSQL中创建数据库

使用上面方法2的步骤2和步骤3。

---

## 验证修复

修复后执行以下命令验证：

```bash
# 1. 检查SAG服务
curl http://localhost:4173/health
# 应该返回: {"ok":true,"service":"sag"}

# 2. 检查项目
curl http://localhost:4173/api/projects
# 应该返回项目列表

# 3. 测试Web界面
# 浏览器访问: http://localhost:5174
```

---

## 常见问题

### Q1: 不知道PostgreSQL密码
**A:** 尝试以下方法：
1. 查看 `C:\Program Files\PostgreSQL\<version>\data\pg_hba.conf`
2. 临时修改认证方式为 `trust`（允许无密码连接）
3. 重启PostgreSQL
4. 连接后重置密码

### Q2: 没有安装pgvector扩展
**A:** pgvector不是必需的，SAG可以在没有向量搜索的情况下工作。如果需要，可以：
1. 从 https://github.com/pgvector/pgvector 下载
2. 编译安装（需要Visual Studio）
3. 或使用Docker版本（已包含pgvector）

### Q3: Docker命令失败
**A:** 检查Docker Desktop：
- 确保Docker Desktop正在运行
- 检查是否有版本更新
- 尝试重启Docker Desktop

---

## 当前状态总结

### ✅ 已正常工作
- Tech Support Agent服务 (http://localhost:8000)
- Qdrant (http://localhost:6333)
- SAG API服务 (http://localhost:4173)
- SAG Web界面 (http://localhost:5174)

### ⚠️ 需要修复
- PostgreSQL连接（密码验证失败）
- SAG数据库未初始化
- 无法通过Web界面上传文档

### 🎯 修复后的效果
- ✅ 可以在Web界面创建项目
- ✅ 可以上传Wiki文档
- ✅ SAG自动提取事件和实体
- ✅ Hybrid检索模式完全激活

---

## 推荐执行顺序

**最快速的解决方案：**

1. 以管理员身份运行PowerShell
2. 执行: `taskkill /F /PID 9472`
3. 执行: `cd D:\SAG && docker-compose up -d`
4. 访问 http://localhost:5174 测试

**如果上述方法不可行：**

1. 找到psql工具位置
2. 连接到端口5433的PostgreSQL
3. 执行SQL创建数据库和用户
4. 重启SAG服务

---

## 技术支持

如果以上方法都不能解决，请提供以下信息：

```bash
# 1. PostgreSQL版本
psql --version

# 2. 端口占用情况
netstat -ano | findstr :5433

# 3. Docker状态
docker ps -a

# 4. SAG日志
# 查看 D:\SAG 目录下的日志文件
```

---

**文档更新:** 2026-07-09  
**预计修复时间:** 5-10分钟
