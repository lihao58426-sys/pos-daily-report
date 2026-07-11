"""
测试 pusher.py — 企业微信推送（全部 mock，不发真实请求）
"""

import sys
sys.path.insert(0, '..')

import pytest
import requests
from unittest.mock import patch, MagicMock

from pusher import WeWorkBotPush
from exceptions import PushError


class TestWeWorkBotPush:
    """测试企微推送器（mock 所有网络请求）"""

    @patch('pusher.requests.post')
    def test_send_markdown_success(self, mock_post):
        """企微返回成功 → send_markdown 应该返回 True"""
        # 模拟企微返回 {"errcode": 0}
        mock_post.return_value.json.return_value = {"errcode": 0}

        bot = WeWorkBotPush("https://fake-webhook")
        result = bot.send_markdown("# 测试日报")

        assert result == True
        # 确认真的调了 requests.post
        assert mock_post.called

    @patch('pusher.requests.post')
    def test_send_markdown_failure(self, mock_post):
        """企微返回失败 → send_markdown 应该返回 False"""
        mock_post.return_value.json.return_value = {"errcode": -1, "errmsg": "invalid webhook"}

        bot = WeWorkBotPush("https://fake-webhook")
        result = bot.send_markdown("# 测试")

        assert result == False

    @patch('pusher.requests.post')
    def test_send_markdown_network_error(self, mock_post):
        """网络异常 → 抛出 PushError"""
        mock_post.side_effect = requests.ConnectionError("网络断了")

        bot = WeWorkBotPush("https://fake-webhook")
        with pytest.raises(PushError):
            bot.send_markdown("# 测试")

    @patch('pusher.requests.post')
    def test_send_markdown_timeout(self, mock_post):
        """超时 → 抛出 PushError"""
        mock_post.side_effect = requests.Timeout("连接超时")

        bot = WeWorkBotPush("https://fake-webhook")
        with pytest.raises(PushError):
            bot.send_markdown("# 测试")

    @patch('pusher.requests.post')
    def test_payload_format(self, mock_post):
        """验证发出的请求格式是否正确"""
        mock_post.return_value.json.return_value = {"errcode": 0}

        bot = WeWorkBotPush("https://fake-webhook")
        bot.send_markdown("日报内容")

        # 检查 mock_post 被调用时传了什么参数
        call_args = mock_post.call_args
        url = call_args[0][0]                    # 第一个位置参数 = URL
        assert url == "https://fake-webhook"

        # 检查 payload 结构
        import json
        payload = json.loads(call_args[1]['data'])  # data 是关键字参数
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["content"] == "日报内容"
