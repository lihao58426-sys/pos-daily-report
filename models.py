"""
数据模型 — dataclass 定义
=========================
职责：定义项目中所有结构化数据类型，替代裸 dict。

为什么用 dataclass？
  - 字段名是 Python 属性 → 编辑器自动补全，不会拼错 key
  - 类型标注 → 一眼知道每个字段是 str 还是 float
  - dict.get("某个key") → 拼错了不报错、默默返回默认值
  - report.revenue → 拼错立刻标红波浪线

原来的方式：data["营业实收"]      ← 字符串 key，容易拼错
现在的方式：report.revenue       ← 属性访问，自动补全
"""

from dataclasses import dataclass, field


@dataclass
class RevenueItem:
    """单条收入明细（如 "储值卡充值: 5000 元"）"""
    name: str       # 项目名称
    amount: float   # 金额（元）


@dataclass
class DailyReport:
    """日报数据 — 爬虫产出的结构化日报

    替代原来 crawler.run() 返回的 dict。
    """
    revenue: float = 0.0           # 营业实收（元）
    time_range: str = ""           # 查询时间跨度
    card_recharge: float = 0.0     # 储值卡充值
    time_card_sales: float = 0.0   # 次卡销售
    gift_pack_sales: float = 0.0   # 礼品包销售
    member_upgrade: float = 0.0    # 会员付费升级
    product_ranking: list[dict] = field(default_factory=list)  # 商品消费排名
    raw_overview: str = ""         # 营业概况原始文本（调试用）
    raw_product_ranking: str = ""  # 商品排名原始文本（调试用）

    @classmethod
    def from_crawler_dict(cls, data: dict) -> "DailyReport":
        """从爬虫返回的 dict 构造 DailyReport

        爬虫返回的 key 是中文（银豹页面的字段名），这里做一次转换。
        """
        return cls(
            revenue=float(data.get("营业实收", 0) or 0),
            time_range=str(data.get("查询时间跨度", "")),
            card_recharge=float(data.get("储值卡充值", 0) or 0),
            time_card_sales=float(data.get("次卡销售", 0) or 0),
            gift_pack_sales=float(data.get("礼品包销售", 0) or 0),
            member_upgrade=float(data.get("会员付费升级", 0) or 0),
            product_ranking=data.get("商品消费单数排名", []),
            raw_overview=str(data.get("_营业概况表_原始", "")),
        )

    @property
    def revenue_items(self) -> list[RevenueItem]:
        """返回金额 > 0 的收入明细列表（供 report 拼表格用）"""
        items = [
            ("储值卡充值", self.card_recharge),
            ("次卡销售", self.time_card_sales),
            ("礼品包销售", self.gift_pack_sales),
            ("会员付费升级", self.member_upgrade),
        ]
        return [RevenueItem(name=n, amount=a) for n, a in items]


@dataclass
class StoreInfo:
    """门店信息 — 为阶段二多店支持做准备"""
    store_id: str = "default"
    store_name: str = ""
    pos_account: str = ""   # 银豹账号（从环境变量读取，不硬编码）
