"""
企微回调服务器 — 接收企微自建应用推送的消息
===========================================
用法：python callback_server.py  →  监听 8003 端口
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="POS Agent 回调")

# ── 企微自建应用参数（从环境变量读取）──
CORPID = os.getenv("WEWORK_CORPID", "")
AGENTID = os.getenv("WEWORK_AGENTID", "")
APPSECRET = os.getenv("WEWORK_APPSECRET", "")


@app.get("/callback", response_class=PlainTextResponse)
async def verify_callback(request: Request):
    """企微首次配置回调时验证——直接用 echoStr
    返回 echo 给企微，企微认为服务器在。"""
    params = request.query_params
    echo = params.get("echostr", "ok")
    logger.info(f"回调验证请求: {echo[:20]}...")
    return PlainTextResponse(echo)


if __name__ == "__main__":
    import uvicorn
    logger.info("Agent 回调服务器启动: http://0.0.0.0:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)
