# POS 日报推送系统

门店营业数据自动抓取 + 企业微信日报推送，每天早 9 点自动发送营业概况。

## 功能

- Playwright 浏览器自动化登录 POS 后台
- 自动抓取：营业实收、订单总数、商品消费排名、储值卡/次卡销售
- 企业微信群机器人 Markdown 日报推送
- Cookie 持久化，减少重复登录
- 异常重试机制

## 技术栈

Python · Playwright · 企业微信 Webhook · YAML

## 环境要求

- Python >= 3.10
- 系统需设置以下环境变量：

| 变量名 | 说明 |
|--------|------|
| `POS_ACCOUNT` | POS 后台登录账号 |
| `POS_PASSWORD` | POS 后台登录密码 |
| `WEWORK_WEBHOOK_URL` | 企业微信群机器人 Webhook 地址 |

## 安装

```bash
git clone https://github.com/lihao58426-sys/pos-daily-report.git
cd pos-daily-report
pip install -r requirements.txt
playwright install chromium
```

## 使用

```bash
python daily_report.py
```

运行后会自动打开浏览器（headless 模式下无界面），抓取当日营业数据并通过企业微信推送。

## 项目结构

```
pos_daily_report/
├── config.yaml          # 配置文件
├── daily_report.py      # 主入口
├── yinbao_crawler.py    # 数据抓取模块
├── wechat_push.py       # 企业微信推送模块
└── requirements.txt     # 依赖清单
```
