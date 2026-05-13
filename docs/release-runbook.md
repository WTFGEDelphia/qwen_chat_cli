# Release Runbook

## 目标

用最少的手工步骤产出一个公开 GitHub Release，并确保：

- `pytest` 通过
- `wheel` 与 `sdist` 都能构建
- Release 附件可被 `pip install`
- 安装后可以直接运行 `qwen-gateway`

## 前置条件

- 你对仓库有 push / tag 权限
- `gh auth status` 已登录
- 当前工作区是你准备发版的 commit
- `pyproject.toml` 里的 `version` 已更新到目标版本
- 默认分支上的 CI 最近一次通过

## 1. 本地验收

```bash
python -m pip install -U pip
python -m pip install -e '.[dev]'
pytest -q
bash scripts/release_check.sh
```

## 2. 推送主分支与版本 tag

```bash
git checkout main
git pull --ff-only
pytest -q
bash scripts/release_check.sh
git status --short
git tag v1.0.0
git push origin main
git push origin v1.0.0
```

推送 `v1.0.0` 后，GitHub Actions 的 `Release` workflow 会自动校验 tag 与 `pyproject.toml` 版本一致，运行测试和打包检查，创建 GitHub Release，并上传 wheel 与 sdist。

注意：

- 这个自动发布能力只对"工作流已经合并到默认分支之后的新 tag 推送事件"生效
- 如果 `v1.0.0` 是在加入 `release.yml` 之前就已经推上去的，GitHub 不会自动补触发历史事件

## 3. 检查自动发布结果

```bash
gh run list --workflow Release --limit 5
gh release view v1.0.0
```

确认 Release 页面里已经带上：

- `qwen_gateway-1.0.0.tar.gz`
- `qwen_gateway-1.0.0-py3-none-any.whl`

## 4. 旧 tag 的补发方式

如果某个 tag 早于自动发布工作流，任选一种方式补发：

### 方式 A：直接手工创建 Release

```bash
bash scripts/release_check.sh
gh release create v1.0.0 dist/* --generate-notes --latest
```

### 方式 B：删除并重新推送同名 tag

只建议在该 tag 还没有被其他下游广泛消费时使用。

```bash
git tag -d v1.0.0
git push origin :refs/tags/v1.0.0
git tag v1.0.0
git push origin v1.0.0
```

## 5. GitHub 源码安装验证

```bash
python -m pip install "qwen-gateway @ git+https://github.com/YOUR_REPO/qwen_chat_cli.git@v1.0.0"
qwen-gateway --host 127.0.0.1 --port 8000
```

如果需要局域网访问，再单独验证：

```bash
API_KEY=sk-your-strong-random-secret qwen-gateway --host 0.0.0.0 --port 8000
```

## 6. wheel 安装验证

```bash
python -m pip install ./dist/qwen_gateway-1.0.0-py3-none-any.whl
qwen-gateway --host 127.0.0.1 --port 8000
```

## 7. 这版计划刻意不做的事

- 不发布到公共 PyPI
- 不引入 Docker 镜像发布
- 默认只监听 `127.0.0.1`，允许在设置强 `API_KEY` 后显式使用 `--host 0.0.0.0`
