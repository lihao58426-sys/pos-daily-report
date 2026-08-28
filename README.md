# POS 日报推送 + AI 经营问答 Agent

银豹（Pospal）后台营业数据自动抓取 + 企业微信日报推送 + DeepSeek 驱动的经营问答 Agent。

> ⚠️ 本项目针对银豹后台（beta.pospal.cn）的特定页面结构编写，Playwright 无法自适应 UI 变化——银豹改版时爬虫需同步修改选择器（见 [crawler.py](crawler.py)）。

---

## 项目由两部分组成

| 子系统 | 入口 | 作用 | 状态 |
|--------|------|------|------|
| **① 日报管线** | `main.py` | 每天定时抓数据 → 存库 → 推企业微信群 | ✅ 可用（群机器人 Webhook 正常） |
| **② AI 问答 Agent** | `web_agent.py` | 老板用自然语言问数据，Agent 查库回答 | ✅ 可用（浏览器入口，端口 8005） |
| （原企微回调） | `callback_server.py` | 企微自建应用回调入口，端口 8003 | ⚠️ 被企微「三方服务商资质」卡住，个人无法开通 |

> **关键区分**：日报推送用的是**企业微信群机器人 Webhook**（`WEWORK_WEBHOOK_URL`，无需资质，正常可用）；而 Agent 问答原本想用**企微自建应用回调**（`callback_server.py`，需要三方服务商资质，个人开不了）。因此 Agent 的对话入口已改为**浏览器网页**（`web_agent.py`）。

---

## 核心架构 / 调用链

### ① 日报管线（`main.py` 编排，7 个模块各司其职）

```
银豹后台 → crawler.py(抓数据) → models.py(dict→DailyReport) → database.py(存库)
                                                                    ↓
           pusher.py(发企微) ← report.py(拼日报 Markdown) ←──（历史可查）
```

| 顺序 | 模块 | 职责 |
|------|------|------|
| 1 | `config.py` | 读 `config.yaml` + 环境变量（账号/密码/webhook） |
| 2 | `crawler.py` | Playwright 模拟浏览器登录银豹，抓营业实收 / 商品排名 / 关键收入 |
| 3 | `models.py` | 爬虫返回的 dict → `DailyReport` dataclass |
| 4 | `database.py` | 存 SQLite（或 PostgreSQL），支持历史/趋势/环比/汇总查询 |
| 5 | `report.py` | 数据 → Markdown 日报 |
| 6 | `pusher.py` | HTTP POST 到企微群机器人 |
| 7 | `main.py` | 编排以上 6 步，含 `--scheduler` 自调度定时任务 |

### ② AI 问答 Agent（`web_agent.py` → `agent.py` 循环）

```
浏览器提问 → web_agent.py(/api/chat) → agent.py(循环：LLM思考→选工具→执行→再思考)
                                          ├── agent_llm.py     调 DeepSeek API
                                          ├── agent_tools.py    5 个会计工具（营收/趋势/环比/汇总/商品排名）
                                          ├── agent_tools_rfm.py 4 个 RFM 会员工具（分群/明细/趋势/新增）
                                          └── 数据库（POS 库 + RFM 会员库）
```

Agent 共 **9 个工具**（会计 5 + RFM 4），`MAX_TURNS=5` 护栏防死循环。

---

## 文件职责表

| 文件 | 作用 |
|------|------|
| `main.py` | 日报主入口 + `--scheduler` 定时任务 |
| `config.py` / `config.yaml` | 配置加载（YAML 门店列表 + 环境变量密钥） |
| `crawler.py` | 银豹 Playwright 抓取（登录 / 反检测 / 三处数据） |
| `models.py` | `DailyReport` 等 dataclass |
| `database.py` | SQLite/PostgreSQL 双后端，双表（日报 + 商品排名） |
| `report.py` | 拼 Markdown 日报 |
| `pusher.py` | 企微群机器人推送 |
| `exceptions.py` | 自定义异常（AuthError/ParseError/PushError/ConfigError） |
| `agent.py` | **Agent 循环**（9 工具统一注册 + `run_agent()`） |
| `agent_llm.py` | 封装 DeepSeek API（`call_llm`） |
| `agent_tools.py` | 5 个会计工具（手写 dict 注册表） |
| `agent_tools_rfm.py` | 4 个 RFM 工具（LangChain `@tool` 装饰器） |
| `callback_server.py` | 企微自建应用回调入口（FastAPI，8003，被资质卡住） |
| `web_agent.py` | **浏览器问答入口**（FastAPI，8005，当前主入口） |
| `agent_langchain.py` | LangChain `bind_tools` 版 Agent（实验/替代实现，**未接线**） |
| `verify_postgres.py` | PostgreSQL 后端验证脚本 |
| `tests/` | pytest 测试（21 用例，SQLite 内存库 + mock 网络） |

> **注意**：`web_agent.py` 和 `callback_server.py` 都 `from agent import run_agent`，走的是**手写版 `agent.py`**。`agent_langchain.py` 是另一套 LangChain 实现，当前**没有被任何入口调用**。

---

## 运行方式

```bash
# ── 日报管线 ──
python main.py              # 单次：抓数据 → 存库 → 推企微
python main.py --dry-run    # 演习：只打印日报，不推送
python main.py --scheduler  # 定时模式：每天 23:10~23:50 随机执行（上云用）

# ── AI 问答 Agent ──
python web_agent.py         # 浏览器问答入口，监听 0.0.0.0:8005（当前主入口）
python agent.py "最近一周营收怎么样"   # 终端测试 Agent
python agent_langchain.py "问一句"     # LangChain 版（实验）

# ── 其它 ──
python callback_server.py   # 企微回调（8003，被资质卡住，一般不部署）
python verify_postgres.py   # 验证 PostgreSQL 后端（需本地 PG 实例）
python -m pytest -v         # 跑 21 个测试
```

---

## 环境变量

| 变量名 | 说明 | 是否必填 |
|--------|------|:--:|
| `POS_ACCOUNT` | 银豹总店登录账号 | 日报必填 |
| `POS_PASSWORD` | 银豹总店登录密码 | 日报必填 |
| `POS_ACCOUNT_2` / `POS_PASSWORD_2` | 分店账号密码（多店时） | 可选 |
| `WEWORK_WEBHOOK_URL` | 企业微信群机器人 Webhook 地址 | 日报必填 |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（Agent 用） | Agent 必填 |
| `WEWORK_CORPID` / `WEWORK_AGENTID` / `WEWORK_APPSECRET` | 企微自建应用参数（callback_server 用） | 可选（已弃用） |
| `DATABASE_URL` | PostgreSQL 连接串（不设则用 SQLite） | 可选 |

> 敏感信息一律走环境变量，**不写进 `config.yaml`**（避免进 git）。

---

## 数据库

### POS 数据库（`data/daily_report.db`）

- 两张表：`daily_reports`（日报，`UNIQUE(store_id, date)` 防重复）+ `product_rankings`（商品排名）
- 默认 SQLite，零配置；生产可切 PostgreSQL（设 `DATABASE_URL` 或 `PGHOST` 等），`database.py` 自动选后端

### RFM 会员数据库（`../rfm_report/data/rfm_data.db`）

- ⚠️ **路径是相对路径**，写死在 [agent_tools_rfm.py](agent_tools_rfm.py) 里：`../rfm_report/data/rfm_data.db`
- 部署时必须保证 `pos_daily_report` 和 `rfm_report` **两个目录同级存在**，否则 RFM 工具报「数据库不存在」

---

## 安装

```bash
git clone <repo>
cd pos-daily-report
pip install -r requirements.txt
playwright install chromium
```

> ⚠️ **依赖注意**：`requirements.txt` 目前只含 `requests / playwright / pyyaml`，但 Agent 相关代码还需要 `fastapi`、`uvicorn`、`pydantic`、`langchain-core`（RFM 工具用 `langchain_core.tools`），PostgreSQL 后端还需要 `psycopg2-binary`。完整安装建议：

```bash
pip install requests playwright pyyaml fastapi uvicorn pydantic langchain-core psycopg2-binary
```

---

## 部署（Docker）

```bash
docker compose up -d --build
```

`docker-compose.yml` 定义了三个服务：
- `pos-daily-report`：定时调度器（`main.py --scheduler`），每天自动推日报
- `pos-agent-callback`：企微回调（`callback_server.py`，8003）—— 已被 `web_agent.py` 取代（保留参考）
- `pos-agent-web`：浏览器问答入口（`web_agent.py`，8005，当前主入口）

> ✅ **已上云**：容器化部署已包含 `web_agent.py`（8005 浏览器入口），Dockerfile 已装 `langchain-core`。详见「部署指南」与复盘文档。

---

## 技术栈

Python · Playwright · SQLite/PostgreSQL · DeepSeek API · 企业微信 Webhook · FastAPI · Uvicorn · LangChain Core · YAML

---

## 目录结构

```
pos_daily_report/
├── main.py              # 日报主入口 + 定时任务
├── crawler.py           # 银豹 Playwright 抓取
├── config.py / config.yaml  # 配置
├── models.py            # 数据模型
├── database.py          # SQLite/PostgreSQL 双后端
├── report.py            # 日报构建
├── pusher.py            # 企微推送
├── exceptions.py        # 自定义异常
├── agent.py             # Agent 循环（9 工具）
├── agent_llm.py         # DeepSeek API 封装
├── agent_tools.py       # 5 会计工具
├── agent_tools_rfm.py   # 4 RFM 工具
├── callback_server.py   # 企微回调（8003，弃用）
├── web_agent.py         # 浏览器问答（8005，主入口）
├── agent_langchain.py   # LangChain 版 Agent（实验）
├── verify_postgres.py   # PG 验证脚本
├── data/                # SQLite 数据（docker volume 挂载，不进 git）
├── tests/               # pytest 测试（21 用例）
├── Dockerfile / docker-compose.yml
└── 技术文档.md / web-agent改造复盘与技术文档.md
```

---

## 近期改动速览

- **Web Agent 改造（2026-08-16）**：企微自建应用入口被资质卡死 → 新增 `web_agent.py` 浏览器入口；`agent.py` 合并 RFM 工具（会计 5 + RFM 4 = 9 个），新增 `_rfm_tool_to_dict()` 统一两套工具格式。详见 [web-agent改造复盘与技术文档.md](web-agent改造复盘与技术文档.md)。
- **INSERT 防重复**：`UNIQUE(store_id, date)` + `INSERT OR IGNORE`/`ON CONFLICT`，同天同店重复抓取静默跳过。
- **PostgreSQL 双后端**：设 `DATABASE_URL` 自动切 PG，否则 SQLite。
