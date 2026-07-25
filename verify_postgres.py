"""验证 PostgreSQL 模式下 database.py 能正常工作"""
import os

# 模拟生产环境——设 PostgreSQL 连接信息
os.environ["DATABASE_URL"] = "postgresql://postgres:test123@localhost:5432/pos_daily_report"

from database import ReportDatabase
from models import DailyReport

print("1. 连接 PostgreSQL...")
db = ReportDatabase()
print(f"   后端: {db._backend}")
assert db._backend == "postgresql", f"应该是 postgresql，实际是 {db._backend}"

print("2. 插入测试数据...")
report = DailyReport(
    revenue=12345.67,
    time_range="全天",
    card_recharge=1000,
    time_card_sales=500,
    gift_pack_sales=300,
    member_upgrade=200,
    raw_overview="测试数据",
)
row_id = db.insert(report, date="2026-07-25", store_id="test-store")
print(f"   插入成功: id={row_id}")
assert row_id is not None

print("3. 查询历史...")
rows = db.get_history(days=1)
print(f"   查到 {len(rows)} 条记录")
assert len(rows) > 0, "应该至少查到一条"
assert rows[0]["revenue"] == 12345.67, f"金额不对: {rows[0]['revenue']}"
assert rows[0]["store_id"] == "test-store"

print("4. 插入商品排名...")
db.insert_product_rankings(row_id, "2026-07-25", [
    {"name": "会员卡", "count": 10},
    {"name": "次卡", "count": 5},
])
rankings = db.get_product_rankings("2026-07-25")
print(f"   查到 {len(rankings)} 条排名")
assert len(rankings) >= 2, f"至少应该有 2 条，实际 {len(rankings)}"

print("5. 查询趋势...")
trend = db.get_trend(days=1)
assert len(trend) > 0

print("6. 查询环比...")
comp = db.get_comparison()
assert comp is not None

print("7. 查询汇总...")
summary = db.get_summary()
assert summary["total_days"] >= 1

db.close()
print("\n✅ 全部通过——PostgreSQL 后端工作正常")
