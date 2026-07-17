"""
Agent LLM 调用 — 把消息和工具清单发给 DeepSeek，让它决定下一步做什么
==================================================================
职责：封装对 DeepSeek API 的调用。不涉及循环、不涉及数据库——只管"问 AI"这一步。

用法：
  from agent_llm import call_llm
  reply, tool_calls = call_llm(messages, TOOLS)
  # tool_calls = None → reply 就是给用户的最终回答
  # tool_calls 有值 → Agent 先去执行工具，把结果追加到 messages 再调一次
"""

import json
import os
import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
LLM_URL = "https://api.deepseek.com/v1/chat/completions"

SYSTEM_PROMPT = """你是一个门店经营数据分析助手。你可以调用工具查询数据库。

规则：
1. 如果用户的问题需要查数据，先调用对应的工具，根据工具返回的真实数据来回答。
2. 如果用户只是在闲聊（问好、感谢），直接文字回复，不需要调工具。
3. 回答用中文，简洁——说清楚数据是什么、意味着什么，不超过 5 句话。
4. 如果工具返回"暂无数据"，如实告知，不要编造。"""


def build_tool_prompt(tools: list[dict]) -> str:
    """把工具列表转成 LLM 能理解的纯文本（不用 OpenAI function calling 格式，简单直白）"""
    lines = ["你可以调用以下工具（回复格式：先输出你要调的工具名和参数 JSON，工具返回结果后你再组织回答）："]
    for t in tools:
        params = ", ".join(f"{k}: {v}" for k, v in t.get("parameters", {}).items())
        lines.append(f"- {t['name']}({params}): {t['description']}")
    return "\n".join(lines)


def call_llm(messages: list[dict], tools: list[dict]) -> tuple[str, dict | None]:
    """
    调一次 DeepSeek，返回 LLM 的决策。

    Args:
        messages: 对话历史 [{"role":"user","content":"..."}, ...]
        tools: 工具清单

    Returns:
        (reply, tool_call)
        - reply: LLM 的文字回复（或工具调用请求的原文）
        - tool_call: None = reply 就是最终回答；有值 = {"name":"xxx","params":{...}}
    """
    # 构建发给 LLM 的完整消息
    full_messages = [
        {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + build_tool_prompt(tools)},
    ] + messages

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "deepseek-chat",
        "messages": full_messages,
        "temperature": 0.1,     # 低温度 = 不乱编，严格按照工具清单来
        "max_tokens": 800,
    }

    resp = requests.post(LLM_URL, headers=headers, json=data, timeout=60)
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    # 尝试从 LLM 回复中解析出工具调用请求
    # LLM 可能先输出工具调用再给回答，也可能直接回答
    tool_call = _parse_tool_call(raw)
    return raw, tool_call


def _parse_tool_call(text: str) -> dict | None:
    """从 LLM 回复中尝试提取工具调用。格式：{工具名} {参数JSON}。
    如果 LLM 没调工具（直接回答），返回 None。"""
    # 找 JSON 块（LLM 可能在回复里夹了工具调用的 JSON）
    try:
        # 找第一个 { ... } 块
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            chunk = text[start:end + 1]
            parsed = json.loads(chunk)
            # 看是不是工具调用格式
            if "name" in parsed and "params" in parsed:
                return parsed
    except (json.JSONDecodeError, KeyError):
        pass
    return None
