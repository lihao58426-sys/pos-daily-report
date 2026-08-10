"""
企微回调服务器 — 接收企微自建应用推送的消息，调 Agent 处理后回复
============================================================

数据流：
  企微用户发消息 → 企微服务器 POST XML 到 /callback
    → 解析 XML（UTF-8 优先，失败回退 GBK）
      → 提取文本内容 → run_agent(content) → 拿到回复
        → _get_access_token()（含 5 分钟过期缓冲缓存）
          → _send_reply() → 企微 API → 用户收到回复

两条路由：
  GET  /callback  — 企微首次配置回调 URL 时验证（原样返回 echostr）
  POST /callback  — 接收消息 + 调 Agent + 回复
  GET  /health    — 健康检查（负载均衡/监控用）

用法：
  python callback_server.py  →  监听 0.0.0.0:8003
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

@app.get("/health")
async def health_check():
    """健康检查——给 Docker/负载均衡用，确认服务还活着"""
    return {"status": "ok"}

# ── 企微自建应用参数（全部从环境变量读取，不进 git）──
CORPID = os.getenv("WEWORK_CORPID", "")       # 企业 ID——在企微管理后台"我的企业"里找
AGENTID = os.getenv("WEWORK_AGENTID", "")     # 自建应用 AgentId
APPSECRET = os.getenv("WEWORK_APPSECRET", "") # 自建应用 Secret——用来换 access_token

# access_token 缓存
#   - 有效期 2 小时（企微 API 返回 expires_in 字段）
#   - 提前 300 秒（5 分钟）刷新——防止"令牌在请求中途过期"的边界情况
#   - 不缓存的话：每条消息多等一次 HTTP 往返（~500ms）+ 可能触发企微频率限制
_access_token: dict = {"value": "", "expires_at": 0}


def _get_access_token() -> str:
    """获取企微 API 的 access_token——含 5 分钟过期缓冲的内存缓存

    为什么需要 access_token：
      企微所有 API 调用都要带 access_token 做身份验证，类似"临时门禁卡"。
      没有它 → 企微拒绝所有 API 请求。

    为什么要缓存：
      1. 延迟——获取 access_token 是一次 HTTP 往返，200-500ms。
         每条消息都重新获取 → 用户等回复多等半秒。
      2. 频率限制——企微对 /gettoken 接口有每日调用上限。
         每条消息都刷新 → 高流量时可能被限流。
      3. 过期缓冲——提前 5 分钟刷新，不是等到刚好过期。
         防止"拿到的 token 在请求中途就过期了"这种边界情况。
    """
    import time
    now = time.time()
    # 缓存未过期 → 直接复用
    if _access_token["value"] and now < _access_token["expires_at"]:
        return _access_token["value"]

    # 缓存过期 → 重新获取
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CORPID}&corpsecret={APPSECRET}"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    if data.get("errcode") == 0:
        _access_token["value"] = data["access_token"]
        # 提前 300 秒刷新——不等到刚好 7200 秒过期
        _access_token["expires_at"] = now + data["expires_in"] - 300
        logger.info("access_token 已刷新")
        return _access_token["value"]
    else:
        logger.error(f"获取 access_token 失败: {data}")
        return ""


def _send_reply(to_user: str, text: str) -> bool:
    """通过企微 API 发送文本消息给指定用户

    Args:
        to_user: 企微用户 ID（从消息 XML 的 FromUserName 字段提取）
        text: Agent 生成的回复文本

    Returns:
        True 表示企微 API 返回成功

    注意：
      这里用的是"应用消息发送"接口——消息会以"自建应用"的身份
      出现在用户的企微对话列表里，不是在群里回复。
    """
    token = _get_access_token()
    if not token:
        return False

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    body = {
        "touser": to_user,            # 发给谁
        "msgtype": "text",            # 文本消息
        "agentid": int(AGENTID) if AGENTID else 0,  # 哪个自建应用发的
        "text": {"content": text},    # 消息内容——Agent 的回答
    }
    resp = requests.post(url, json=body, timeout=10)
    ok = resp.json().get("errcode") == 0
    logger.info(f"回复{'成功' if ok else '失败'}: {text[:50]}...")
    return ok


# ── 企微回调路由 ──

@app.get("/callback", response_class=PlainTextResponse)
async def verify_callback(request: Request):
    """GET /callback —— 企微首次配置回调 URL 时的验证

    企微在"保存回调配置"时会发一个 GET 请求到回调 URL，
    带 echostr 参数。服务器必须原样返回这个值——企微用它验证
    "这个 URL 确实是你控制的服务器在响应"。

    如果 5 秒内不返回正确的 echostr → 企微认为 URL 不可达 → 配置失败。
    """
    params = request.query_params
    echo = params.get("echostr", "ok")
    logger.info(f"回调验证请求: {echo[:20]}...")
    return PlainTextResponse(echo)


@app.post("/callback")
async def receive_message(request: Request):
    """POST /callback —— 接收企微推送的用户消息 → 调 Agent → 回复

    完整处理链：
      1. 读取 XML body（企微消息格式是 XML，不是 JSON）
      2. 解析 MsgType / Content / FromUserName 三个关键字段
      3. 如果是 text 类型且有内容 → 调 run_agent(content)
      4. 拿到 Agent 回复后 → 调 _send_reply() 发回给用户
      5. 返回空字符串 "" 给企微（企微只关心 200 状态码，不关心 body）

    异常处理分两层：
      - Agent 异常：回复"暂时无法处理"给用户，不把报错堆栈丢给老板
      - XML/其他异常：静默返回空响应，记日志
    """
    body = await request.body()
    # 企微 XML 可能是 UTF-8 或 GBK——优先 UTF-8，失败回退 GBK
    try:
        xml_text = body.decode("utf-8")
    except UnicodeDecodeError:
        xml_text = body.decode("gbk")
    logger.info(f"收到企微消息: {xml_text[:200]}")

    try:
        # 解析 XML——企微消息的三个关键字段
        root = ET.fromstring(xml_text)
        msg_type = root.findtext("MsgType", "unknown")     # "text" 表示文字消息
        content = root.findtext("Content", "")             # 用户打的字
        from_user = root.findtext("FromUserName", "")      # 谁发的（企微用户 ID）
        logger.info(f"消息类型: {msg_type} | 来自: {from_user} | 内容: {content}")

        if msg_type == "text" and content:
            logger.info("Agent 思考中...")
            try:
                answer = run_agent(content)
                logger.info(f"Agent 回复: {answer[:200]}")
                _send_reply(from_user, answer)
            except Exception as agent_err:
                # Agent 异常 → 给用户友好提示，不把堆栈丢给老板
                logger.error(f"Agent 处理失败: {agent_err}")
                _send_reply(from_user, "抱歉，暂时无法处理您的问题，请稍后再试。")

        # 返回空字符串——企微只检查 HTTP 200，不关心响应 body
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
