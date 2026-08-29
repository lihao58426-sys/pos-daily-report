"""
运营 Agent 工具集 — RFM 会员数据库查询
========================================
给 POS Agent 追加 RFM 数据库的查询能力。
跟 agent_tools.py 平级——同一个 Agent，两套工具。

用法：
  from agent_tools_rfm import RFM_TOOLS
  ALL_TOOLS = TOOLS + RFM_TOOLS  # 合并两套工具给 Agent
"""

import os
import sqlite3
import time
from datetime import date, datetime, timedelta

from langchain_core.tools import tool

# RFM 数据库路径——跟 POS 同级的 rfm_report 目录
RFM_DB = os.getenv("RFM_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "rfm_report", "data", "rfm_data.db"))

# 内存缓存——同一截止日期 5 分钟内不重复计算
_cache_result = None
_cache_ts = 0.0
_cache_ttl = 300  # 秒


def _parse_date(s: str) -> date | None:
    """校验并解析 YYYY-MM-DD 日期"""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"日期格式错误: '{s}'，请使用 YYYY-MM-DD 格式，如 2026-07-01")


def _compute_rfm(as_of: date | None = None) -> list[dict]:
    """读 RFM 数据库全部会员 → 计算 R/F/M → 返回带分群标签的会员列表

    所有 @tool 函数调这个公共方法——5 分钟内同一截止日期复用缓存。
    """
    global _cache_result, _cache_ts

    today = as_of or date.today()
    cache_key = str(today)

    # 缓存命中
    now = time.time()
    if _cache_result is not None and cache_key == _cache_result[0] and (now - _cache_ts) < _cache_ttl:
        return _cache_result[1]

    conn = sqlite3.connect(RFM_DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            COALESCE(NULLIF(phone,''), member_name) as uid,
            COALESCE(NULLIF(member_name,''), phone) as display_name,
            SUM(CAST(revenue AS REAL)) as total_revenue,
            COUNT(*) as visit_count,
            MAX(trans_date) as last_date
        FROM transactions
        WHERE phone != '佚名' AND phone != '' AND member_name != ''
          AND CAST(revenue AS REAL) > 0
        GROUP BY uid
    """).fetchall()
    conn.close()

    if not rows:
        _cache_result = (cache_key, [])
        _cache_ts = now
        return []

    members = []
    for r in rows:
        revenue = float(r["total_revenue"]) if r["total_revenue"] else 0
        visits = int(r["visit_count"])
        last_str = str(r["last_date"] or "")[:10]
        last_date = datetime.strptime(last_str, "%Y-%m-%d").date() if last_str else today
        recency = (today - last_date).days
        members.append({
            "name": r["display_name"],
            "revenue": revenue,
            "visits": visits,
            "recency": recency,
        })

    n = len(members)
    avg_r = sum(m["recency"] for m in members) / n
    avg_f = sum(m["visits"] for m in members) / n
    avg_m = sum(m["revenue"] for m in members) / n

    name_map = {
        ("近","高","高"): "重要价值客户", ("远","高","高"): "重要唤回客户",
        ("近","低","高"): "重要发展客户", ("远","低","高"): "重要挽留客户",
        ("近","高","低"): "一般活跃客户", ("远","高","低"): "一般客户",
        ("近","低","低"): "新客/低频客户", ("远","低","低"): "流失客户",
    }
    for m in members:
        r_label = "近" if m["recency"] < avg_r else "远"
        f_label = "高" if m["visits"] >= avg_f else "低"
        m_label = "高" if m["revenue"] >= avg_m else "低"
        m["segment"] = name_map.get((r_label, f_label, m_label), "未分类")

    _cache_result = (cache_key, members)
    _cache_ts = now
    return members


# ── 工具函数 ──

@tool
def query_segments(as_of: str = "") -> str:
    """查 RFM 客户分群概况——各分群的人数、消费总额、人均消费。
    注意：这里金额是 RFM 口径（会员实际消费折价），与 POS 营业实收口径不同，不可混加。
    as_of 格式 YYYY-MM-DD，指定截止日期。不传默认今天。
    用于回答'会员分群情况怎么样''哪个分群人数最多'。"""
    try:
        cutoff = _parse_date(as_of)
        members = _compute_rfm(cutoff)
        if not members:
            return "RFM 数据库中暂无会员数据，请先上传银豹 CSV 导入。"

        segs = {}
        for m in members:
            s = m["segment"]
            if s not in segs:
                segs[s] = {"count": 0, "revenue": 0.0}
            segs[s]["count"] += 1
            segs[s]["revenue"] += m["revenue"]

        lines = [f"RFM 客户分群概况（共 {len(members)} 人）："]
        total_revenue = sum(s["revenue"] for s in segs.values())
        for name, s in segs.items():
            avg = round(s["revenue"] / s["count"]) if s["count"] else 0
            pct = s["revenue"] / total_revenue * 100 if total_revenue > 0 else 0
            lines.append(f"  {name}：{s['count']} 人 | 营收 ¥{s['revenue']:.0f}（{pct:.0f}%）| 人均 ¥{avg}")
        return "\n".join(lines)
    except Exception as e:
        return f"查询 RFM 数据库失败: {e}"


@tool
def query_member_detail(segment: str = "", as_of: str = "", top_n: int = 20) -> str:
    """查某个 RFM 分群的具体会员列表。
    segment：分群名称，例如'流失客户''重要价值客户'。
    as_of：截止日期 YYYY-MM-DD，不传默认今天。
    top_n：返回前 N 名，默认 20。
    用于回答'流失客户有哪些''重要价值客户是谁'。"""
    try:
        if not segment:
            return "请指定要查询的分群名称，例如：流失客户、重要价值客户。"

        cutoff = _parse_date(as_of)
        members = _compute_rfm(cutoff)
        if not members:
            return "暂无会员数据。"

        matched = [m for m in members if m["segment"] == segment]
        if not matched:
            available = sorted(set(m["segment"] for m in members))
            return f"没有找到分群「{segment}」。可选：{', '.join(available)}"

        matched.sort(key=lambda m: m["revenue"], reverse=True)
        lines = [f"「{segment}」会员列表（共 {len(matched)} 人，显示前 {min(top_n, len(matched))}）："]
        for m in matched[:top_n]:
            lines.append(f"  {m['name']} | 消费 ¥{m['revenue']:.0f} | {m['visits']}次 | 上次 {m['recency']}天前")
        if len(matched) > top_n:
            lines.append(f"  ...还有 {len(matched) - top_n} 人（可调整 top_n 查看更多）")
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


@tool
def query_member_trend(months: int = 6) -> str:
    """查最近 N 个月的会员月度消费趋势——每月到店人数、消费总额。
    用于回答'最近几个月会员消费在涨还是跌'。"""
    try:
        conn = sqlite3.connect(RFM_DB)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT
                SUBSTR(trans_date, 1, 7) as month,
                COUNT(DISTINCT COALESCE(NULLIF(phone,''), member_name)) as member_count,
                SUM(CAST(revenue AS REAL)) as total_revenue
            FROM transactions
            WHERE phone != '佚名' AND member_name != ''
              AND CAST(revenue AS REAL) > 0
            GROUP BY month
            ORDER BY month DESC
            LIMIT ?
        """, (months,)).fetchall()
        conn.close()

        if not rows:
            return "暂无月度消费数据。"

        rows = list(reversed(rows))
        lines = [f"最近 {months} 个月会员消费趋势："]
        for r in rows:
            lines.append(f"  {r['month']} | {r['member_count']} 人到店 | 营收 ¥{r['total_revenue']:.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"查询失败: {e}"


@tool
def query_new_members(month: str = "") -> str:
    """查某月新增会员数量，与上月对比。
    month 格式 YYYY-MM，不传默认查上个月。
    用于回答'这个月新增了多少会员''新客有没有变多'。"""
    try:
        if not month:
            now = datetime.now()
            first_of_this = now.replace(day=1)
            month = (first_of_this - timedelta(days=1)).strftime("%Y-%m")

        conn = sqlite3.connect(RFM_DB)
        conn.row_factory = sqlite3.Row

        # 当月首次消费的会员
        this_new = conn.execute("""
            SELECT COALESCE(NULLIF(phone,''), member_name) as uid
            FROM transactions
            WHERE SUBSTR(trans_date, 1, 7) = ?
            GROUP BY uid
            HAVING MIN(trans_date) >= ?
        """, (month, month + "-01")).fetchall()

        # 上月
        y, m = map(int, month.split("-"))
        if m == 1:
            prev_month = f"{y-1}-12"
        else:
            prev_month = f"{y}-{m-1:02d}"
        prev_new = conn.execute("""
            SELECT COALESCE(NULLIF(phone,''), member_name) as uid
            FROM transactions
            WHERE SUBSTR(trans_date, 1, 7) = ?
            GROUP BY uid
            HAVING MIN(trans_date) >= ?
        """, (prev_month, prev_month + "-01")).fetchall()
        conn.close()

        this_count = len(this_new)
        prev_count = len(prev_new)

        change_str = ""
        if prev_count > 0:
            change_pct = (this_count - prev_count) / prev_count * 100
            change_str = (
                f"{'增加' if change_pct >= 0 else '减少'} {abs(this_count - prev_count)} 人"
                f"（{'+' if change_pct >= 0 else ''}{change_pct:.0f}%）"
            )
        else:
            change_str = f"新增 {this_count} 人（上月无数据，无法对比）"

        return f"{month} 新增会员 {this_count} 人。上月（{prev_month}）新增 {prev_count} 人。{change_str}"
    except Exception as e:
        return f"查询失败: {e}"


# ── 工具注册 ──

RFM_TOOLS = [query_segments, query_member_detail, query_member_trend, query_new_members]
