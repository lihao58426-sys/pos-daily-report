"""
日报内容构建模块
--------------
职责：只负责"把数据拼成好看的日报文字"，不关心怎么发出去。

为什么从 wechat_push.py 拆出来？
  - 原来 build_markdown_report() 和 WeWorkBotPush 混在一起
  - 报告排版是"内容逻辑"，推送是"传输逻辑"——完全不同的东西
  - 以后改日报格式（比如加图表、改排版），只需要动这个文件

v2 改动：入参从 dict 改为 DailyReport dataclass
  - 原来：data.get("营业实收", "0")  ← 字符串 key，拼错不报错
  - 现在：report.revenue              ← 属性访问，自动补全
"""

import logging
import re
from datetime import datetime

from models import DailyReport

logger = logging.getLogger(__name__)


def _parse_product_table(raw_text: str) -> list[dict[str, str]]:
    """从商品销售统计的原始表格文本中解析出商品列表

    这是内部辅助函数，外部不需要直接调用。
    输入是爬虫从页面上抓下来的原始文本，输出是结构化的商品列表。
    """
    lines = raw_text.strip().splitlines()
    products: list[dict[str, str]] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ["商品名", "商品名称", "名称\t", "销量", "金额\t", "序号"]):
            continue

        nums = re.findall(r"[\d.]+", line)
        if not nums:
            continue

        words = re.split(r"\s+", line)
        name_parts: list[str] = []
        for w in words:
            if re.search(r"^\d+\.?\d*$", w):
                break
            name_parts.append(w)
        name = "".join(name_parts).strip()
        if not name:
            continue

        qty = nums[0] if len(nums) >= 1 else ""
        products.append({"name": name, "qty": qty})

    try:
        products.sort(key=lambda x: float(x.get("qty", 0) or 0), reverse=True)
    except Exception:
        pass

    return products


def build_markdown_report(report: DailyReport, date_str: str | None = None) -> str:
    """根据 DailyReport 构建游乐场日报 Markdown

    这是 report 模块的核心函数。入参从 dict 改为 DailyReport dataclass——
    report.revenue 替代了 data.get("营业实收", "0")。

    Args:
        report: DailyReport 数据对象（来自 models.py）
        date_str: 日期字符串，默认取今天

    Returns:
        企微 Markdown 格式的日报字符串
    """
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")

    lines: list[str] = []

    # ── 头部 ──
    lines.append("# 游乐场日报")
    lines.append(f"> 日期：{date_str}")
    if report.time_range:
        lines.append(f"> 查询时间：{report.time_range}")
    lines.append("")

    # ── 核心指标 ──
    lines.append(f"## 今日营业实收：**{report.revenue:.0f}** 元")
    lines.append("")

    # ── 关键收入明细（只显示金额 > 0 的项目）──
    items = report.revenue_items
    if items:
        lines.append("## 关键收入")
        lines.append("")
        lines.append("| 项目 | 金额 |")
        lines.append("| --- | ---: |")
        for item in items:
            lines.append(f"| {item.name} | {item.amount:.0f} 元 |")
        lines.append("")

    # ── 商品消费排名 ──
    if report.product_ranking:
        lines.append("## 商品消费单数排名")
        lines.append("")
        lines.append("| 排名 | 商品 | 销量 |")
        lines.append("| ---: | --- | ---: |")
        for i, prod in enumerate(report.product_ranking, 1):
            name = prod.get("name", "")
            count = prod.get("count", "0")
            lines.append(f"| {i} | {name} | {count} 单 |")
        lines.append("")

    # ── 尾部 ──
    lines.append("---")
    lines.append(f" 系统自动生成 · {now_str}")

    return "\n".join(lines)
