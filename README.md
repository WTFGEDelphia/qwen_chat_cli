# Qwen API Gateway - /new 命令优化版

支持 `stateless`/`stateful` 双模式的 Qwen Studio API 网关，兼容流式/非流式响应，
支持 `/new` 命令主动重置会话。

## 特性

- **双模式支持**:
  - `stateless`: 每次请求独立会话，客户端负责拼接历史
  - `stateful`: 全局单会话，后台维护上下文
- **流式响应**: 完美兼容 `stream=true/false`
- **/new 命令**: stateful 模式下主动创建新会话
- **多模态兼容**: 安全处理 `content` 为字符串或列表
- **纯异步栈**: FastAPI + async_playwright + httpx
- **高并发**: asyncio.Lock 保护共享资源
- **自动刷新**: 25 分钟自动刷新风控令牌

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填写你的邮箱、密码和 API_KEY
```

### 3. 启动服务

```bash
# stateful 模式（推荐，支持 /new 命令）
python main.py --mode stateful --port 8000

# stateless 模式（兼容第三方客户端）
python main.py --mode stateless --port 8000
```

### 4. 测试 API

#### 健康检查

```bash
curl http://localhost:8000/health
```

#### 获取模型列表

```bash
curl -H "Authorization: Bearer sk-qwen-studio-123456" \
  http://localhost:8000/v1/models
```

#### 发送对话（流式）

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-qwen-studio-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

#### 创建新会话（/new 命令）

```bash
# 流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-qwen-studio-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "/new"}],
    "stream": true
  }'

# 非流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-qwen-studio-123456" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "/new"}],
    "stream": false
  }'
```

## 特殊命令

| 命令 | 说明 | 适用模式 | 响应格式 |
|------|------|---------|---------|
| `/new` | 创建新会话，清除上下文 | stateful | 兼容 stream=true/false |

## 运行模式对比

| 模式 | 行为 | 适用场景 | /new 命令 |
|------|------|---------|----------|
| **stateless** | 每次请求创建独立 chat_id | Cursor、Chatbox 等第三方客户端 | 无效（提示） |
| **stateful** | 全局单 chat_id，后台维护上下文 | 单用户长期对话 | ✅ 有效 |

## 多模态支持

API 兼容多模态请求格式：

```json
{
  "model": "qwen3.6-plus",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "这张图片是什么？"},
      {"type": "image_url", "image_url": {"url": "https://..."}}
    ]
  }],
  "stream": false
}
```

## 技术架构

- **FastAPI**: 异步 Web 框架
- **Playwright**: 无头浏览器自动化，获取风控令牌
- **httpx**: 异步 HTTP 客户端
- **Pydantic v2**: 数据验证
- **asyncio.Lock**: 并发安全保护

## 许可证

MIT License
