"""
演示假数据种子脚本 — 一键生成"长得像真业务"的演示数据库
================================================================
面试演示版专用：真实业务数据含客户隐私（5303 个真实会员手机号），
绝不能用真实数据做演示。本脚本生成两份独立的假 SQLite（不碰真实库）：

  - data/demo.db                   → daily_reports + product_rankings（150 天营收 + 商品排名）
  - ../rfm_report/data/demo_rfm.db → transactions（1500 个假会员 + 180 天消费记录）

关键设计：所有日期都相对"今天"往前推——任何时候跑都是"最新数据"，永不过期。

跟 demo 容器配合：容器里设了 POS_DB_PATH / RFM_DB_PATH 环境变量指向假库，
Agent 的 9 个工具就自动查假库（代码零改动）。

用法：
  python seed_demo_db.py
  # 自定义输出路径（跟 Agent 工具的环境变量保持一致）：
  POS_DB_PATH=data/demo.db RFM_DB_PATH=../rfm_report/data/demo_rfm.db python seed_demo_db.py
"""
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

# 固定随机种子 → 同一台机器同一天跑两次，结果一模一样（可复现）
random.seed(42)

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)

# 输出路径（默认与 Agent 工具的 demo 约定一致，可用环境变量覆盖）
POS_DB_PATH = os.getenv("POS_DB_PATH", "data/demo.db")
RFM_DB_PATH = os.getenv("RFM_DB_PATH", os.path.join("..", "rfm_report", "data", "demo_rfm.db"))

STORE_ID = "总店"
POS_DAYS = 150         # 营收历史 150 天（覆盖约 5 个自然月，保证"某月营收"类问题能查到完整月份）

# 商品名（沿用真实业务名，演示讲着自然）+ 日销量区间
PRODUCTS = [
    ("蹦床组合乐园", 60, 150),
    ("儿童卡丁车25圈", 20, 50),
    ("欢乐飞舞", 15, 40),
    ("快乐火车", 15, 40),
    ("恐龙车", 10, 30),
    ("淘气堡", 10, 25),
    ("娃娃机", 5, 15),
    ("钓鱼池", 5, 15),
    ("小火车", 3, 10),
    ("沙池", 3, 8),
]

# RFM 会员分群画像：8 个分群都要有代表性人数
# (分群, 人数, 最近访问距今[天], 月均访问次数, 单次消费区间[元], 入会月份窗口[最早,最晚])
# 入会月份窗口：从今天往前数几个月，控制"什么时候成为新客"，让每月新增会员呈增长曲线
SEGMENTS = [
    ("重要价值客户", 200, (0, 7), 4.0, (150, 400), (0, 5)),
    ("重要唤回客户", 120, (15, 45), 3.0, (150, 400), (1, 6)),
    ("重要发展客户", 150, (0, 14), 0.8, (150, 400), (0, 3)),
    ("重要挽留客户", 100, (60, 120), 1.2, (150, 400), (3, 8)),
    ("一般活跃客户", 180, (0, 7), 3.0, (20, 80), (0, 5)),
    ("一般客户",     120, (15, 60), 2.0, (20, 80), (1, 5)),
    ("新客/低频客户", 200, (0, 14), 0.6, (20, 80), (0, 2)),
    ("流失客户",      250, (90, 180), 1.5, (20, 80), (3, 8)),
    ("普通会员",      180, (0, 60), 1.5, (30, 150), (1, 5)),
]

_SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
_GIVEN = ["伟", "芳", "娜", "敏", "静", "磊", "军", "洋", "勇", "艳", "杰", "娟", "涛", "明", "超", "秀英", "慧", "丹", "浩", "雪"]


def _fake_name() -> str:
    return random.choice(_SURNAMES) + random.choice(_GIVEN)


def _fake_phone(idx: int) -> str:
    """假手机号：真实号段前缀 + 序号后 8 位，保证唯一"""
    prefix = ["138", "139", "150", "151", "158", "159", "177", "186", "188", "189"][idx % 10]
    return f"{prefix}{idx:08d}"


def _month_ago_start(months_ago: int) -> date:
    """N 个月前的 1 号（处理跨年）"""
    y, m = TODAY.year, TODAY.month - months_ago
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def _days_in_month(d: date) -> int:
    nxt = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    return (nxt - d).days


def gen_pos() -> None:
    """生成 POS 假库：150 天日报 + 每天 10 个商品排名"""
    print(f"[1/2] 生成 POS 假数据 → {POS_DB_PATH}")
    os.makedirs(os.path.dirname(POS_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(POS_DB_PATH)
    cur = conn.cursor()
    # 建表（与 database.py 的 schema 完全一致）
    cur.execute("""CREATE TABLE IF NOT EXISTS daily_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store_id TEXT NOT NULL DEFAULT 'default',
        date TEXT NOT NULL,
        revenue REAL NOT NULL DEFAULT 0,
        time_range TEXT DEFAULT '',
        card_recharge REAL DEFAULT 0,
        time_card_sales REAL DEFAULT 0,
        gift_pack_sales REAL DEFAULT 0,
        member_upgrade REAL DEFAULT 0,
        raw_overview TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(store_id, date))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS product_rankings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER NOT NULL,
        store_id TEXT NOT NULL DEFAULT 'default',
        date TEXT NOT NULL,
        rank INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (report_id) REFERENCES daily_reports(id))""")
    # 每次重跑都清空重建 → 幂等
    cur.execute("DELETE FROM product_rankings")
    cur.execute("DELETE FROM daily_reports")

    for i in range(POS_DAYS):
        day = YESTERDAY - timedelta(days=POS_DAYS - 1 - i)  # 90 天前 → 昨天
        date_str = day.isoformat()
        is_weekend = day.weekday() >= 5
        # 营收：周末高、工作日低；整体每月约 +8% 增长
        base = random.uniform(16000, 30000) if is_weekend else random.uniform(8000, 15000)
        growth = 1 + 0.08 * (i / 30)
        revenue = int(base * growth)
        card_recharge = int(revenue * random.uniform(0.12, 0.18))
        time_card_sales = int(revenue * random.uniform(0.06, 0.10))
        gift_pack_sales = int(revenue * random.uniform(0.03, 0.06))
        member_upgrade = random.choice([0, 0, 0, 100, 200])  # 偶尔有会员付费升级

        cur.execute(
            "INSERT INTO daily_reports (store_id, date, revenue, time_range, card_recharge, "
            "time_card_sales, gift_pack_sales, member_upgrade, raw_overview) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (STORE_ID, date_str, revenue, "全天", card_recharge,
             time_card_sales, gift_pack_sales, member_upgrade, ""),
        )
        report_id = cur.lastrowid

        # 商品排名：每天 10 个商品按销量降序
        items = []
        for name, lo, hi in PRODUCTS:
            qty = random.randint(lo, hi)
            if is_weekend and name == "蹦床组合乐园":
                qty = int(qty * 1.3)  # 周末蹦床更火爆
            items.append((name, qty))
        items.sort(key=lambda x: x[1], reverse=True)
        for rank, (name, qty) in enumerate(items, 1):
            cur.execute(
                "INSERT INTO product_rankings (report_id, store_id, date, rank, product_name, quantity) "
                "VALUES (?,?,?,?,?,?)",
                (report_id, STORE_ID, date_str, rank, name, qty),
            )
    conn.commit()
    n_days = cur.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0]
    n_rank = cur.execute("SELECT COUNT(*) FROM product_rankings").fetchone()[0]
    conn.close()
    print(f"  OK daily_reports {n_days} 天 / product_rankings {n_rank} 条")


def gen_rfm() -> None:
    """生成 RFM 假库：1500 个假会员，消费记录覆盖 180 天，8 个分群全覆盖"""
    print(f"[2/2] 生成 RFM 假数据 → {RFM_DB_PATH}")
    os.makedirs(os.path.dirname(RFM_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(RFM_DB_PATH)
    cur = conn.cursor()
    # 建表（与 rfm_report/database.py 的 schema 完全一致）
    cur.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_name TEXT NOT NULL DEFAULT '',
        phone TEXT NOT NULL DEFAULT '',
        trans_date TEXT NOT NULL,
        revenue REAL NOT NULL DEFAULT 0,
        batch TEXT,
        created_at TEXT)""")
    cur.execute("DELETE FROM transactions")

    now = datetime.now().isoformat(timespec="seconds")
    batch = f"demo-{YESTERDAY:%Y%m%d}"
    rows = []
    idx = 0
    for seg, n, (rec_lo, rec_hi), monthly_visits, (m_lo, m_hi), (jk_min, jk_max) in SEGMENTS:
        for _ in range(n):
            name = _fake_name()
            phone = _fake_phone(idx)
            idx += 1
            # 最后访问日落在分群要求的 recency 区间（相对今天）
            last_visit = YESTERDAY - timedelta(days=random.randint(rec_lo, rec_hi))
            # 入会月份：窗口内"越近越多"→ 每月新增会员呈增长曲线
            weights = [1.0 / (k + 1) for k in range(jk_min, jk_max + 1)]
            k = random.choices(range(jk_min, jk_max + 1), weights=weights)[0]
            ms = _month_ago_start(k)
            join_date = ms + timedelta(days=random.randint(0, _days_in_month(ms) - 1))
            if join_date > last_visit:
                join_date = last_visit - timedelta(days=random.randint(0, 7))  # 兜底：入会不晚于最后访问
            span_days = (last_visit - join_date).days
            total_visits = max(1, int((span_days / 30) * monthly_visits * random.uniform(0.8, 1.2)))
            offsets = sorted(random.sample(range(span_days + 1), min(total_visits, span_days + 1)))
            if offsets and offsets[-1] != span_days:
                offsets[-1] = span_days  # 保证最后访问日 = 分群要求的最近访问
            for d in offsets:
                vd = join_date + timedelta(days=d)
                revenue = round(random.uniform(m_lo, m_hi), 2)
                ts = f"{vd} {random.randint(9, 21):02d}:{random.randint(0, 59):02d}:{random.randint(0, 59):02d}"
                rows.append((name, phone, ts, revenue, batch, now))
    cur.executemany(
        "INSERT INTO transactions (member_name, phone, trans_date, revenue, batch, created_at) "
        "VALUES (?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    n_tx = cur.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    member_count = sum(n for _, n, *_ in SEGMENTS)
    print(f"  OK transactions {n_tx} 条 / {member_count} 个假会员")


if __name__ == "__main__":
    print("=" * 50)
    print("  面试演示假数据生成")
    print("=" * 50)
    gen_pos()
    gen_rfm()
    print("完成！启动 demo：")
    print(f"  POS_DB_PATH={POS_DB_PATH} RFM_DB_PATH={RFM_DB_PATH} python web_agent.py")
