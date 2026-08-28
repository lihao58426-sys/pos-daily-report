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
    """查指定门店最近N天的收银日报。返回每天营业实收（总额）及其构成明细。
    注意：储值卡、次卡、礼品包等是营收的子项拆分——营收已经包含了它们，不要重复相加。
    用于回答'最近生意怎么样''这周卖了多少'这类问题。"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_history(days=days, store_id=store_id)
    if not rows:
        return f"{store_id} 最近 {days} 天暂无数据。"
    lines = []
    for r in rows:
        parts = [f"营业实收 {r['revenue']:.0f} 元"]
        card = r.get('card_recharge', 0) or 0
        time_card = r.get('time_card_sales', 0) or 0
        gift = r.get('gift_pack_sales', 0) or 0
        if card or time_card or gift:
            sub = []
            if card: sub.append(f"储值卡 {card:.0f}")
            if time_card: sub.append(f"次卡 {time_card:.0f}")
            if gift: sub.append(f"礼品包 {gift:.0f}")
            parts.append("（其中: " + ", ".join(sub) + "）")
        lines.append(f"{r['date']} | {' '.join(parts)}")
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
def query_product_ranking(store_id: str = "xianyang", days: int = 1) -> str:
    """查商品销量排名。days=1（默认）查最近一天；days=7/30 时按最近 N 天聚合返回各商品累计销量排名。
    用于回答'哪个卖得最好''这个月什么最好卖''最近一周卖得最好的商品'。"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_product_rankings(store_id=store_id, days=days)
    if not rows:
        return f"{store_id} 暂无商品排名数据。"
    if days > 1:
        lines = [f"{store_id} 最近 {days} 天商品销量聚合排名："]
        for i, r in enumerate(rows[:10], 1):
            lines.append(f"  #{i} {r['product_name']} 共售出 {r['total_qty']} 次（覆盖 {r['days_sold']} 天）")
    else:
        date = rows[0].get("date", "最近")
        lines = [f"{date} {store_id} 商品排名："]
        for r in rows[:10]:
            lines.append(f"  #{r['rank']} {r['product_name']} ×{r['quantity']}")
    return "\n".join(lines)


# ── 2. 工具清单——LangChain 自动从 @tool 装饰器生成描述 ──

TOOLS_LC = [query_history, query_trend, query_comparison, query_summary, query_product_ranking]

# 运营工具（RFM 会员库）
from agent_tools_rfm import RFM_TOOLS
ALL_TOOLS = TOOLS_LC + RFM_TOOLS  # 会计 5 工具 + 运营 4 工具

# ── 3. LLM —— 带工具绑定 ──

_llm = ChatOpenAI(
    model="deepseek-v4-pro",
    base_url="https://api.deepseek.com/v1",
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    temperature=0.3,
    max_tokens=1200,
)

_llm_with_tools = _llm.bind_tools(ALL_TOOLS)  # ← LangChain 自动生成 Function Calling schema


# ── 4. Agent 循环（替代手写 while 循环）──

MAX_TURNS = 5

def run_agent_langchain(user_question: str) -> str:
    """接收用户问题 → LLM 选工具 → 执行 → 综合回答"""
    messages = [
        SystemMessage(content="你是门店数据助手兼运营顾问，管理两套数据库：\n"
               "① 营收日报库（POS 每日自动抓取）\n"
               "   统计口径：门店营业实收 = 银豹收银系统当天全部现金收入。\n"
               "   包含：储值卡消费、次卡消费、礼品包、会员升级等各类流水。\n"
               "   工具返回的「储值卡/次卡/礼品包」是营业实收的子项拆分，不是额外收入——不要再把它们加上去。\n"
               "② 会员消费库（RFM 手动导入）\n"
               "   统计口径：会员实际消费金额，已按会员套餐折扣折价。\n"
               "   不含办卡预存（储值行为不算消费）。\n"
               "   POS 营收看收银台流水，RFM 消费看会员行为——两套口径不同，跨库时分别标注，不要强凑总数。"
               "老板问活动建议时，先调数据工具获取事实，再基于数据进行分析："
               "① 数据综述——上个月会员消费情况，发现了什么问题"
               "② 活动方案——针对发现的问题给出2-3个选项，每个含目标人群、预计增收、成本预算"
               "③ 寻求决策——让老板选采纳哪个方案"
               "用口语化中文回答，给出具体数字。"),
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
            tool_map = {t.name: t for t in ALL_TOOLS}
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
