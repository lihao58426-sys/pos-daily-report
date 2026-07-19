"""
企微回调服务器 — 接收企微自建应用推送的消息
===========================================
用法：python callback_server.py  →  监听 8003 端口
"""
import logging
import os
import xml.etree.ElementTree as ET

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="POS Agent 回调")

# ── 企微自建应用参数（从环境变量读取）──
CORPID = os.getenv("WEWORK_CORPID", "")
AGENTID = os.getenv("WEWORK_AGENTID", "")
APPSECRET = os.getenv("WEWORK_APPSECRET", "")


@app.get("/callback", response_class=PlainTextResponse)
async def verify_callback(request: Request):
    """企微首次配置回调时验证——原样返回 echostr"""
    params = request.query_params
    echo = params.get("echostr", "ok")
    logger.info(f"回调验证请求: {echo[:20]}...")
    return PlainTextResponse(echo)


@app.post("/callback")
async def receive_message(request: Request):
    """接收企微推送的消息——解析 XML，提取内容和发送人"""
    body = await request.body()
    xml_text = body.decode("utf-8")
    logger.info(f"收到企微消息: {xml_text[:200]}")

    try:
        root = ET.fromstring(xml_text)
        msg_type = root.findtext("MsgType", "unknown")
        content = root.findtext("Content", "")
        from_user = root.findtext("FromUserName", "")
        logger.info(f"消息类型: {msg_type} | 来自: {from_user} | 内容: {content}")

        if msg_type == "text" and content:
            logger.info("Agent 思考中...")
            answer = run_agent(content)
            logger.info(f"Agent 回复: {answer[:200]}")

        # 先不回——C4 加企微发送功能
        return PlainTextResponse("")

    except ET.ParseError as e:
        logger.error(f"XML 解析失败: {e}")
        return PlainTextResponse("")


if __name__ == "__main__":
    import uvicorn
    logger.info("Agent 回调服务器启动: http://0.0.0.0:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)
