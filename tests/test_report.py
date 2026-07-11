"""
测试 report.py — 日报 Markdown 构建
"""

import sys
sys.path.insert(0, '..')

from models import DailyReport
from report import build_markdown_report


def test_build_markdown_basic():
    """最简日报：只有营业额"""
    report = DailyReport(revenue=12345)
    md = build_markdown_report(report)
    assert "12345" in md
    assert "游乐场日报" in md
    assert "今日营业实收" in md

def test_build_markdown_with_income():
    """含关键收入的日报"""
    report = DailyReport(revenue=10000, card_recharge=5000,
                         time_card_sales=2000, member_upgrade=0)
    md = build_markdown_report(report)
    assert "储值卡充值" in md
    assert "5000" in md
    assert "次卡销售" in md
    assert "2000" in md

def test_build_markdown_with_time_range():
    """含时间跨度的日报"""
    report = DailyReport(revenue=8000, time_range="2026-07-01 ~ 2026-07-31")
    md = build_markdown_report(report)
    assert "2026-07-01" in md

def test_build_markdown_custom_date():
    """自定义日期"""
    report = DailyReport(revenue=5000)
    md = build_markdown_report(report, date_str="2026-08-01")
    assert "2026-08-01" in md

def test_build_markdown_zero_revenue():
    """零营业额 → 不崩溃"""
    report = DailyReport(revenue=0)
    md = build_markdown_report(report)
    assert "0" in md
    assert len(md) > 50  # 至少有头部和尾部
