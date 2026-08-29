"""
Agent 循环 — LLM 思考 → 选工具 → 执行 → 再思考 → 直到回答
==========================================================
这是整个 Agent 的大脑中枢。依赖 agent_llm（调 LLM）和 agent_tools（执行工具）。

用法：
  python agent.py                    # 终端交互测试
  from agent import run_agent        # 企微回调 / Web 服务里调它

逻辑：
  用户问 → LLM 想：要查数据吗？
    → 要 → 调工具 → 拿到数据 → 再问 LLM → LLM 组织回答
    → 不要 → 直接回

工具清单：会计(5) + RFM(4) = 9 个，见 ALL_TOOLS。
"""

from agent_llm import call_llm
from agent_tools import TOOLS, execute_tool
from agent_tools_rfm import RFM_TOOLS

MAX_TURNS = 5  # 最多调 5 轮工具，避免死循环


# ── 合并会计(5) + RFM(4) 共 9 个工具 ──

def _rfm_tool_to_dict(tool) -> dict:
    """把 LangChain @tool 对象转成 agent_llm 认识的 dict 格式"""
    schema = tool.args  # JSON schema dict，参数在 properties 里
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    params = {}
    for name, meta in properties.items():
        if isinstance(meta, dict):
            params[name] = meta.get("description", "") or name
        else:
            params[name] = str(meta)
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": params,
    }


# 9 个工具的完整清单（发给 LLM 看的"说明书"）
ALL_TOOLS = TOOLS + [_rfm_tool_to_dict(t) for t in RFM_TOOLS]

# RFM 工具执行器：LangChain @tool 对象的原始函数
_RFM_EXECUTORS = {t.name: t.func for t in RFM_TOOLS}


def execute_any_tool(name: str, params: dict) -> str:
    """统一执行器：会计工具走 execute_tool，RFM 工具走 LangChain func"""
    if name in _RFM_EXECUTORS:
        try:
            return str(_RFM_EXECUTORS[name](**params))
        except Exception as e:
            return f"工具 {name} 执行失败: {e}"
    return execute_tool(name, params)


def run_agent(user_question: str, conversation_history: list[dict] | None = None, return_trace: bool = False):
    """
    接收用户问题 → 跟 LLM 对话 → 调工具 → 返回最终回答。

    Args:
        user_question: 用户发的问题
        conversation_history: 之前的对话上下文（可选，多轮记忆）
        return_trace: True 时返回 (answer, trace)，trace 记录每轮工具调用（可观测性/eval 用）

    Returns:
        return_trace=False（默认）: Agent 的最终文字回答
        return_trace=True: (回答, trace列表) —— trace 元素 {"name", "params", "result"}
    """
    messages = (conversation_history or []) + [
        {"role": "user", "content": user_question},
    ]

    import logging
    logger = logging.getLogger(__name__)

    trace: list[dict] = []
    raw_reply = ""
    for _ in range(MAX_TURNS):
        raw_reply, tool_call = call_llm(messages, ALL_TOOLS)
        if tool_call is None:
            return (raw_reply, trace) if return_trace else raw_reply

        tool_result = execute_any_tool(tool_call["name"], tool_call.get("params", {}))
        # 记录轨迹（结果截断，防止响应过大）
        trace.append({
            "name": tool_call["name"],
            "params": tool_call.get("params", {}),
            "result": (tool_result or "")[:400],
        })
        messages.append({"role": "assistant", "content": raw_reply})
        messages.append({"role": "user", "content": f"工具 {tool_call['name']} 返回结果：\n{tool_result}\n\n请根据这些数据回答用户最初的问题。"})

    # 超出最大轮数——可能 LLM 在反复调工具但没找到答案
    logger.warning(f"Agent 达到最大轮数 {MAX_TURNS}，强制结束。问题: {user_question[:50]}")
    return (raw_reply, trace) if return_trace else raw_reply


# ── 终端测试入口 ──
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        q = input("老板：")
    print(f"\n老板：{q}")
    print("Agent 思考中...\n")
    answer = run_agent(q)
    print(f"Agent：{answer}")
