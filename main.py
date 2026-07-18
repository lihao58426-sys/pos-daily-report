"""
银豹日报推送 — 主入口
====================
职责：只管"按什么顺序、调谁"，不干具体活。

调用链（6 个模块各自做什么）：
  1. config.py   → 读配置（YAML + 环境变量）
  2. crawler.py  → 爬数据（Playwright 打开银豹后台抓取）
  3. models.py   → dict → DailyReport dataclass
  4. database.py → 存入 SQLite（永久保存，随时可查历史）
  5. report.py   → 拼报告（数据 → Markdown 日报）
  6. pusher.py   → 发消息（HTTP POST 到企微群机器人）
  7. main.py     → 你就是它 ← 编排上面 6 步

用法：
  python main.py             正常模式：爬数据 → 存库 → 拼日报 → 推到企微群
  python main.py --dry-run   演习模式：爬数据 → 存库 → 拼日报 → 只打印到屏幕
  python main.py --summary   查看历史汇总（不爬虫，只读数据库）
"""

import logging
import sys
import time
import random
from datetime import datetime

from config import load_config, get_webhook_url
from crawler import YinbaoCrawler
from models import DailyReport
from database import ReportDatabase
from report import build_markdown_report
from pusher import WeWorkBotPush

# ── 日志配置（入口文件负责初始化日志系统） ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("daily_report.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _print_separator(title: str = "") -> None:
    """打印分隔线，让控制台输出更易读"""
    if title:
        print(f"\n{'─' * 50}")
        print(f"  {title}")
        print(f"{'─' * 50}")
    else:
        print(f"{'─' * 50}")


def main() -> None:
    """日报推送主流程 — 支持多店"""

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=" * 50)
        print("  DRY RUN 模式 — 只演习，不真推")
        print("=" * 50)
    else:
        logger.info("=" * 50)
        logger.info("银豹日报推送 开始运行")
        logger.info("=" * 50)

    # ── 步骤 1：加载配置 ── config.py ──
    config = load_config()
    stores = config.get("stores", [{"id": "default", "name": "", "account_env": "POS_ACCOUNT", "password_env": "POS_PASSWORD"}])

    # ── 步骤 2：逐店抓取 → 存库 ──
    all_reports = []
    for store in stores:
        store_id = store["id"]
        store_name = store["name"]
        logger.info(f"\n{'─' * 40}")
        logger.info(f"正在处理: {store_name} ({store_id})")
        logger.info(f"{'─' * 40}")

        crawler = YinbaoCrawler(config, store=store)
        data = crawler.run()

        if not data:
            logger.warning(f"[{store_name}] 数据抓取失败，跳过")
            continue

        report = DailyReport.from_crawler_dict(data)
        logger.info(f"[{store_name}] revenue={report.revenue:.0f}")

        with ReportDatabase("data/daily_report.db") as db:
            row_id = db.insert(report, store_id=store_id)
            if report.product_ranking:
                db.insert_product_rankings(row_id, datetime.now().strftime("%Y-%m-%d"), report.product_ranking, store_id=store_id)
            summary = db.get_summary()
            if summary["total_days"] > 1:
                logger.info(f"[{store_name}] 历史: {summary['total_days']}天 / 累计¥{summary['total_revenue']:,.0f} / 日均¥{summary['avg_daily']:,.0f}")

        all_reports.append((store_name, report))

    if not all_reports:
        logger.error("所有门店数据抓取均失败，终止推送")
        sys.exit(1)

    # ── 步骤 3：构建日报 ──
    if len(all_reports) == 1:
        _, report = all_reports[0]
        md_content = build_markdown_report(report)
    else:
        parts = []
        for store_name, report in all_reports:
            parts.append(f"## {store_name}")
            parts.append(build_markdown_report(report))
            parts.append("")
        md_content = "\n".join(parts)
    logger.info("日报内容构建完成")

    # ── 步骤 4：推送 ──
    push_method = config["push"]["method"]

    if dry_run:
        _print_separator("日报内容预览")
        print(md_content)
        _print_separator("DRY RUN 完成 — 以上内容未实际推送")

    elif push_method == "wework_bot":
        webhook = get_webhook_url()
        if not webhook:
            logger.error("未设置环境变量 WEWORK_WEBHOOK_URL")
            sys.exit(1)
        bot = WeWorkBotPush(webhook)
        logger.info("正在推送到企业微信群...")
        if bot.send_markdown(md_content):
            logger.info("日报推送成功！")
        else:
            logger.error("日报推送失败")
            sys.exit(1)

    else:
        logger.error(f"不支持的推送方式: {push_method}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("运行完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()


# ============================================================
# 定时任务模式（上云后运行：python main.py --scheduler &）
# ============================================================
# 效果：程序不退出，每天 23:10~23:50 之间随机时间跑一次
#       41 个分钟数用完一遍之前绝不重复，用完洗牌再开下一轮
# 原理：自调度 — 每次跑完算下次几点跑，sleep 到点再跑
# ============================================================
if "--scheduler" in sys.argv:
    from datetime import timedelta as _td

    _pool: list[int] = []            # 当前轮次剩余可用的分钟数
    _used_seconds: dict[int, list[int]] = {}  # 每个分钟用过的秒数

    def _refill_pool() -> None:
        """重新填满可选池（41 个分钟数全部洗牌），
        并保证新一轮的第一个和上一轮的最后一个不重复。"""
        global _pool
        last = _pool[0] if len(_pool) == 1 else None
        full = list(range(10, 51))
        random.shuffle(full)
        if last is not None and full[0] == last:
            random.shuffle(full)
        _pool = full

    def _next_run_time() -> datetime:
        """每次从剩余池随机取一个分钟 + 随机秒。
        同一分钟再次出现时（跨轮），确保秒跟上次不同。
        银豹日志：23:17:43, 23:41:08, 23:25:31... 永远不重复。"""
        if not _pool:
            _refill_pool()
        minute = _pool.pop()
        # 选秒：避开这个分钟之前用过的秒数
        used = _used_seconds.get(minute, [])
        available = [s for s in range(60) if s not in used]
        second = random.choice(available)
        _used_seconds.setdefault(minute, []).append(second)

        now = datetime.now()
        target = now.replace(hour=23, minute=minute, second=second, microsecond=0)
        if target <= now:
            target += _td(days=1)
        return target

    logger.info("定时任务已启动：每天 23:10~23:50 随机，41天内绝不重复")
    while True:
        target = _next_run_time()
        wait = (target - datetime.now()).total_seconds()
        logger.info(
            f"下次执行: {target.strftime('%m-%d %H:%M')} "
            f"（{wait/60:.0f} 分钟后）[剩余 {len(_pool)} 个可选]"
        )
        time.sleep(wait)
        try:
            main()
        except Exception as _e:
            logger.error(f"定时执行异常: {_e}")
