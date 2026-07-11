"""
测试 models.py — DailyReport / RevenueItem / StoreInfo
"""

import sys
sys.path.insert(0, '..')  # 让测试能找到项目代码

from models import DailyReport, RevenueItem, StoreInfo


class TestDailyReport:
    """测试 DailyReport 数据模型"""

    def test_from_crawler_dict_normal(self):
        """正常数据 → 正确解析"""
        data = {
            "营业实收": "12345",
            "储值卡充值": "5000",
            "次卡销售": "3000",
            "会员付费升级": "0",
            "查询时间跨度": "2026-07-01 ~ 2026-07-31",
        }
        report = DailyReport.from_crawler_dict(data)

        assert report.revenue == 12345.0
        assert report.card_recharge == 5000.0
        assert report.time_card_sales == 3000.0
        assert report.member_upgrade == 0.0
        assert report.time_range == "2026-07-01 ~ 2026-07-31"

    def test_from_crawler_dict_empty(self):
        """空数据 → 不崩溃，返回默认值"""
        report = DailyReport.from_crawler_dict({})
        assert report.revenue == 0.0
        assert report.card_recharge == 0.0
        assert report.time_card_sales == 0.0
        assert report.member_upgrade == 0.0
        assert report.time_range == ""
        assert report.product_ranking == []

    def test_from_crawler_dict_partial(self):
        """部分字段缺失 → 缺失的用默认值"""
        data = {"营业实收": "8000"}
        report = DailyReport.from_crawler_dict(data)
        assert report.revenue == 8000.0
        assert report.card_recharge == 0.0     # 没给 → 默认 0

    def test_from_crawler_dict_bad_number(self):
        """坏数字 → 不崩溃"""
        data = {"营业实收": ""}
        report = DailyReport.from_crawler_dict(data)
        assert report.revenue == 0.0           # 空字符串 → 0

    def test_from_crawler_dict_with_ranking(self):
        """含商品排名 → 正确传入"""
        ranking = [
            {"name": "蹦床", "count": "90"},
            {"name": "卡丁车", "count": "17"},
        ]
        data = {"营业实收": "5000", "商品消费单数排名": ranking}
        report = DailyReport.from_crawler_dict(data)
        assert len(report.product_ranking) == 2
        assert report.product_ranking[0]["name"] == "蹦床"

    def test_revenue_items(self):
        """收入明细：返回全部 RevenueItem（含金额为 0 的）"""
        report = DailyReport(revenue=5000, card_recharge=1000,
                             time_card_sales=800, gift_pack_sales=0,
                             member_upgrade=0)
        items = report.revenue_items
        assert len(items) == 4                  # 4 个项目都有
        assert items[0].name == "储值卡充值"
        assert items[0].amount == 1000.0
        assert items[3].name == "会员付费升级"
        assert items[3].amount == 0.0
