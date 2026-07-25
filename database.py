"""
数据持久化模块
=============
职责：把日报数据存进 SQLite，支持历史查询和趋势分析。

原来：数据抓完 → push 到企微 → 丢了（下次想查上个月的？没了）
现在：数据抓完 → 存入 SQLite → push 到企微 → 随时能查历史

SQLite 是什么？
  - 一个 .db 文件就是整个数据库，不需要装 MySQL/PostgreSQL
  - Python 自带 sqlite3 模块，不用 pip install 任何东西
  - 存 10 万条记录毫无压力

用法：
  db = ReportDatabase("daily_report.db")
  db.insert(report)                          # 存一条
  rows = db.get_history(days=30)             # 查最近 30 天
  trend = db.get_trend(days=30)              # 趋势数据
  summary = db.get_summary()                 # 本月统计
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta

from models import DailyReport

logger = logging.getLogger(__name__)

# PostgreSQL 是可选的——只有设了 DATABASE_URL 才启用
try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False


def _build_postgres_url() -> str | None:
    """从环境变量拼出 PostgreSQL 连接地址

    两种设法（选一种就行）：
      方式 A：DATABASE_URL=postgresql://user:pass@host:5432/dbname
      方式 B：分开设 PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD

    返回：连接字符串，如果都没设就返回 None（表示用 SQLite）
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url

    # 方式 B：分开设的环境变量
    host = os.getenv("PGHOST", "")
    if not host:
        return None

    dbname = os.getenv("PGDATABASE", "pos_daily_report")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "")
    port = os.getenv("PGPORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


class ReportDatabase:
    """日报数据库操作

    自动选择后端：
      - 设了 DATABASE_URL 或 PGHOST → PostgreSQL
      - 没设 → SQLite（默认，跟以前一样）
    """

    def __init__(self, db_path: str = "daily_report.db"):
        """打开数据库连接，自动建表"""
        pg_url = _build_postgres_url()

        if HAS_POSTGRES and pg_url:
            # ── PostgreSQL 后端 ──
            self.conn = psycopg2.connect(pg_url)
            self._backend = "postgresql"
            logger.info(f"数据库: PostgreSQL ({pg_url.split('@')[1] if '@' in pg_url else pg_url})")
        else:
            # ── SQLite 后端（默认）──
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row  # 查询结果用 row["列名"] 访问
            self._backend = "sqlite"
            logger.info(f"数据库: SQLite ({db_path})")

        self._init_table()

    # ==================== 辅助 ====================
    def _ph(self) -> str:
        """SQL 占位符——SQLite 用 ?，PostgreSQL 用 %s"""
        return "%s" if self._backend == "postgresql" else "?"

    # ==================== 建表 ====================
    def _init_table(self) -> None:
        """创建日报表（如果不存在）

        自动适配后端：
          - SQLite:     INTEGER PRIMARY KEY AUTOINCREMENT
          - PostgreSQL: SERIAL PRIMARY KEY
        """
        pk = "SERIAL PRIMARY KEY" if self._backend == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id              {pk},
                store_id        TEXT    NOT NULL DEFAULT 'default',
                date            TEXT    NOT NULL,
                revenue         REAL    NOT NULL DEFAULT 0,
                time_range      TEXT    DEFAULT '',
                card_recharge   REAL    DEFAULT 0,
                time_card_sales REAL    DEFAULT 0,
                gift_pack_sales REAL    DEFAULT 0,
                member_upgrade  REAL    DEFAULT 0,
                raw_overview    TEXT    DEFAULT '',
                created_at      TEXT    DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 商品排名表：一次日报对应多条商品排名记录
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS product_rankings (
                id              {pk},
                report_id       INTEGER NOT NULL,
                store_id        TEXT    NOT NULL DEFAULT 'default',
                date            TEXT    NOT NULL,
                rank            INTEGER NOT NULL,
                product_name    TEXT    NOT NULL,
                quantity        INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (report_id) REFERENCES daily_reports(id)
            )
        """)
        self.conn.commit()
        logger.info(f"数据库就绪 ({self._backend})")

    # ==================== 写入 ====================
    def insert(self, report: DailyReport, date: str | None = None, store_id: str = "default") -> int:
        """把一条日报写入数据库

        Args:
            report: DailyReport 对象（来自 models.py）
            date: 日期字符串，默认今天
            store_id: 门店标识（如 "xianyang"）

        Returns:
            新插入行的 id
        """
        ph = self._ph()
        date = date or datetime.now().strftime("%Y-%m-%d")
        cursor = self.conn.execute(
            f"""
            INSERT INTO daily_reports
                (store_id, date, revenue, time_range,
                 card_recharge, time_card_sales, gift_pack_sales, member_upgrade,
                 raw_overview)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            """,
            (
                store_id,
                date,
                report.revenue,
                report.time_range,
                report.card_recharge,
                report.time_card_sales,
                report.gift_pack_sales,
                report.member_upgrade,
                report.raw_overview,
            ),
        )
        self.conn.commit()
        logger.info(f"日报已入库: id={cursor.lastrowid}, revenue={report.revenue:.0f}")
        return cursor.lastrowid

    # ==================== 查询：历史 ====================
    def get_history(self, days: int = 30, store_id: str | None = None) -> list[dict]:
        """查最近 N 天的日报记录

        Args:
            days: 查多少天，默认 30
            store_id: 门店ID，None=查所有店

        Returns:
            按日期倒序的日报列表
        """
        if store_id:
            cursor = self.conn.execute(
                "SELECT store_id, date, revenue, card_recharge, time_card_sales, member_upgrade "
                f"FROM daily_reports WHERE store_id = {ph} AND date >= {ph} ORDER BY date DESC",
                (store_id, (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")),
            )
        else:
            cursor = self.conn.execute(
                "SELECT store_id, date, revenue, card_recharge, time_card_sales, member_upgrade "
                f"FROM daily_reports WHERE date >= {ph} ORDER BY date DESC",
                ((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),),
            )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 查询：趋势 ====================
    def get_trend(self, days: int = 30) -> list[dict]:
        """查最近 N 天的营收趋势（给图表用）

        和 get_history 的区别：按日期升序，方便画折线图。

        Returns:
            [{"date": "2026-07-01", "revenue": 12345}, ...]
        """
        cursor = self.conn.execute(
            f"""
            SELECT date, revenue
            FROM daily_reports
            WHERE date >= {self._ph()}
            ORDER BY date ASC
            """,
            ((datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 查询：环比 ====================
    def get_comparison(self) -> dict:
        """本月 vs 上月环比

        自动计算：
          - 本月到目前的营收总额和日均
          - 上个月同期的营收总额和日均
          - 环比涨幅百分比

        Returns:
            {
                "this_month_total": 350000,
                "last_month_total": 300000,
                "change_pct": 16.7
            }
        """
        today = datetime.now()
        # 本月
        this_month_start = today.replace(day=1).strftime("%Y-%m-%d")
        this_data = self.conn.execute(
            f"""
            SELECT SUM(revenue) as total, COUNT(*) as days
            FROM daily_reports
            WHERE date >= {self._ph()}
            """,
            (this_month_start,),
        ).fetchone()

        # 上月
        if today.month == 1:
            last_month_start = f"{today.year - 1}-12-01"
            last_month_end = f"{today.year - 1}-12-{min(today.day, 31):02d}"
        else:
            last_month_start = f"{today.year}-{today.month - 1:02d}-01"
            last_month_end = f"{today.year}-{today.month - 1:02d}-{min(today.day, 31):02d}"

        last_data = self.conn.execute(
            f"""
            SELECT SUM(revenue) as total, COUNT(*) as days
            FROM daily_reports
            WHERE date >= {self._ph()} AND date <= {self._ph()}
            """,
            (last_month_start, last_month_end),
        ).fetchone()

        this_total = this_data["total"] or 0
        last_total = last_data["total"] or 0
        change_pct = ((this_total - last_total) / last_total * 100) if last_total > 0 else 0

        logger.info(
            f"环比: 本月 ¥{this_total:.0f} vs 上月 ¥{last_total:.0f} "
            f"({'+' if change_pct >= 0 else ''}{change_pct:.1f}%)"
        )

        return {
            "this_month_total": this_total,
            "this_month_days": this_data["days"],
            "last_month_total": last_total,
            "last_month_days": last_data["days"],
            "change_pct": round(change_pct, 1),
        }

    # ==================== 查询：汇总 ====================
    def get_summary(self) -> dict:
        """获取整体统计摘要

        Returns:
            {"total_days": 50, "total_revenue": 500000, "avg_daily": 10000}
        """
        row = self.conn.execute(
            """
            SELECT COUNT(*) as total_days,
                   SUM(revenue) as total_revenue,
                   AVG(revenue) as avg_daily
            FROM daily_reports
            """
        ).fetchone()
        return {
            "total_days": row["total_days"],
            "total_revenue": row["total_revenue"] or 0,
            "avg_daily": round(row["avg_daily"] or 0, 0),
        }

    # ==================== 商品排名 ====================
    def insert_product_rankings(self, report_id: int, date: str, products: list[dict], store_id: str = "default") -> None:
        """保存商品排名数据"""
        ph = self._ph()
        for rank, prod in enumerate(products, 1):
            self.conn.execute(
                f"INSERT INTO product_rankings (report_id, store_id, date, rank, product_name, quantity) "
                f"VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                (report_id, store_id, date, rank, prod.get("name", ""), int(prod.get("count", 0))),
            )
        self.conn.commit()
        logger.info(f"商品排名已入库: {len(products)} 条")

    def get_product_rankings(self, date: str | None = None) -> list[dict]:
        """查询某天的商品排名，默认查最近一天"""
        if date:
            cursor = self.conn.execute(
                f"SELECT rank, product_name, quantity FROM product_rankings "
                f"WHERE date = {self._ph()} ORDER BY rank",
                (date,),
            )
        else:
            cursor = self.conn.execute(
                "SELECT date, rank, product_name, quantity FROM product_rankings "
                "WHERE date = (SELECT MAX(date) FROM product_rankings) ORDER BY rank"
            )
        return [dict(row) for row in cursor.fetchall()]

    # ==================== 收尾 ====================
    def close(self) -> None:
        """关闭数据库连接"""
        self.conn.close()

    def __enter__(self):
        """上下文管理器入口：with ReportDatabase() as db:"""
        return self

    def __exit__(self, *args):
        """上下文管理器出口：自动关闭连接"""
        self.close()
