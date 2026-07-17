"""
Agent 循环 — LLM 思考 → 选工具 → 执行 → 再思考 → 直到回答
==========================================================
这是整个 Agent 的大脑中枢。依赖 agent_llm（调 LLM）和 agent_tools（执行工具）。

用法：
  python agent.py                    # 终端交互测试
  from agent import run_agent        # 企微回调里调它

逻辑：
  用户问 → LLM 想：要查数据吗？
    → 要 → 调工具 → 拿到数据 → 再问 LLM → LLM 组织回答
    → 不要 → 直接回
"""

from agent_llm import call_llm
from agent_tools import TOOLS, execute_tool

MAX_TURNS = 5  # 最多调 5 轮工具，避免死循环


def run_agent(user_question: str, conversation_history: list[dict] | None = None) -> str:
    """
    接收用户问题 → 跟 LLM 对话 → 调工具 → 返回最终回答。

    Args:
        user_question: 老板在企微里发的问题
        conversation_history: 之前的对话上下文（可选）

    Returns:
        Agent 的最终文字回答
    """
    messages = (conversation_history or []) + [
        {"role": "user", "content": user_question},
    ]

    for _ in range(MAX_TURNS):
        # ① 问 LLM：你要调工具还是直接回答？
        raw_reply, tool_call = call_llm(messages, TOOLS)

        # ② LLM 不调工具 → 这就是最终回答
        if tool_call is None:
            return raw_reply

        # ③ LLM 要调工具 → 执行它
        tool_result = execute_tool(tool_call["name"], tool_call.get("params", {}))

        # ④ 把工具结果追加到对话历史，再进入下一轮
        messages.append({"role": "assistant", "content": raw_reply})
        messages.append({"role": "user", "content": f"工具 {tool_call['name']} 返回结果：\n{tool_result}\n\n请根据这些数据回答用户最初的问题。"})

    # 超出最大轮数，强制返回最后的 LLM 回复
    return raw_reply


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
