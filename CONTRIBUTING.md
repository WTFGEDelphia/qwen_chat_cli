# 贡献指南

感谢你愿意为 `qwen-gateway` 贡献代码、文档或问题反馈。

## 开始之前

- 这个项目会处理 Qwen Studio 账号、明文密码、登录态、风控令牌和本地 API Key，请不要在提交、Issue、PR、测试样例、截图或日志里放入真实凭证。
- 项目默认面向本机使用，默认监听 `127.0.0.1`。除非有明确安全设计和文档说明，不要把默认监听地址改成 `0.0.0.0`。
- 本项目与通义千问无官方关联，也不适合直接部署到公网。
- 当前要求 Python 3.10 或更高版本。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[dev]'
playwright install chromium
cp .env.example .env
```

编辑 `.env`，填写 `QWEN_EMAIL`、`QWEN_PASSWORD`，并把 `API_KEY` 改成强随机值。

启动本地服务：

```bash
python -m qwen_gateway --mode stateful --host 127.0.0.1 --port 8000
```

或使用安装后的命令：

```bash
qwen-gateway --mode stateful --host 127.0.0.1 --port 8000
```

## 提交前检查

至少运行：

```bash
pytest -q
```

如果你的改动涉及打包、依赖、CLI、GitHub Actions、发布文档或包内容，请额外运行：

```bash
bash scripts/release_check.sh
```

## Pull Request 建议

- 说明改动背景、范围和验证方式。
- 如果改动影响公开使用方式，请同步更新 `README.md` 或 `docs/`。
- 如果改动影响安全边界，例如鉴权、默认监听地址、CORS、账号凭证处理或公网暴露风险，请在 PR 中明确说明。
- 尽量把重构和行为修改拆开，方便审阅。
- 不要把构建产物、虚拟环境、真实 `.env` 或本地 worktree 提交到仓库。

## 发布相关

当前发布链路聚焦 GitHub Releases，不自动发布到公共 PyPI。发版前请参考 [docs/release-runbook.md](docs/release-runbook.md)，并确保：

- `pyproject.toml` 中的版本号已经更新。
- `pytest -q` 通过。
- `bash scripts/release_check.sh` 通过。
- 推送的 `v*` tag 与 `pyproject.toml` 版本一致。

## 讨论与安全

- 普通功能建议或缺陷报告可以直接提 Issue。
- 涉及凭证泄漏、鉴权绕过、敏感日志、CORS 暴露、错误公网监听或可复用攻击细节的问题，请先阅读 [SECURITY.md](SECURITY.md)。
