"""
企业微信群机器人消息推送模块
"""

import json
import logging
import re
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

class WeWorkBotPush:
    """企业微信群机器人推送"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send_markdown(self, content: str) -> bool:
        """发送 Markdown 消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content},
        }
        return self._send(payload)

    def _send(self, payload: dict) -> bool:
        """发送消息到企业微信"""
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
        except Exception as e:
            logger.error(f"推送请求异常: {e}")
            return False

def _parse_product_table(raw_text: str) -> list:
    """从商品销售统计的原始表格文本中解析项目数据"""
    lines = raw_text.strip().splitlines()
    products = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ["商品名", "商品名称", "名称\t", "销量", "金额\t", "序号"]):
            continue
        nums = re.findall(r"[\d.]+", line)
        if not nums:
            continue
        words = re.split(r"\s+", line)
        name_parts = []
        for w in words:
            if re.search(r"^\d+\.?\d*$", w):
                break
            name_parts.append(w)
        name = "".join(name_parts).strip()
        if not name:
            continue
        qty = nums[0] if len(nums) >= 1 else ""
        products.append({"name": name, "qty": qty})
    try:
        products.sort(key=lambda x: float(x.get("qty", 0) or 0), reverse=True)
    except Exception:
        pass
    return products

def build_markdown_report(data: dict, date_str: str = None) -> str:
    """构建游乐场日报 Markdown"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%H:%M")

    revenue = data.get("营业实收", "0")
    order_count = data.get("订单总数", "0")
    time_range = data.get("查询时间跨度", "")

    lines = []
    lines.append(f"# 游乐场日报")
    lines.append(f"> 日期：{date_str}")
    if time_range:
        lines.append(f"> 查询时间：{time_range}")
    lines.append("")

    lines.append(f"## 今日营业实收：**{revenue}** 元")
    lines.append(f"订单总数：{order_count} 笔")
    lines.append("")

    key_revenues = [
        ("储值卡充值", data.get("储值卡充值", "0")),
        ("次卡销售", data.get("次卡销售", "0")),
        ("礼品包销售", data.get("礼品包销售", "0")),
        ("会员付费升级", data.get("会员付费升级", "0")),
    ]
    key_revenues = [(k, v) for k, v in key_revenues if v and float(v) > 0]
    if key_revenues:
        lines.append("## 关键收入")
        lines.append("")
        lines.append(f"| 项目 | 金额 |")
        lines.append(f"| --- | ---: |")
        for name, val in key_revenues:
            lines.append(f"| {name} | {val} 元 |")
        lines.append("")

    if "_商品销售_原始" in data:
        products = _parse_product_table(data["_商品销售_原始"])
        if products:
            lines.append("## 各项目销量")
            lines.append("")
            lines.append(f"| 项目 | 销量 |")
            lines.append(f"| --- | ---: |")
            for prod in products:
                name = prod.get("name", "")
                qty = prod.get("qty", "0")
                lines.append(f"| {name} | {qty} |")
            lines.append("")

    lines.append("---")
    lines.append(f" 系统自动生成 · {now_str}")

    return "\n".join(lines)