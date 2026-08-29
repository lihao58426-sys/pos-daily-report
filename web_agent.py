"""
Web 版 Agent — 本地闭环的真实 Agent（浏览器对话入口，替代被卡的企业微信）
=========================================================================
数据流：
  浏览器提问 → POST /api/chat → run_agent(question, history) → 返回回答

为什么做这个：
  企微自建应用需要三方服务商资质，个人无法开通。于是把 Agent 的对话入口
  从"企微回调"换成"浏览器网页"——Agent 本体（循环/9 个工具/数据库）完全
  不变，只是换了一张嘴。链路 100% 自主可控，可公网部署、可现场演示。

用法：
  python web_agent.py          → 监听 0.0.0.0:8005，浏览器打开首页即可对话
  接口：
    GET  /          聊天页面
    POST /api/chat  对话 {"question": "...", "session_id": "可选（多轮记忆）"}
    GET  /health    健康检查
"""

import logging
import os
import uuid

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="POS 经营智能问答 Agent（Web 版）")

# 简单会话记忆：session_id → 对话历史（内存实现，重启即清空）
_sessions: dict[str, list[dict]] = {}
MAX_HISTORY = 20  # 只保留最近 N 条消息，控制 token 成本


class ChatRequest(BaseModel):
    question: str
    session_id: str = ""


def _get_history(session_id: str) -> list[dict]:
    return _sessions.get(session_id, [])


def _remember(session_id: str, role: str, content: str) -> None:
    history = _sessions.setdefault(session_id, [])
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        del history[: len(history) - MAX_HISTORY]


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(CHAT_PAGE)


@app.post("/api/chat")
async def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        return JSONResponse({"answer": "请输入问题。"})

    sid = req.session_id or uuid.uuid4().hex[:12]
    history = _get_history(sid)

    try:
        answer, trace = run_agent(question, history, return_trace=True)
    except Exception as e:
        logger.error(f"Agent 处理失败: {e}")
        answer = "抱歉，暂时无法处理您的问题，请稍后再试。"
        trace = []

    _remember(sid, "user", question)
    _remember(sid, "assistant", answer)
    logger.info(f"[{sid[:8]}] Q: {question[:40]} | A: {answer[:60]}")
    return JSONResponse({"answer": answer, "session_id": sid, "trace": trace})


@app.get("/health")
async def health():
    return {"status": "ok", "tools": 11}


# 聊天页面 HTML（拆成两段拼接，避免单次编辑过大）
_HTML_A = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>经营智能助手</title>
<style>
  body { margin:0; font-family:"Microsoft YaHei",sans-serif; background:#0f172a; color:#e2e8f0; height:100vh; display:flex; flex-direction:column; }
  header { padding:14px 20px; background:#1e293b; border-bottom:1px solid #334155; }
  header h1 { margin:0; font-size:16px; }
  header p { margin:2px 0 0; font-size:12px; color:#94a3b8; }
  #messages { flex:1; overflow-y:auto; padding:20px; max-width:760px; width:100%; margin:0 auto; box-sizing:border-box; }
  .msg { margin-bottom:14px; display:flex; }
  .msg.user { justify-content:flex-end; }
  .bubble { max-width:70%; padding:10px 14px; border-radius:12px; font-size:14px; line-height:1.6; white-space:pre-wrap; word-break:break-word; }
  .msg.user .bubble { background:#2563eb; border-top-right-radius:2px; }
  .msg.assistant .bubble { background:#1e293b; border-top-left-radius:2px; }
  .msg.system .bubble { background:#334155; color:#94a3b8; font-size:13px; max-width:85%; }
  #inputbar { padding:14px 20px; background:#1e293b; border-top:1px solid #334155; display:flex; gap:10px; max-width:760px; width:100%; margin:0 auto; box-sizing:border-box; }
  #input { flex:1; padding:10px 14px; border:1px solid #475569; border-radius:8px; background:#0f172a; color:#e2e8f0; font-size:14px; outline:none; }
  #send { padding:10px 22px; background:#2563eb; color:#fff; border:none; border-radius:8px; font-size:14px; cursor:pointer; }
  #send:disabled { background:#475569; cursor:not-allowed; }
  #typing { color:#94a3b8; font-size:13px; padding:4px 2px; margin-bottom:12px; }
</style>
</head>
<body>
<header>
  <h1>📊 门店经营智能问答助手</h1>
  <p>自然语言查营收 / 会员分群 / 商品排名 · Agent 自动查库回答（9 个工具）</p>
</header>
<div id="messages"></div>
<div id="inputbar">
  <input id="input" placeholder="例如：最近一周营收怎么样？" autocomplete="off">
  <button id="send">发送</button>
</div>
"""

_HTML_B = """<script>
(function () {
  var sid = localStorage.getItem("pos_agent_sid") || Math.random().toString(36).slice(2, 14);
  localStorage.setItem("pos_agent_sid", sid);
  var box = document.getElementById("messages");
  var input = document.getElementById("input");
  var send = document.getElementById("send");

  function add(text, who) {
    var wrap = document.createElement("div");
    wrap.className = "msg " + who;
    var b = document.createElement("div");
    b.className = "bubble";
    b.textContent = text;
    wrap.appendChild(b);
    box.appendChild(wrap);
    box.scrollTop = box.scrollHeight;
  }

  add("你好，我是门店经营数据分析助手。可以问我：\\n· 最近一周营收怎么样？\\n· 本月环比上月涨了吗？\\n· 哪个商品卖得最好？\\n· 哪些客户是流失客户？\\n· 这个月新增了多少会员？", "system");

  function ask() {
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    add(q, "user");
    send.disabled = true;
    var t = document.createElement("div");
    t.id = "typing";
    t.textContent = "Agent 正在查库分析…";
    box.appendChild(t);
    box.scrollTop = box.scrollHeight;

    fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question: q, session_id: sid})
    })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var tp = document.getElementById("typing");
      if (tp) tp.remove();
      add(d.answer || "（无返回）", "assistant");
    })
    .catch(function () {
      var tp = document.getElementById("typing");
      if (tp) tp.remove();
      add("网络错误，请稍后再试。", "assistant");
    })
    .finally(function () { send.disabled = false; });
  }

  send.addEventListener("click", ask);
  input.addEventListener("keydown", function (e) { if (e.key === "Enter") ask(); });
})();
</script>
</body>
</html>
"""

CHAT_PAGE = _HTML_A + _HTML_B


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8005"))
    logger.info(f"Web Agent 启动: http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)