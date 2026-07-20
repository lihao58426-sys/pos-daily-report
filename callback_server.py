"""
企微回调服务器 — 接收企微自建应用推送的消息
===========================================
用法：python callback_server.py  →  监听 8003 端口
"""
import logging
import os
import xml.etree.ElementTree as ET

import requests
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

# access_token 缓存（有效期 2 小时，到期自动刷新）
_access_token: dict = {"value": "", "expires_at": 0}


def _get_access_token() -> str:
    """获取企微 API 的 access_token（自动缓存）"""
    import time
    now = time.time()
    if _access_token["value"] and now < _access_token["expires_at"]:
        return _access_token["value"]

    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORPID}&corpsecret={APPSECRET}"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if data.get("errcode") == 0:
        _access_token["value"] = data["access_token"]
        _access_token["expires_at"] = now + data["expires_in"] - 300
        logger.info("access_token 已刷新")
        return _access_token["value"]
    else:
        logger.error(f"获取 access_token 失败: {data}")
        return ""


def _send_reply(to_user: str, text: str) -> bool:
    """通过企微 API 回复消息给指定用户"""
    token = _get_access_token()
    if not token:
        return False
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = {
        "touser": to_user,
        "msgtype": "text",
        "agentid": int(AGENTID) if AGENTID else 0,
        "text": {"content": text},
    }
    resp = requests.post(url, json=body, timeout=10)
    ok = resp.json().get("errcode") == 0
    logger.info(f"回复{'成功' if ok else '失败'}: {text[:50]}...")
    return ok


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
    # 企微 XML 可能是 UTF-8 或 GBK，优先 UTF-8，失败回退 GBK
    try:
        xml_text = body.decode("utf-8")
    except UnicodeDecodeError:
        xml_text = body.decode("gbk")
    logger.info(f"收到企微消息: {xml_text[:200]}")

    try:
        root = ET.fromstring(xml_text)
        msg_type = root.findtext("MsgType", "unknown")
        content = root.findtext("Content", "")
        from_user = root.findtext("FromUserName", "")
        logger.info(f"消息类型: {msg_type} | 来自: {from_user} | 内容: {content}")

        if msg_type == "text" and content:
            logger.info("Agent 思考中...")
            try:
                answer = run_agent(content)
                logger.info(f"Agent 回复: {answer[:200]}")
                _send_reply(from_user, answer)
            except Exception as agent_err:
                logger.error(f"Agent 处理失败: {agent_err}")
                _send_reply(from_user, "抱歉，暂时无法处理您的问题，请稍后再试。")

        return PlainTextResponse("")

    except ET.ParseError as e:
        logger.error(f"XML 解析失败: {e}")
        return PlainTextResponse("")
    except Exception as e:
        logger.error(f"回调处理异常: {e}")
        return PlainTextResponse("")


if __name__ == "__main__":
    import uvicorn
    logger.info("Agent 回调服务器启动: http://0.0.0.0:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)
