# POS 日报推送系统

银豹（Pospal）后台营业数据自动抓取 + 企业微信日报推送。

> ⚠️ 本项目针对银豹系统（beta.pospal.cn）的特定页面结构编写。Playwright 无法自适应 UI 变化——如果银豹改版，爬虫需要同步修改选择器。

## 当前状态

### ✅ 已实现

- Playwright 自动登录银豹后台（支持 Cookie 持久化）
- 首页抓取：**营业实收**、**订单总数**
- 企业微信群机器人 Markdown 日报推送
- 登录失败自动重试

### 🚧 开发中（暂不可用）

- **商品消费单数排名**：页面需滚动加载，滚动触发不稳定，暂时无法可靠提取
- **储值卡充值 / 次卡销售金额**：需从"更多→营业概况明细"的表格中定位，当前提取逻辑不稳定

### 📋 计划中

- 多门店支持
- APScheduler 定时自动运行
- SQLite 数据库持久化（历史趋势查询）
- 环比昨日数据对比
- Docker 打包

## 技术栈

Python · Playwright · 企业微信 Webhook · YAML

## 环境要求

- Python >= 3.10
- 环境变量：

| 变量名 | 说明 |
|--------|------|
| `POS_ACCOUNT` | 银豹后台登录账号 |
| `POS_PASSWORD` | 银豹后台登录密码 |
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

## 项目结构

```
pos_daily_report/
├── config.yaml          # 配置文件
├── daily_report.py      # 主入口
├── yinbao_crawler.py    # 银豹页面抓取模块
├── wechat_push.py       # 企业微信推送模块
├── pyproject.toml       # 项目元数据
└── requirements.txt     # 依赖清单
```

## 更新

代码修改后提交推送：

```bash
git add .
git commit -m "描述你改了什么"
git push
```
