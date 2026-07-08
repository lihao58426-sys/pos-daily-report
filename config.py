"""
配置加载模块
-----------
职责：读 config.yaml + 读环境变量，给其他模块提供配置信息。

为什么单独拆出来？
  - 原来 load_config() 写在 daily_report.py 里，只有 main 能用。
  - 拆出来后，crawler、pusher、report 任何模块都能 import 它拿配置。
  - 以后如果要换配置格式（比如换 .toml 或 .env），只改这一个文件。
"""

import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认配置文件名
CONFIG_PATH = "config.yaml"


def load_config(path: str = CONFIG_PATH) -> dict[str, Any]:
    """加载 YAML 配置文件

    原来：写在 daily_report.py 第 25-28 行
    现在：独立成一个函数，任何模块都能 import 使用

    Args:
        path: 配置文件路径，默认当前目录下的 config.yaml

    Returns:
        配置字典，例如：
        {
            "push": {"method": "wework_bot"},
            "run": {"headless": False, "timeout": 30000}
        }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        config: dict[str, Any] = yaml.safe_load(f)

    logger.info(f"配置加载成功: {path}")
    return config


def get_webhook_url() -> str:
    """从环境变量读取企微 Webhook 地址

    安全考虑：URL 里有 key，不能写在 config.yaml 里（会被 git 提交）。
    所以用环境变量，代码里只写 os.getenv("WEWORK_WEBHOOK_URL")。
    """
    return os.getenv("WEWORK_WEBHOOK_URL", "")


def get_pos_credentials() -> tuple[str, str]:
    """从环境变量读取银豹后台的账号和密码

    Returns:
        (account, password) — 两个都是字符串，没设置就返回空字符串
    """
    return os.getenv("POS_ACCOUNT", ""), os.getenv("POS_PASSWORD", "")
