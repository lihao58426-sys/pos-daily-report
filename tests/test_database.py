"""
测试 database.py — SQLite 增删改查
用 :memory: 数据库，不碰真实的 daily_report.db
"""

import sys
sys.path.insert(0, '..')

import os
from datetime import datetime, timedelta
from database import ReportDatabase
from models import DailyReport

# 测试日期用相对"今天"的值，避免硬编码日期随日历过期导致用例失败
_TODAY = datetime.now()
RECENT_DATE = (_TODAY - timedelta(days=1)).strftime("%Y-%m-%d")


class TestReportDatabase:
    """测试 ReportDatabase 类"""

    @classmethod
    def setup_class(cls):
        """所有测试前：创建内存数据库"""
        # :memory: = 临时数据库，关掉就消失，不碰真实数据
        cls.db = ReportDatabase(":memory:")

    def test_insert_and_get_history(self):
        """插入一条 → 查历史能查到"""
        report = DailyReport(revenue=10000, card_recharge=3000, time_card_sales=1500)
        rid = self.db.insert(report, date=RECENT_DATE, store_id="test")
        assert rid > 0  # 插入成功，返回了 ID

        rows = self.db.get_history(days=30)
        assert len(rows) >= 1
        assert rows[0]["revenue"] == 10000

    def test_get_trend(self):
        """趋势查询：按日期升序"""
        trend = self.db.get_trend(days=30)
        assert len(trend) >= 1
        # 趋势数据应该包含 date 和 revenue
        assert "date" in trend[0]
        assert "revenue" in trend[0]

    def test_get_summary(self):
        """汇总统计"""
        summary = self.db.get_summary()
        assert summary["total_days"] >= 1
        assert summary["total_revenue"] >= 10000

    def test_store_isolation(self):
        """多店数据隔离"""
        # 插入另一家店
        report = DailyReport(revenue=5000)
        self.db.insert(report, date=RECENT_DATE, store_id="store_b")

        # 只查 test 店
        rows = self.db.get_history(days=30, store_id="test")
        for r in rows:
            assert r["store_id"] == "test"  # 不会出现 store_b 的数据

    def test_insert_product_rankings(self):
        """商品排名入库"""
        products = [
            {"name": "卡丁车", "count": "20"},
            {"name": "蹦床", "count": "15"},
        ]
        # 用 test 表中已有的 report_id（假设 id=1 存在）
        self.db.insert_product_rankings(
            report_id=1, date="2026-07-10",
            products=products, store_id="test"
        )
        rankings = self.db.get_product_rankings()
        assert len(rankings) >= 2

    def test_get_product_rankings_days_aggregation(self):
        """跨 N 天聚合：最近 2 天销量应正确汇总并排序"""
        d1 = (_TODAY - timedelta(days=2)).strftime("%Y-%m-%d")
        d2 = (_TODAY - timedelta(days=1)).strftime("%Y-%m-%d")
        self.db.insert_product_rankings(
            report_id=1, date=d1,
            products=[{"name": "蹦床", "count": "10"}, {"name": "卡丁车", "count": "5"}],
            store_id="test",
        )
        self.db.insert_product_rankings(
            report_id=1, date=d2,
            products=[{"name": "蹦床", "count": "20"}, {"name": "淘气堡", "count": "8"}],
            store_id="test",
        )
        rows = self.db.get_product_rankings(store_id="test", days=2)
        assert len(rows) >= 3  # 蹦床 + 卡丁车 + 淘气堡
        assert rows[0]["product_name"] == "蹦床"
        assert rows[0]["total_qty"] == 30  # 10 + 20 = 30
        assert rows[0]["days_sold"] == 2
