"""
银豹日报推送 — 主入口
====================
职责：只管"按什么顺序、调谁"，不干具体活。

调用链（5 个模块各自做什么）：
  1. config.py  → 读配置（YAML + 环境变量）
  2. crawler.py → 爬数据（Playwright 打开银豹后台抓取）
  3. report.py  → 拼报告（数据 → Markdown 日报）
  4. pusher.py  → 发消息（HTTP POST 到企微群机器人）
  5. main.py    → 你就是它 ← 编排上面 4 步

用法：
  python main.py             正常模式：爬数据 → 拼日报 → 推到企微群
  python main.py --dry-run   演习模式：爬数据 → 拼日报 → 只打印到屏幕，不真推
"""

import logging
import sys

from config import load_config, get_webhook_url
from crawler import YinbaoCrawler
from models import DailyReport
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
    """日报推送主流程"""

    # ── 解析命令行参数 ──
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

    # ── 步骤 2：抓取数据 ── crawler.py ──
    crawler = YinbaoCrawler(config)
    data = crawler.run()

    if not data:
        logger.error("数据抓取失败，终止推送")
        sys.exit(1)

    logger.info(f"抓取到数据指标数: {len(data)} 项")
    for key in ["营业实收", "订单总数", "查询时间跨度", "储值卡充值", "次卡销售"]:
        logger.info(f"  {key}: {data.get(key, 'N/A')}")

    # ── 步骤 3：dict → dataclass ── models.py ──
    report = DailyReport.from_crawler_dict(data)
    logger.info(f"日报数据转换完成: revenue={report.revenue:.0f}, orders={report.order_count}")

    # ── 步骤 4：构建日报内容 ── report.py ──
    md_content = build_markdown_report(report)
    logger.info("日报内容构建完成")

    # ── 步骤 5：推送 ──
    push_method = config["push"]["method"]
    logger.info(f"推送方式: {push_method}")

    if dry_run:
        # ==================== 演习模式 ====================
        # 同样走完爬数据 + 拼报告，但不调 pusher，直接 print
        _print_separator("日报内容预览（以下为将要推送的内容）")
        print(md_content)
        _print_separator("DRY RUN 完成 — 以上内容未实际推送")
        # =================================================

    elif push_method == "wework_bot":
        # ==================== 正常推送 ====================
        webhook = get_webhook_url()
        if not webhook:
            logger.error("未设置环境变量 WEWORK_WEBHOOK_URL")
            sys.exit(1)

        bot = WeWorkBotPush(webhook)
        logger.info("正在推送到企业微信群...")
        success = bot.send_markdown(md_content)

        if success:
            logger.info("日报推送成功！")
        else:
            logger.error("日报推送失败")
            sys.exit(1)
        # =================================================

    else:
        logger.error(f"不支持的推送方式: {push_method}")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("运行完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
