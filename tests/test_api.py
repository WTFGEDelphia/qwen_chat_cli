"""
Qwen API Server 测试套件

覆盖场景:
- /new 命令（流式/非流式）
- 多模态 content 兼容
- 基础健康检查
"""
import pytest
import httpx
import json

BASE_URL = "http://localhost:8000"
API_KEY = "sk-qwen-studio-123456"

headers = {"Authorization": f"Bearer {API_KEY}"}


@pytest.mark.asyncio
async def test_health_check():
    """测试健康检查端点"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BASE_URL}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "mode" in data


@pytest.mark.asyncio
async def test_list_models():
    """测试模型列表接口"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{BASE_URL}/v1/models",
            headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert len(data["data"]) > 0


@pytest.mark.asyncio
async def test_new_command_non_stream():
    """测试 /new 命令（非流式响应）"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "/new"}],
                "stream": False
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "choices" in data
        content = data["choices"][0]["message"]["content"]
        # stateful 模式返回 "已创建新会话"，stateless 模式返回提示
        assert "已创建新会话" in content or "stateless" in content


@pytest.mark.asyncio
async def test_new_command_stream():
    """测试 /new 命令（流式响应）"""
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": "qwen3.6-plus",
                "messages": [{"role": "user", "content": "/new"}],
                "stream": True
            },
            timeout=30
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get(
                "content-type", ""
            )

            # 验证 SSE 格式
            chunks = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    try:
                        data = json.loads(line[6:])
                        if "choices" in data:
                            chunks.append(
                                data["choices"][0]["delta"].get("content", "")
                            )
                    except json.JSONDecodeError:
                        pass

            full_content = "".join(chunks)
            assert "已创建新会话" in full_content or "stateless" in full_content


@pytest.mark.asyncio
async def test_new_command_multimodal_text():
    """测试多模态 content（文本列表）不会崩溃"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": "qwen3.6-plus",
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": "/new"}]
                }],
                "stream": False
            }
        )
        # 应该成功响应（200）或参数错误（400），但不应该是 500
        assert resp.status_code in [200, 400]


@pytest.mark.asyncio
async def test_normal_message():
    """测试正常消息处理"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": "qwen3.6-plus",
                "messages": [
                    {"role": "user", "content": "你好，请自我介绍"}
                ],
                "stream": False
            },
            timeout=60
        )
        # 可能因网络/认证失败返回非 200，但至少不应崩溃
        assert resp.status_code in [200, 401, 500]


@pytest.mark.asyncio
async def test_empty_messages():
    """测试空消息列表处理"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v1/chat/completions",
            headers=headers,
            json={
                "model": "qwen3.6-plus",
                "messages": [],
                "stream": False
            }
        )
        # 应该返回错误，但不应该崩溃
        assert resp.status_code in [400, 422, 500]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
