"""
Agent 工具集 — 把数据库查询函数包装成 LLM 可调用的 Tool
=====================================================
职责：告诉 DeepSeek（Agent 的大脑）POS 系统有哪些查询能力可用。
每个 Tool 是一份"说明书"——函数名、功能、参数含义。

用法：
  from agent_tools import TOOLS, execute_tool
  result = execute_tool("query_history", {"store_id": "xianyang", "days": 7})

Agent 循环逻辑见 agent.py（下一个 commit）。
"""

from database import ReportDatabase

DB_PATH = "daily_report.db"


# ── 工具执行函数 ──

def _run_query_history(store_id: str = "xianyang", days: int = 7) -> str:
    """查指定门店最近 N 天的营收数据"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_history(days=days, store_id=store_id)
    if not rows:
        return f"{store_id} 最近 {days} 天暂无数据。"
    lines = [f"{r['date']} | 营收 {r['revenue']:.0f} 元 | 储值卡 {r['card_recharge']:.0f} | 次卡 {r['time_card_sales']:.0f}" for r in rows]
    return "\n".join(lines)


def _run_trend(days: int = 30) -> str:
    """查营收趋势（按日升序，给画图或分析用）"""
    with ReportDatabase(DB_PATH) as db:
        rows = db.get_trend(days=days)
    if not rows:
        return f"最近 {days} 天暂无数据。"
    lines = [f"{r['date']} | {r['revenue']:.0f} 元" for r in rows]
    return "\n".join(lines)


def _run_comparison() -> str:
    """本月 vs 上月环比"""
    with ReportDatabase(DB_PATH) as db:
        c = db.get_comparison()
    return (
        f"本月至今 {c['this_month_days']} 天，总营收 {c['this_month_total']:.0f} 元；"
        f"上月同期 {c['last_month_days']} 天，总营收 {c['last_month_total']:.0f} 元；"
        f"环比 {'+' if c['change_pct'] >= 0 else ''}{c['change_pct']}%"
    )


def _run_summary() -> str:
    """整体统计摘要"""
    with ReportDatabase(DB_PATH) as db:
        s = db.get_summary()
    return (
        f"共 {s['total_days']} 天数据，累计营收 {s['total_revenue']:.0f} 元，"
        f"日均 {s['avg_daily']:.0f} 元"
    )


def _run_product_ranking(store_id: str = "xianyang", days: int = 1) -> str:
    """查商品销量排名"""
    from datetime import datetime, timedelta
    with ReportDatabase(DB_PATH) as db:
        # 兼容多天查询：取最近几天的排名（简化处理，取最新一天）
        rows = db.get_product_rankings()
    if not rows:
        return f"{store_id} 暂无商品排名数据。"
    date = rows[0].get("date", "最近")
    lines = [f"{date} {store_id} 商品排名："]
    for r in rows[:10]:
        lines.append(f"  #{r['rank']} {r['product_name']} ×{r['quantity']}")
    return "\n".join(lines)


# ── Tool 注册表（Agent 的大脑读这个清单，决定调哪个）──

TOOLS = [
    {
        "name": "query_history",
        "description": "查指定门店最近N天的营收数据。返回每天日期、营业额、储值卡消费、次卡消费。用于回答'最近生意怎么样''这周卖了多少'这类问题。",
        "parameters": {
            "store_id": "门店ID，可选值：xianyang（咸阳总店）。不传默认 xianyang。",
            "days": "查最近几天，默认7天。老板问'这周'=7，'这个月'=30。",
        },
    },
    {
        "name": "query_trend",
        "description": "查营收趋势。返回最近N天每天的营业额，按日期升序排列。用于回答'最近在涨还是跌''有没有什么变化趋势'。",
        "parameters": {
            "days": "查几天趋势，默认30。",
        },
    },
    {
        "name": "query_comparison",
        "description": "对比本月和上个月的营收，算出环比涨跌幅。用于回答'环比涨了没''跟比上月比怎么样'。",
        "parameters": {},
    },
    {
        "name": "query_summary",
        "description": "查数据库整体统计——总共多少天数据、累计营收、日均营收。用于回答'总共多少''开业以来总共赚了多少'。",
        "parameters": {},
    },
    {
        "name": "query_product_ranking",
        "description": "查最近一天的商品销量排名 Top10。用于回答'哪个卖得最好''什么最好卖'。",
        "parameters": {
            "store_id": "门店ID，默认 xianyang。",
        },
    },
]

# 工具名 → 执行函数的映射
_EXECUTORS = {
    "query_history": _run_query_history,
    "query_trend": _run_trend,
    "query_comparison": _run_comparison,
    "query_summary": _run_summary,
    "query_product_ranking": _run_product_ranking,
}


def execute_tool(name: str, params: dict) -> str:
    """Agent 调这个函数来执行工具。传入工具名和参数，返回执行结果字符串。"""
    func = _EXECUTORS.get(name)
    if not func:
        return f"未知工具: {name}"
    return func(**params)
