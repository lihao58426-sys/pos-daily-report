"""
银豹日报推送 - 主程序入口
"""

import logging
import os
import sys
from datetime import datetime

import yaml

from yinbao_crawler import YinbaoCrawler
from wechat_push import WeWorkBotPush, build_markdown_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("daily_report.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

def load_config() -> dict:
    """加载配置文件"""
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main():
    logger.info("=" * 50)
    logger.info("银豹日报推送 开始运行")
    logger.info("=" * 50)

    config = load_config()

    # 第一步：从银豹抓取数据
    crawler = YinbaoCrawler(config)
    data = crawler.run()

    if not data:
        logger.error("数据抓取失败，终止推送")
        sys.exit(1)

    logger.info(f"抓取到数据指标数: {len(data)} 项")
    for key in ["营业实收", "订单总数", "查询时间跨度", "储值卡充值", "次卡销售"]:
        logger.info(f"  {key}: {data.get(key, 'N/A')}")

    # 第二步：构建并推送日报
    push_method = config["push"]["method"]
    logger.info(f"推送方式: {push_method}")

    if push_method == "wework_bot":
        webhook = os.getenv("WEWORK_WEBHOOK_URL", "")
        if not webhook:
            logger.error("未设置环境变量 WEWORK_WEBHOOK_URL")
            sys.exit(1)
        bot = WeWorkBotPush(webhook)

        md_content = build_markdown_report(data)
        logger.info("日报内容构建完成")

        logger.info("正在推送到企业微信群...")
        success = bot.send_markdown(md_content)

        if success:
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
