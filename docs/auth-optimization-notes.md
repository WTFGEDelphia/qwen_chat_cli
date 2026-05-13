# 认证方式优化说明

## 变更概述

本次优化基于真实浏览器请求分析，修正了 Qwen 官方 API 的认证方式。

## 主要变更

### 1. 移除多余请求头

以下请求头已被移除（浏览器实际请求中不存在）:
- `bx-ua`
- `bx-umidtoken`
- `Authorization: Bearer`

### 2. 添加必需请求头

以下请求头已添加（浏览器实际请求中包含）:
- `bx-v: 2.5.36`
- `version: 0.2.50`
- `source: web`

### 3. Cookie 认证

使用 httpx 的 CookieJar 自动管理所有认证 Cookie:
- `tfstk` - 核心认证令牌
- `isg` - 签名验证
- `cna` - 用户标识
- `token` - 会话令牌

## 验证报告

详细验证报告见：`docs/bx-ua-verification-report.md`

## 兼容性

此变更为破坏性更新，需要更新所有依赖此网关的客户端配置。
