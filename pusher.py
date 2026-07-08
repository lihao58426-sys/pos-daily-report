"""
消息推送模块
-----------
职责：只负责"怎么把消息发出去"，不关心消息内容是什么。

为什么从 wechat_push.py 拆出来？
  - 原来 WeWorkBotPush 和 build_markdown_report() 混在一起
  - 推送是"怎么发"，报告是"发什么"——两个维度的变化
  - 以后换钉钉/飞书推送：只改这个文件，report.py 不动
"""

import json
import logging

import requests

from exceptions import PushError

logger = logging.getLogger(__name__)


class WeWorkBotPush:
    """企业微信群机器人推送

    用法：
        bot = WeWorkBotPush(webhook_url)
        bot.send_markdown("# 你好\n这是日报内容")
    """

    def __init__(self, webhook_url: str):
        """初始化推送器

        Args:
            webhook_url: 企微群机器人的 Webhook 地址
                         （从环境变量 WEWORK_WEBHOOK_URL 读取）
        """
        self.webhook_url = webhook_url

    def send_markdown(self, content: str) -> bool:
        """发送 Markdown 格式消息到企微群

        Args:
            content: Markdown 格式的消息内容（由 report.py 生成）

        Returns:
            True 表示发送成功，False 表示失败
        """
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        return self._send(payload)

    def _send(self, payload: dict) -> bool:
        """底层 HTTP 发送逻辑

        Args:
            payload: 企微机器人消息体（JSON 格式）

        Returns:
            True 表示发送成功，False 表示失败
        """
        try:
            resp = requests.post(
                self.webhook_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=10,
            )
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("企业微信消息发送成功！")
                return True
            else:
                logger.error(f"发送失败: {result}")
                return False
        except requests.ConnectionError as e:
            raise PushError(f"网络不通，无法连接企微: {e}") from e
        except requests.Timeout as e:
            raise PushError(f"企微响应超时: {e}") from e
        except requests.RequestException as e:
            raise PushError(f"推送请求异常: {e}") from e
