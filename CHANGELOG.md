# 变更日志

本项目遵循面向用户可读的变更记录。发布版本以 GitHub Releases 为准，Release Notes 会由 GitHub Actions 基于 tag 自动生成。

## 未发布

- 补充开源社区健康文档、Issue 模板和 PR 模板。
- 更新 `README.md` 的本地开发、API Key 示例和发布说明。

## 1.0.0

- 提供兼容 OpenAI API 格式的 Qwen Studio 本地网关。
- 支持 `stateless` 和 `stateful` 两种运行模式。
- 支持 `/new` 命令重置 stateful 会话。
- 支持流式和非流式响应。
- 支持 GitHub Release 自动构建并上传 wheel 与 sdist。
