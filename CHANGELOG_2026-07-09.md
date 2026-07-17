# 技术支持 Agent 优化记录
**日期**: 2026-07-09  
**任务**: SAG 独立运行 + Web UI 优化

---

## ✅ 已完成的任务

### 1. SAG 工作流独立运行脚本

**创建文件**: `run_sag.py`

**功能特性**:
- ✅ 支持交互式对话模式
- ✅ 支持单次查询模式
- ✅ 支持调试模式（显示每个节点执行详情）
- ✅ 支持工作流可视化（生成 PNG 图）

**使用方式**:
```bash
# 交互式模式
python run_sag.py

# 单次查询
python run_sag.py "你的问题"

# 调试模式
python run_sag.py "问题" --debug

# 可视化工作流
python run_sag.py --visualize
```

**测试结果**:
- ✅ 完整的 6 节点流程正常运行（query_rewrite → classify → retrieve → retrieve_historical → reflect → generate）
- ✅ 修复了递归限制问题（max_rewrites 逻辑优化）
- ✅ 历史回复融合功能正常（检索到 3 条相似工单）
- ✅ 生成高质量回答（约 60-70 秒执行时间）

---

### 2. Web UI 超时问题修复

**问题**: 用户在 Web UI 提问时遇到 60 秒超时错误

**修改文件**: `ui/app.py` (第 176 行)

**修复内容**:
```python
# 修复前
timeout=60

# 修复后
timeout=180  # SAG 工作流需要更长时间（包含 rewrite 循环）
```

---

### 3. 邮件模板优化

**问题**:
1. 重复的问候语（"Hi there" + "Dear XXX"）
2. 重复的结尾签名
3. 重复的诊断信息请求
4. AI 味太浓（过多标题、加粗）
5. "Historical Reference Patterns" 暴露给用户

**修改文件**: `agent/templates/troubleshooting.md`

**优化内容**:
- ❌ 删除了所有 Markdown 标题（##, ###）
- ❌ 移除了"Historical Reference Patterns"内部参考信息
- ❌ 移除了重复的参考文档区块
- ❌ 删除了模板中固定的诊断信息请求
- ✅ 改为简洁自然的邮件风格
- ✅ 只保留一个问候语和一个签名

**修复前的结构**:
```markdown
## Your Question
## Initial Response
## Suggested Troubleshooting Steps
## Historical Reference Patterns
## Reference Documentation
## Information We Need From You
Best Regards (x2)
```

**修复后的结构**:
```markdown
Hi there,

Thank you for contacting Seeed Studio Technical Support.

{{ answer }}

Best regards,
Seeed Studio Technical Support Team
```

---

### 4. LLM 生成提示词优化

**问题**: LLM 生成的回答中包含重复的问候语、签名和诊断请求

**修改文件**: `agent/generator.py` (第 15-25 行)

**优化内容**:
```python
邮件格式要求：
- 只写邮件正文，不要重复问候语（模板已包含 "Hi there" 开头）
- 直接进入主题，不要再写 "Dear XXX" 或 "Thank you for contacting..."
- 结尾不要写 "Best regards" 等签名（模板已包含）
- 避免重复请求信息或排查步骤
- 保持简洁专业的客服邮件风格，不要过度使用标题和加粗
```

---

### 5. 检索精度优化

**问题**: 
- 用户询问 "reComputer Super" 时召回了大量不相关文档
- "reComputer Super Hardware and Interfaces Usage" 没有排在前列

**修改内容**:

#### 5.1 配置优化 (`config.yaml` 第 60-67 行)
```yaml
# 修复前
backend: "hybrid"  # 依赖外部 SAG 服务（端口 4173）
top_k: 5
min_score: 0.25

# 修复后
backend: "qdrant"  # 纯向量检索，更稳定
top_k: 10
min_score: 0.30
```

#### 5.2 关键词扩展 (`agent/retriever.py` 第 24-34 行)
```python
_KEYWORD_SYNONYMS = {
    # ... 原有内容 ...
    "super": "reComputer Super J4012 J4011 J3011 J3010",  # 新增
    "j4012": "J4012 reComputer Super Orin NX 16GB",      # 新增
    "eth1": "eth1 second ethernet port network interface RJ45",  # 新增
}
```

**测试结果**:
- ✅ "reComputer Super Hardware and Interfaces Usage" 现在排在第 1 位（score=0.692）
- ✅ 检索召回的文档更加精准

---

### 6. SAG 工作流递归限制修复

**问题**: SAG 工作流在 max_rewrites=2 后仍然触发递归限制错误

**修改文件**: 
- `agent/graph.py` (route_after_reflect 函数)
- `run_sag.py` (recursion_limit 参数)

**修复内容**:
```python
# graph.py - 优先检查迭代次数
if iterations >= cfg_max_rewrites:
    logger.info(f"[reflect→generate] max_rewrites={iterations} reached, force generate")
    return "generate"
if score >= cfg_threshold:
    return "generate"

# run_sag.py - 增加递归限制
graph.invoke(initial_state, {"recursion_limit": 50})  # 从 10 增加到 50
```

---

## 📊 服务运行状态

| 服务 | 端口 | 状态 | 备注 |
|------|------|------|------|
| FastAPI 后端 | 8000 | ✅ 运行中 | SAG 工作流引擎 |
| Streamlit 前端 | 8501 | ✅ 运行中 | Web UI 界面 |
| Qdrant 向量库 | 6333 | ✅ 运行中 | 5134 chunks indexed |

---

## 🚀 推荐使用方式

### 方式 1: 独立脚本测试（最稳定）
```bash
python run_sag.py
```

### 方式 2: Web UI
访问: http://localhost:8501
- 超时已修复（180秒）
- 邮件模板已优化

### 方式 3: API 调用
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你的问题"}'
```

---

## 📝 关键文件清单

### 新增文件
- `run_sag.py` - SAG 独立运行脚本
- `graph_visualization.png` - 工作流可视化图
- `start_services.sh` - 服务启动脚本

### 修改文件
- `agent/graph.py` - 修复递归限制逻辑
- `agent/generator.py` - 优化 LLM 系统提示词
- `agent/templates/troubleshooting.md` - 简化邮件模板
- `agent/retriever.py` - 增加关键词扩展
- `ui/app.py` - 增加超时时间
- `config.yaml` - 优化检索配置

---

## ⚠️ 已知问题

### 1. API Key 401 错误（已识别，未完全解决）
**现象**: 部分 LLM 调用（classify 和 generate 节点）间歇性失败

**临时解决方案**: 使用独立脚本 `run_sag.py` 可以完全绕过这个问题

**根本原因**: 环境变量加载时机问题，OpenAI 客户端初始化时未正确获取 API Key

**建议**: 未来可以考虑在 `config.yaml` 中直接配置 API Key（避免依赖环境变量）

---

## 🎯 测试验证

### SAG 工作流测试
```bash
python run_sag.py "reComputer J4012 supports which JetPack version?"
```

**结果**:
- ✅ 查询改写成功
- ✅ 分类为 compatibility
- ✅ 检索到 10 条 Wiki 文档
- ✅ 检索到 3 条历史回复
- ✅ 反思评估正常
- ✅ 生成高质量表格式回答

### 检索精度测试
```bash
python run_sag.py "reComputer Super J4012 eth1 port not working"
```

**结果**:
- ✅ "reComputer Super Hardware and Interfaces Usage" 排在前列
- ✅ 相关文档召回精准

---

## 📚 相关文档

- SAG 工作流文档: `docs/SAG_DEPLOY_AND_INTEGRATION.md`
- 配置说明: `config.yaml`
- 邮件模板目录: `agent/templates/`

---

*更新时间: 2026-07-09*
*维护者: Seeed Studio 技术支持团队*
