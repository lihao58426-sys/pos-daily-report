"""
Agent 问答 — LangChain @tool 版本
===================================
跟 agent.py 做同一件事——LLM 选工具 → 执行 → 综合回答。
区别：用 LangChain 的 @tool 装饰器 + bind_tools，不手写 TOOLS 字典和解析逻辑。

手写版 vs LangChain 版对比：
  手写：~80 行，自己定义 TOOLS JSON、自己解析、自己循环
  @tool：~50 行，@tool 自动生成工具描述，bind_tools 自动处理 Function Calling

用法：
  python agent_langchain.py "上周咸阳卖了多少"
"""

import json
import logging
import os

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from database import ReportDatabase

os.makedirs("data", exist_ok=True)
DB_PATH = "data/daily_report.db"
logger = logging.getLogger(__name__)

# ── 1. 用 @tool 装饰器定义工具（替代手写的 TOOLS 字典）──

@tool
def query_history(store_id: str = "xianyang", days: int = 7) -> str:
    """查指定门店最近N天的营收数据。返回每天日期、营业额、储值卡消费、次卡消费。
    用于回答'最近生意怎么样''这周卖了多少'这类问题。"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_history(days=days, store_id=store_id)
    if not rows:
        return f"{store_id} 最近 {days} 天暂无数据。"
    lines = [f"{r['date']} | 营收 {r['revenue']:.0f} 元 | 储值卡 {r['card_recharge']:.0f} | 次卡 {r['time_card_sales']:.0f}" for r in rows]
    return "\n".join(lines)


@tool
def query_trend(days: int = 30) -> str:
    """查营收趋势。返回最近N天每天的营业额，按日期升序排列。
    用于回答'最近在涨还是跌''有没有什么变化趋势'。"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_trend(days=days)
    if not rows:
        return f"最近 {days} 天暂无数据。"
    lines = [f"{r['date']} | {r['revenue']:.0f} 元" for r in rows]
    return "\n".join(lines)


@tool
def query_comparison() -> str:
    """对比本月和上个月的营收，算出环比涨跌幅。
    用于回答'环比涨了没''跟比上月比怎么样'。"""
    with ReportDatabase(DB_PATH) as db:
        c = db.get_comparison()
    return (
        f"本月至今 {c['this_month_days']} 天，总营收 {c['this_month_total']:.0f} 元；"
        f"上月同期 {c['last_month_days']} 天，总营收 {c['last_month_total']:.0f} 元；"
        f"环比 {'+' if c['change_pct'] >= 0 else ''}{c['change_pct']}%"
    )


@tool
def query_summary() -> str:
    """查数据库整体统计——总共多少天数据、累计营收、日均营收。
    用于回答'总共多少''开业以来总共赚了多少'。"""
    with ReportDatabase(DB_PATH) as db:
        s = db.get_summary()
    return (
        f"共 {s['total_days']} 天数据，累计营收 {s['total_revenue']:.0f} 元，"
        f"日均 {s['avg_daily']:.0f} 元"
    )


@tool
def query_product_ranking(store_id: str = "xianyang") -> str:
    """查最近一天的商品销量排名 Top10。
    用于回答'哪个卖得最好''什么最好卖'。"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_product_rankings(store_id=store_id)
    if not rows:
        return f"{store_id} 暂无商品排名数据。"
    date = rows[0].get("date", "最近")
    lines = [f"{date} {store_id} 商品排名："]
    for r in rows[:10]:
        lines.append(f"  #{r['rank']} {r['product_name']} ×{r['quantity']}")
    return "\n".join(lines)


# ── 2. 工具清单——LangChain 自动从 @tool 装饰器生成描述 ──

TOOLS_LC = [query_history, query_trend, query_comparison, query_summary, query_product_ranking]

# ── 3. LLM —— 带工具绑定 ──

_llm = ChatOpenAI(
    model="deepseek-v4-pro",
    base_url="https://api.deepseek.com/v1",
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    temperature=0.3,
    max_tokens=1200,
)

_llm_with_tools = _llm.bind_tools(TOOLS_LC)  # ← LangChain 自动生成 Function Calling schema


# ── 4. Agent 循环（替代手写 while 循环）──

MAX_TURNS = 5

def run_agent_langchain(user_question: str) -> str:
    """接收用户问题 → LLM 选工具 → 执行 → 综合回答"""
    messages = [
        SystemMessage(content="你是 POS 数据助手。根据数据库查询结果回答老板的经营问题。用口语化的中文，给出具体数字。"),
        HumanMessage(content=user_question),
    ]

    for turn in range(MAX_TURNS):
        response = _llm_with_tools.invoke(messages)

        # 没要调工具 → 直接返回答案
        if not response.tool_calls:
            return response.content

        # 需要调工具 → 追加 AI 消息（只加一次）、逐个执行工具、回填结果
        messages.append(response)  # 只加一次——不因多个 tool_call 而重复

        for tc in response.tool_calls:
            logger.info(f"Agent 调用工具: {tc['name']}({tc['args']})")
            tool_map = {t.name: t for t in TOOLS_LC}
            func = tool_map.get(tc["name"])
            if func:
                try:
                    result = func.invoke(tc["args"])
                except Exception as e:
                    result = f"查询出错: {e}"
                    logger.error(f"工具 {tc['name']} 执行失败: {e}")
            else:
                result = f"未知工具: {tc['name']}"

            messages.append(ToolMessage(content=result, tool_call_id=tc["id"]))

    logger.warning(f"Agent 达到最大轮数 {MAX_TURNS}，问题: {user_question[:50]}")
    return response.content


# ── CLI 测试入口 ──

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        q = input("老板：")
    print(f"\n老板：{q}")
    print("Agent 思考中...\n")
    answer = run_agent_langchain(q)
    print(f"Agent：{answer}")
