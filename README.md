# POS 日报推送系统

某收银系统（Pospal）后台营业数据自动抓取 + 企业微信日报推送。

> ⚠️ 本项目针对某收银系统系统（beta.pospal.cn）的特定页面结构编写。Playwright 无法自适应 UI 变化——如果某收银系统改版，爬虫需要同步修改选择器。

## 当前状态

### ✅ 已实现

- **营业实收** — 首页自动抓取
- **商品消费单数排名** — Top 5 商品 + 销量
- **关键收入明细** — 储值卡充值 / 次卡销售 / 会员付费升级（现金支付列）
- SQLite 数据库 — 日报表 + 商品排名表，支持历史/趋势/环比查询
- 多门店支持 — config.yaml 配置门店列表，自动循环抓取
- 反检测 — 浏览器指纹隐藏 + UA 伪装 + 真人鼠标轨迹 + 随机延迟
- 定时任务 — 自调度算法：每天 23:10~23:50 随机执行，41 天内不重复（待上云激活）
- 演习模式 — `--dry-run` 只打印不推送
- 企业微信群机器人 Markdown 日报推送
- **AI Agent 问答** — 老板在企微问"本周生意怎么样"，Agent 自动查数据库回答（DeepSeek LLM + 工具调用）
- pytest 测试（21 用例）

## Docker 部署

```bash
docker compose up -d --build
# 调度器每天 23:10~23:50 自动推日报
# Agent 回调服务监听 8003 端口
```

## 技术栈

Python · Playwright · SQLite · DeepSeek API · 企业微信 Webhook/Bot · FastAPI · YAML

## 环境要求

- Python >= 3.14
- 环境变量：

| 变量名 | 说明 |
|--------|------|
| `POS_ACCOUNT` | 某收银系统后台登录账号（总店） |
| `POS_PASSWORD` | 某收银系统后台登录密码（总店） |
| `POS_ACCOUNT_2` | 分店账号（多店时设置） |
| `POS_PASSWORD_2` | 分店密码（多店时设置） |
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
python main.py              # 正常推送
python main.py --dry-run    # 演习模式（只打印不推）
```

## 项目结构

```
pos_daily_report/
├── config.py          # 配置加载
├── crawler.py         # 某收银系统页面抓取（Playwright）
├── models.py          # 数据模型（DailyReport等）
├── database.py        # SQLite 数据库操作
├── report.py          # 日报内容构建
├── pusher.py          # 企业微信推送
├── exceptions.py      # 自定义异常
├── main.py            # 主入口
├── config.yaml        # 配置文件
└── pyproject.toml     # 项目元数据
```
