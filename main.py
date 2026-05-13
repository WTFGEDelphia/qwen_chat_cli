#!/usr/bin/env python3
"""
Qwen API Server - /new 命令优化版
支持 stateless/stateful 双模式，兼容流式/非流式响应，安全处理多模态内容
"""

import os
import sys
import time
import uuid
import json
import hashlib
import asyncio
import logging
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator, Union

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal

import httpx
from playwright.async_api import async_playwright, Request as PwRequest

# ==============================================================================
# 0. 参数解析与环境配置
# ==============================================================================
parser = argparse.ArgumentParser(description="Qwen API Gateway with /new command")
parser.add_argument("--mode", type=str, choices=["stateless", "stateful"], default="stateful",
                    help="运行模式：stateless(无状态，拼接历史), stateful(有状态，后台单会话)")
parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="监听端口")
args, unknown = parser.parse_known_args()

RUN_MODE = args.mode
PORT = args.port

QWEN_EMAIL = os.getenv("QWEN_EMAIL", "your_email@gmail.com")
QWEN_PASSWORD = os.getenv("QWEN_PASSWORD", "your_password")
API_KEY = os.getenv("API_KEY", "sk-qwen-studio-123456")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("QwenServer")


# ==============================================================================
# 1. Pydantic 模型定义 (Pydantic v2 兼容)
# ==============================================================================
class MessageContent(BaseModel):
    """多模态内容项"""
    type: str
    text: Optional[str] = None


class Message(BaseModel):
    """对话消息模型"""
    role: str
    content: Union[str, List[Dict[str, Any]]]


class ChatCompletionReq(BaseModel):
    """对话请求模型"""
    model: str = "qwen3.6-plus"
    messages: List[Message]
    stream: bool = False


# ==============================================================================
# 2. 异步风控管理器 (Playwright 令牌抓取)
# ==============================================================================
class AsyncPlaywrightManager:
    """异步风控令牌管理器 - 使用 Playwright 获取 bx-ua 和 bx-umidtoken"""

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    # 保底令牌（当抓取失败时使用）
    FALLBACK_UA = "231!DZA3j4mUfW4+j+oAFo2jZk8FEl2ZWfPwIPF92lBLek2KxVW/XJ2EwruCiDOX5b/I+quD3qBnFMKtmWiGAG/srKz9mnlnpaRiDsJMoqvGGy+FQX1Zr34G/4jDU06bY8PEmXuzvng+zV1BKc6OP2U5E/AE+oUjTOQUU1K78Fnk7eKHddhRGrgXYA+r+/Mep4Dqk+I9xGdFt9ytKHlCok+++4mWYi++6bFEjpc0rUGDj+8LwG3lUWsSB0pqLcaMPviJZK5gS3VxZuQnMoK+3V6//TR7fAOJs7vbFZXiwWZr25yu3ulMHHv1tw8f4LHtpSKK+FLgqn9CI7/D8aNtE//Fsi658Nbn0y620M2YlUa5I4e/Pa35WtGsYKWoZMceHgxPs+kaUergcvcqxU4zPjR4W3iqkAsFFE3jO43sK8iEyEDhRorsD+DLNlRr9q37/x/sDgW/F6suOHQt6dv1nQJwvGEZffKgf+XX5RO/3WDee2ImQB11+431mMvyCCbl5HPONAN1qge5UjnpT+r0PJ3wYjc6cSoSXQv1906aD6N1W0il70uWYzWsqoy5eFvR/jNHgORahVLL7czdToocn6l/QVZ19sdqxH0uR7Ez/bjZWmpBcyQshQN4SOf8p4Zj77iDzi1tsXBKptZBrlM+VXo78ytMr0DbC1Dcbv0iqlvpBojsOhIrr0KNT6vhuxeOH2y/2yFmwgN7bSv0bLicTANq8WwBv26FEuBK1onSA3YcR2PAA8bLN5Pfk/Hbli/BzOA35ZwhyXuOlPHZKxY+67aDz7x+JaO3v1fZyExrvznG0CaM+QIGnSWKW90dQivUB01CbdeC+kS34OzyiXVKWUBJI+SYJBnR0alG6JCqYs0O8ZC6934uvG33h8dHChXr3QiATjJUd/103yzoso5o+uQQP8QVhtGjD+84CxYGrEl+kvdk/foeLSHUVeG9x5fkfbqpGZ7UdIcI7YD7tEUlgdY9lR2NVU5zGUc4V19F8WLhsCTE7UH9rDzg7KqXBgI5rzBq2lxrAHpTMzg4IVzC4327PRoOjIyNmUFTvo9pdW6zI8n1CCBSAow/PESgs2UYcNrP+A3Ny1qBjpPOp7PzIF2KLNs0HmtvaWbnlTodOOc5bM4xEoxvGD2JYADjCCCTKjqJmoR+X2yAGrpNAJynYO7mMifPBI0oKzymmRI3+PnH/MjvPy+lNyJaiXqnmMLU/fPQSuB+815fUuVXUeUe2G9Mf7GuUHFlM7JtPst30gG8ay1a8C24HL9CjkV5GOk0777VI3opxHrPwKh8QJWlMsLjnRS25+MA1SuiWF2/y/6uKBwZ9WgQjIJQzpqRhqjrXBmnzRAXWZftA3ImflI3ZR0SAq+maHo"
    FALLBACK_UMID = "T2gAjE9z7cERJjDt1EtsNKIOHVosD-h0sHZrpPGly1vzfOJnLNAor9E_6M96EKi6bp0="

    def __init__(self):
        self._lock = asyncio.Lock()
        self._bx_ua = None
        self._bx_umid = None
        self._last_refresh = 0.0

    async def get_tokens(self) -> tuple[str, str]:
        """获取风控令牌，25 分钟刷新一次"""
        if time.time() - self._last_refresh > 1500:
            async with self._lock:
                if time.time() - self._last_refresh > 1500:
                    await self._refresh_tokens_from_browser()
        return self._bx_ua or self.FALLBACK_UA, self._bx_umid or self.FALLBACK_UMID

    async def _refresh_tokens_from_browser(self):
        """通过 Playwright 无头浏览器获取动态风控令牌"""
        logger.info("启动无头浏览器获取动态风控令牌...")
        captured_ua, captured_umid = None, None

        async def handle_request(request: PwRequest):
            nonlocal captured_ua, captured_umid
            headers = request.headers
            if 'bx-ua' in headers:
                captured_ua = headers['bx-ua']
            if 'bx-umidtoken' in headers:
                captured_umid = headers['bx-umidtoken']

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox'
                    ]
                )
                context = await browser.new_context(user_agent=self.USER_AGENT)
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
                page = await context.new_page()
                page.on("request", handle_request)

                try:
                    await page.goto(
                        "https://chat.qwen.ai/",
                        wait_until="domcontentloaded",
                        timeout=12000
                    )
                    await page.mouse.move(100, 100)
                    await asyncio.sleep(0.5)
                    await page.evaluate(
                        "() => { fetch('/api/v2/auths/signin', { method: 'POST', body: '{}' }).catch(e => {}); }"
                    )
                except Exception as e:
                    logger.warning(f"页面加载异常：{e}")

                for _ in range(24):
                    if captured_ua:
                        break
                    await asyncio.sleep(0.5)

                if captured_ua:
                    self._bx_ua, self._bx_umid = captured_ua, captured_umid
                    logger.info("动态风控令牌获取成功！")
                else:
                    logger.warning("风控抓取超时，启用保底令牌策略。")

                self._last_refresh = time.time()
        except Exception as e:
            logger.error(f"浏览器异常：{e}")
            self._last_refresh = time.time()


# ==============================================================================
# 3. Qwen 核心客户端
# ==============================================================================
class AsyncQwenClient:
    """Qwen API 客户端 - 封装所有与通义千问 API 的交互"""

    BASE_URL = "https://chat.qwen.ai"

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token = None
        self.http_client = httpx.AsyncClient(timeout=120.0)

        # Stateful 模式缓存
        self.active_chat_id = None
        self.active_parent_id = None
        self.session_lock = asyncio.Lock()

    async def _get_headers(self) -> dict:
        """获取请求头，包含风控令牌和认证信息"""
        bx_ua, bx_umid = await pm.get_tokens()
        headers = {
            "x-request-id": str(uuid.uuid4()),
            "bx-umidtoken": bx_umid,
            "bx-ua": bx_ua,
            "accept": "text/event-stream",
            "content-type": "application/json",
            "referer": "https://chat.qwen.ai/",
            "user-agent": pm.USER_AGENT
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def login(self) -> bool:
        """登录 Qwen 并获取认证 token"""
        pwd_hash = hashlib.sha256(self.password.encode()).hexdigest()
        headers = await self._get_headers()
        try:
            resp = await self.http_client.post(
                f"{self.BASE_URL}/api/v2/auths/signin",
                headers=headers,
                json={"email": self.email, "password": pwd_hash}
            )
            if resp.status_code == 200:
                self.token = resp.cookies.get("token")
                return True if self.token else False
            return False
        except Exception as e:
            logger.error(f"登录失败：{e}")
            return False

    async def create_new_chat(self) -> Optional[str]:
        """创建新会话，返回 chat_id"""
        headers = await self._get_headers()
        try:
            resp = await self.http_client.post(
                f"{self.BASE_URL}/api/v2/chats/new",
                headers=headers,
                json={}
            )
            if resp.status_code == 200:
                return resp.json().get('data', {}).get('id')
        except Exception as e:
            logger.error(f"创建会话失败：{e}")
        return None

    async def stream_chat(
        self,
        prompt: str,
        model: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式对话 - 返回 SSE 格式的生成结果"""
        # 创建或获取 chat_id
        if RUN_MODE == "stateful":
            if not self.active_chat_id:
                async with self.session_lock:
                    if not self.active_chat_id:
                        self.active_chat_id = await self.create_new_chat()
            chat_id, parent_id = self.active_chat_id, self.active_parent_id
        else:
            chat_id = await self.create_new_chat()
            parent_id = None

        if not chat_id:
            yield {"error": "无法建立官方底层会话"}
            return

        headers = await self._get_headers()
        timestamp = int(time.time())

        payload = {
            "stream": True,
            "version": "2.1",
            "incremental_output": True,
            "chat_id": chat_id,
            "chat_mode": "normal",
            "model": model,
            "parent_id": parent_id,
            "messages": [{
                "fid": str(uuid.uuid4()),
                "parentId": parent_id,
                "childrenIds": [str(uuid.uuid4())],
                "role": "user",
                "content": prompt,
                "user_action": "chat",
                "files": [],
                "timestamp": timestamp,
                "models": [model],
                "chat_type": "t2t",
                "feature_config": {
                    "thinking_enabled": True,
                    "output_schema": "phase",
                    "auto_thinking": True,
                    "thinking_mode": "Auto",
                    "thinking_format": "summary",
                    "auto_search": True,
                    "mcp_tools": ["code-interpreter"]
                },
                "sub_chat_type": "t2t"
            }],
            "timestamp": timestamp
        }

        try:
            async with self.http_client.stream(
                "POST",
                f"{self.BASE_URL}/api/v2/chat/completions?chat_id={chat_id}",
                headers=headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    yield {"error": f"Qwen 官方拒绝：{response.status_code}"}
                    return

                async for line in response.aiter_lines():
                    if not line or not line.startswith('data:'):
                        continue
                    data_str = line.split('data:', 1)[1].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        data = json.loads(data_str)
                        if RUN_MODE == "stateful":
                            if "response.created" in data:
                                self.active_parent_id = data["response.created"].get("response_id")
                            elif "response_id" in data:
                                self.active_parent_id = data.get("response_id")

                        if 'choices' in data:
                            delta = data['choices'][0].get('delta', {})
                            yield {
                                "phase": delta.get('phase', ''),
                                "content": delta.get('content', '')
                            }
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            yield {"error": str(e)}

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.http_client.aclose()


# ==============================================================================
# 4. 全局实例初始化
# ==============================================================================
pm = AsyncPlaywrightManager()
qwen_client = AsyncQwenClient(QWEN_EMAIL, QWEN_PASSWORD)


# ==============================================================================
# 5. FastAPI 应用配置
# ==============================================================================
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info(f"Qwen API Gateway 启动... 模式：[{RUN_MODE.upper()}]")

    if not await qwen_client.login():
        logger.error("启动登录失败，请检查账号密码配置！")
    else:
        logger.info("登录成功")

    if RUN_MODE == "stateful":
        chat_id = await qwen_client.create_new_chat()
        if chat_id:
            qwen_client.active_chat_id = chat_id
            logger.info(f"创建初始会话：{chat_id[:8]}...")

    yield

    await qwen_client.close()
    logger.info("服务已关闭")


app = FastAPI(
    title="Qwen API Gateway",
    version="3.1-new-command",
    description="支持 /new 命令的 Qwen Studio  API 网关",
    lifespan=lifespan
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# 认证
security = HTTPBearer()


async def verify_key(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """验证 API Key"""
    if credentials.credentials != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")


# ==============================================================================
# 6. API 路由
# ==============================================================================
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "mode": RUN_MODE}


@app.get("/v1/models", dependencies=[Depends(verify_key)])
async def list_models():
    """返回可用模型列表"""
    return {
        "object": "list",
        "data": [
            {
                "id": "qwen3.6-plus",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "qwen"
            },
            {
                "id": "qwen3.5-plus",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "qwen"
            }
        ]
    }


def extract_message_text(content: Union[str, List[Dict[str, Any]]]) -> str:
    """
    安全提取消息文本内容

    兼容多模态格式:
    - 字符串："hello"
    - 列表：[{"type": "text", "text": "hello"}, {"type": "image", ...}]
    """
    if isinstance(content, str):
        return content.strip()
    elif isinstance(content, list):
        # 提取所有 text 类型的内容
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        return " ".join(text_parts).strip()
    else:
        return str(content).strip()


@app.post("/v1/chat/completions", dependencies=[Depends(verify_key)])
async def chat_completions(req: ChatCompletionReq):
    """
    对话接口（兼容 OpenAI 格式）

    特殊命令支持:
    - /new: stateful 模式下创建新会话，清除上下文

    运行模式:
    - stateless: 拼接所有消息为 single prompt（兼容第三方客户端）
    - stateful: 只发送最新消息（官方维护上下文）
    """
    # ====== 1. 统一生成通用属性 (DRY 原则) ======
    req_id = f"chatcmpl-{uuid.uuid4()}"
    created_time = int(time.time())
    # ==========================================

    # ====== 2. 安全提取最后一条消息文本 ======
    last_message_content = req.messages[-1].content if req.messages else ""
    last_text = extract_message_text(last_message_content)
    # =======================================

    # ====== 3. 特殊命令拦截处理 ======
    if last_text == "/new":
        logger.info("收到 /new 命令，创建新会话...")

        if RUN_MODE == "stateful" and qwen_client:
            # 使用锁保护全局状态修改
            async with qwen_client.session_lock:
                new_chat_id = await qwen_client.create_new_chat()
                if new_chat_id:
                    qwen_client.active_chat_id = new_chat_id
                    qwen_client.active_parent_id = None
                    logger.info(f"新会话创建：{new_chat_id[:8]}...")

            reply_text = "已创建新会话！之前的上下文已清除。"
        else:
            reply_text = (
                "当前为 stateless 模式，每次请求都是独立会话，"
                "无需手动创建新会话。"
            )

        # 根据客户端请求类型返回对应协议格式
        if req.stream:
            # 流式请求：返回 SSE 格式
            async def fake_stream():
                openai_chunk = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created_time,
                    "model": req.model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": reply_text}
                    }]
                }
                yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                fake_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive"
                }
            )
        else:
            # 非流式请求：返回 JSON
            return JSONResponse({
                "id": req_id,
                "object": "chat.completion",
                "created": created_time,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": reply_text
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            })
    # ==================================

    # ====== 4. 原有对话逻辑 ======
    # 拼装 prompt
    if RUN_MODE == "stateless":
        formatted_prompt = ""
        for msg in req.messages[:-1]:
            content_str = extract_message_text(msg.content)
            formatted_prompt += f"[{msg.role}]: {content_str}\n\n"
        formatted_prompt += f"[{req.messages[-1].role}]: {last_text}"
    else:
        formatted_prompt = last_text

    async def stream_generator():
        """SSE 流式生成器"""
        is_thinking = False

        async for chunk in qwen_client.stream_chat(formatted_prompt, req.model):
            if "error" in chunk:
                yield f"data: {json.dumps({'error': {'message': chunk['error'], 'type': 'server_error'}})}\n\n"
                break

            content = chunk.get("content", "")
            phase = chunk.get("phase", "")
            if not content:
                continue

            # 智能封装深度思考流程
            out_str = ""
            if phase == "thinking_summary":
                if not is_thinking:
                    out_str += "<think>\n"
                    is_thinking = True
                out_str += content
            else:
                if is_thinking:
                    out_str += "\n</think>\n\n"
                    is_thinking = False
                out_str += content

            openai_chunk = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created_time,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": out_str}
                }]
            }
            yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"

        # 确保标签闭合
        if is_thinking:
            yield f"data: {json.dumps({'choices': [{'delta': {'content': '\n</think>\n\n'}}]})}\n\n"

        yield "data: [DONE]\n\n"

    if req.stream:
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
    else:
        # 非流式：收集完整响应
        full_text = ""
        async for chunk in stream_generator():
            if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
                try:
                    data = json.loads(chunk[6:])
                    if "choices" in data:
                        full_text += data["choices"][0]["delta"].get("content", "")
                except json.JSONDecodeError:
                    pass

        return JSONResponse({
            "id": req_id,
            "object": "chat.completion",
            "created": created_time,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": full_text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        })


# ==============================================================================
# 7. 主程序入口
# ==============================================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False
    )
