# qwen-api-gateway

基于 FastAPI 的 [Qwen Studio](https://chat.qwen.ai/) 反向代理网关，提供 `stateless`/`stateful` 双模式支持，兼容 OpenAI API 格式。

这个项目提供一个本地 HTTP 服务，把 Qwen Studio 的登录认证转成兼容 OpenAI API 的接口。它默认面向本机使用，因为会处理高敏感度的账号凭证和风控令牌。

项目采用模块化架构，通过 Playwright 无头浏览器自动抓取风控令牌，并封装 Qwen 官方 API 交互。

本项目与通义千问无官方关联，也不适合部署到公网。

## 能做什么

- 本地启动兼容 OpenAI API 格式的 HTTP 服务
- 自动登录 Qwen Studio 并获取认证 token
- 自动抓取和刷新风控令牌 (`bx-ua`, `bx-umidtoken`)，25 分钟自动刷新
- 支持 `stateless` 模式（每次请求独立 chat_id，兼容第三方客户端）
- 支持 `stateful` 模式（全局单 chat_id，后台维护上下文）
- 支持 `/new` 命令主动重置会话（stateful 模式）
- 支持流式 (`stream=true`) 和非流式 (`stream=false`) 响应
- 支持多模态请求（`content` 为字符串或 `[{type: "text", text: "..."}]` 格式）
- 深度思考内容自动封装在 `<think>...</think>` 标签中

## 快速开始

如果你只是想本地跑起来，最短路径是：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# 编辑 .env：填写 QWEN_EMAIL、QWEN_PASSWORD，并把 API_KEY 改成强随机值
python -m qwen_gateway --mode stateful --port 8000
```

然后打开另一个终端测试 API：

```bash
curl http://localhost:8000/health
```

要求：Python 3.10 或更高版本。

## 安装方式

### 1. 源码开发安装

适合本地开发、调试和跑测试。

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. 从 GitHub tag 直接安装

适合希望直接按 tag 安装源码包的场景。

```bash
pip install "qwen-gateway @ git+https://github.com/WTFGEDelphia/qwen_chat_cli.git@v1.0.0"
```

说明：

- `v1.0.0` 是示例版本标签；如果后续发了新 tag，替换成目标版本即可
- 这种方式会从 GitHub 拉取对应 tag 的源码并安装

### 3. 从 GitHub Release 的 wheel 安装

适合不想直接拉源码、只想安装发布产物的场景。

```bash
pip install ./dist/qwen_gateway-1.0.0-py3-none-any.whl
```

### 4. 环境变量配置

```bash
cp .env.example .env
# 编辑 .env：填写 QWEN_EMAIL、QWEN_PASSWORD，并把 API_KEY 改成强随机值
```

## 启动方式

### 1. 开发模式

```bash
python -m qwen_gateway --mode stateful --port 8000 --reload
```

### 2. 生产模式（安装包）

```bash
qwen-gateway --mode stateful --port 8000
```

或者直接运行：

```bash
python -m qwen_gateway --mode stateful --port 8000
```

### 3. 显式对外监听

默认绑定 `127.0.0.1`，只接受本机访问。如果确实需要局域网访问，必须同时显式指定 `--host 0.0.0.0` 并设置非默认 `API_KEY`：

```bash
API_KEY=sk-your-strong-random-secret \
python -m qwen_gateway --mode stateful --host 0.0.0.0 --port 8000
```

## API 使用说明

下面的请求示例假设你已经把 `.env` 里的 `API_KEY` 改成强随机值，并在当前终端导出同一个值：

```bash
export API_KEY=sk-your-strong-random-secret
```

### 健康检查

```bash
curl http://localhost:8000/health
```

返回示例：

```json
{"status": "ok", "mode": "stateful"}
```

### 获取模型列表

```bash
curl -H "Authorization: Bearer $API_KEY" \
  http://localhost:8000/v1/models
```

返回示例：

```json
{
  "object": "list",
  "data": [
    {"id": "qwen3.6-plus", "object": "model", "created": 1715600000, "owned_by": "qwen"},
    {"id": "qwen3.5-plus", "object": "model", "created": 1715600000, "owned_by": "qwen"}
  ]
}
```

### 发送对话（流式）

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -N -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### 发送对话（非流式）

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

返回示例：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1715600000,
  "model": "qwen3.6-plus",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "你好！有什么我可以帮你的吗？"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

### 创建新会话（/new 命令）

```bash
# 流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -N -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "/new"}],
    "stream": true
  }'

# 非流式请求
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{"role": "user", "content": "/new"}],
    "stream": false
  }'
```

### 多模态请求

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-plus",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "这张图片是什么？"}
      ]
    }],
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
| **stateful** | 全局单 chat_id，后台维护上下文 | 单用户长期对话 | 有效 |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QWEN_EMAIL` | Qwen Studio 账号邮箱 | - |
| `QWEN_PASSWORD` | Qwen Studio 明文密码；程序登录前会做 SHA256 哈希 | - |
| `API_KEY` | 客户端认证密钥；对外监听时必须改成强随机值 | `sk-qwen-studio-123456` |
| `RUN_MODE` | 运行模式：`stateless` \| `stateful` | `stateful` |
| `PORT` | 服务端口 | `8000` |
| `HOST` | 监听地址 | `127.0.0.1` |
| `CORS_ALLOW_ORIGINS` | 浏览器跨域来源白名单，逗号分隔；为空时不启用 CORS 中间件 | - |

## 构建与发布

### 本地构建发布包

```bash
pip install -U pip
pip install -U build twine
python -m build
python -m twine check dist/*
```

### 发布前推荐做的完整校验

```bash
bash scripts/release_check.sh
```

当 `main` 上的代码已经准备好发布，并且你推送了和 `pyproject.toml` 版本一致的 `v*` tag 之后，GitHub Actions 会自动：

- 跑测试
- 执行打包校验
- 创建 GitHub Release
- 上传 `wheel` 和 `sdist` 到 Release 附件

例如当前版本是 `1.0.0`，对应 tag 应该是 `v1.0.0`。

更完整的发版步骤，以及"旧 tag 不会自动补触发 release"的补救方式，见 [docs/release-runbook.md](docs/release-runbook.md)。

## 测试

```bash
pytest -q

# 运行单个测试
pytest tests/test_api.py::test_new_command_non_stream -v

# 带覆盖率测试需要额外安装 pytest-cov
pip install pytest-cov
pytest tests/ -v --cov=qwen_gateway
```

## 安全说明

- 这个工具会处理高敏感度账号凭证，只建议在本机运行
- 默认监听 `127.0.0.1`，不要在未设置强 `API_KEY` 时绑定 `0.0.0.0`
- 不要把它直接部署到公网
- 不要把真实密码、API_KEY 提交到 Git 仓库、Issue、日志或截图中
- 只有在需要浏览器页面跨域调用时才设置 `CORS_ALLOW_ORIGINS`

如果你发现了安全问题，请不要直接在公开 Issue 里贴真实凭证或可复用的敏感数据。

## 发布边界

- 当前发布链路聚焦 GitHub Releases，不自动发布到公共 PyPI
- Docker 镜像发布暂不支持

## 社区与贡献

- 贡献代码或文档前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)
- 报告安全问题前请阅读 [SECURITY.md](SECURITY.md)
- 获取帮助请阅读 [SUPPORT.md](SUPPORT.md)
- 社区行为准则见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 版本变更记录见 [CHANGELOG.md](CHANGELOG.md)

## 技术架构

**模块化架构** (`src/qwen_gateway/`):

| 模块 | 说明 |
|------|------|
| `browser.py` | `AsyncPlaywrightManager` - 无头浏览器抓取风控令牌 (`bx-ua`, `bx-umidtoken`)，25 分钟自动刷新 |
| `client.py` | `AsyncQwenClient` - 封装 Qwen 官方 API 交互，管理登录、会话创建、流式对话 |
| `settings.py` | 运行时配置 - 读取 `.env`/环境变量，校验运行模式、端口、监听地址和公网暴露风险 |
| `routes.py` | HTTP 路由定义 - `/health`, `/v1/models`, `/v1/chat/completions`，处理鉴权、请求校验和上游错误 |
| `schemas.py` | Pydantic 数据模型 - `Message`, `ChatCompletionReq` |
| `cli.py` | CLI 入口 - `--mode`, `--port`, `--host`, `--reload` 参数 |
| `app.py` | FastAPI 应用 - lifespan 初始化和关闭客户端，注册路由和可选 CORS 中间件 |

**核心依赖**:

| 依赖 | 用途 |
|------|------|
| FastAPI | 异步 Web 框架 |
| Playwright | 无头浏览器自动化，获取风控令牌 |
| httpx | 异步 HTTP 客户端 |
| Pydantic v2 | 数据验证 |
| uvicorn | ASGI 服务器 |
| asyncio.Lock | 并发安全保护 |

## 开源协议

本项目使用 [MIT License](LICENSE)。
