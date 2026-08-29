# 深挖-01：NL2SQL 在这个项目里具体怎么落地

> 承接《Agent架构与生产化笔记》第四章。本文把"只读 NL2SQL"从概念落到本项目可执行的设计：
> 该不该上、上了怎么做、安全机械怎么装、什么时候才值得上。

---

## 1. 一句话说清 NL2SQL 解决什么

工具枚举式的边界 = "我预判过的问题形状"（比如 `query_history` 只认"最近N天"）。
NL2SQL 的边界 = "数据库里实际有的数据"。它把"写查询"这个动作本身交给模型，前提是：
**给模型完整的表结构 + 一份把业务词汇翻译成 SQL 的口径字典**。

本项目最近的一次"只会查30天"故障，用 NL2SQL 就不会发生——模型看到 `daily_reports.date` 字段，
自然能写 `WHERE date BETWEEN '2026-05-01' AND '2026-05-31'`。

---

## 2. 本项目当前的选择：暂不上，先加两个固化工具

**判据（为什么不上）：**

| 维度 | 本项目现状 | NL2SQL 的代价 |
|---|---|---|
| 表数量 | 2 张（daily_reports + product_rankings）+ 1 张 RFM（transactions） | 表少，固化工具覆盖率高 |
| 问题形状 | 集中在十来个形状 | 长尾需求少，NL2SQL 收益低 |
| 数据量 | 150 天日报 + 1500 会员 | 全表扫描也无压力 |
| 安全 | 固化工具天然只读 | NL2SQL 必须自建"监狱"（见 §4） |
| 口径 | 营收/会员消费/新增会员 3 个口径，已写死进工具 | 口径字典要单独维护 |

**已经做的折中**（第 9、10 个工具）：`query_revenue_range`（任意日期范围营收）+ `query_new_member_trend`（多月增长序列）——把两个最典型的长尾问题形状固化成工具，成本趋近于零，收益覆盖 95% 真实问题。

---

## 3. 如果上，完整设计

### 3.1 暴露给模型的"表结构 + 口径字典"（每轮随系统提示词注入）

```
数据库 schema：
  daily_reports(id, store_id, date, revenue, time_range, card_recharge,
                time_card_sales, gift_pack_sales, member_upgrade, raw_overview)
    - 每天一行，date 是 YYYY-MM-DD
  product_rankings(id, report_id, store_id, date, rank, product_name, quantity)
  transactions(id, member_name, phone, trans_date, revenue, batch, created_at)
    - trans_date 是 YYYY-MM-DD HH:MM:SS

业务口径字典：
  营收          = SUM(daily_reports.revenue)          （别名：营业额、实收，不含会员折价口径）
  会员消费      = SUM(transactions.revenue)           （别名：消费额，与营收是两套口径，不可相加）
  新增会员      = 当月首次消费的会员数（MIN(trans_date) 落在那月）
  储值卡充值    = SUM(daily_reports.card_recharge)
```

### 3.2 `query_sql` 工具代码草图（只读 + 多道护栏）

```python
import sqlite3, re
from concurrent.futures import ThreadPoolExecutor

ALLOWED_TABLES = {"daily_reports", "product_rankings", "transactions"}
MAX_ROWS = 100            # 结果行数上限
QUERY_TIMEOUT_S = 5       # 查询超时

def _guard(sql: str) -> str:
    """静态审查：只允许单条 SELECT，禁止其他任何语句"""
    sql = sql.strip().rstrip(";").strip()
    if re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|PRAGMA|ATTACH)\b", sql, re.I):
        raise ValueError("只允许 SELECT 查询")
    if ";" in sql:
        raise ValueError("只允许单条语句")
    if sql.split(None, 1)[0].upper() != "SELECT":
        raise ValueError("只允许 SELECT 查询")
    return sql

def _run_query(sql: str, db_path: str):
    # 只读连接：file:...?mode=ro&immutable=1 —— 物理上禁止任何写
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        cur = conn.execute(sql)      # sqlite 天然拒绝对只读文件写
        return [dict(zip([d[0] for d in cur.description], row))
                for row in cur.fetchmany(MAX_ROWS)]
    finally:
        conn.close()

@tool
def query_sql(database: str = "pos", sql: str = "") -> str:
    """只读 SQL 查询（自动限制行数与超时）。database: pos=营收库 / rfm=会员库。
    只能 SELECT，禁止写操作。用于回答固化工具覆盖不到的数据问题。"""
    sql = _guard(sql)
    path = os.getenv("POS_DB_PATH", "data/daily_report.db") if database == "pos" \
           else os.getenv("RFM_DB_PATH", "../rfm_report/data/rfm_data.db")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_query, sql, path)
        try:
            rows = future.result(timeout=QUERY_TIMEOUT_S)
        except TimeoutError:
            return "查询超时（超过 5 秒），请简化查询或加 WHERE/LIMIT。"
    return "\n".join(str(r) for r in rows[:MAX_ROWS]) or "无结果"
```

**七道护栏（生产必须全上）：**
1. 静态审查：正则拒绝所有非 SELECT 语句 + 拒绝多语句
2. 只读连接：`mode=ro&immutable=1` 物理只读（即使审查被绕过也写不进）
3. 行数上限：`fetchmany(MAX_ROWS)`，防爆响应
4. 查询超时：线程池 `future.result(timeout=5)`，防全表扫描拖垮服务
5. 表名白名单：LLM 只能查到 3 张表（可选在 sqlite 里用触发器/视图进一步封死）
6. 口径字典（§3.1）随提示词注入——防"模型发明口径"
7. （进阶）SQL 顾问子 Agent：执行前让第二个模型审一遍

### 3.3 与固化工具的关系：同一 Agent，双轨并存

- 固化工具（10 个）：高频、口径敏感、要求精确 → 描述里写"优先使用"
- `query_sql`：长尾、开放式 → 描述里写"仅当上面工具都不合适时用"
- 模型根据问题自己路由；eval 集对两类都断言"该用哪个"

---

## 4. 评估清单：什么信号出现，才值得从"固化"切到"NL2SQL"

1. **表数量 > 5 或口径 > 10 个**：固化工具维护成本爆炸；
2. **"这个能查吗"类问题占比上升**：日志里频繁出现"工具表达不了"的对话；
3. **数据量大**（日报几年、会员几十万）：SQL 比枚举工具高效得多；
4. **多门店/多租户**：每个门店一套口径，工具数量 × 门店数量；
5. **有专职数据团队**：能维护口径字典和 SQL 审查规则。

只要上面 1~2 条都不满足（本项目现状），**固化工具 + 定期补形状 就是最优解**。

---

## 5. 如果真上，迁移路径（3 步，可回退）

1. **阶段一（并行）**：加 `query_sql` 为第 11 个工具，先只在 demo 容器开放（env `ENABLE_SQL_TOOL=1`），eval 集同时测固化/SQL 双路径；
2. **阶段二（灰度）**：用 eval 跑同一批黄金问题，对比"只用固化工具" vs "固化+SQL"，回答准确率、口径一致性、平均耗时三个指标；
3. **阶段三（决策）**：SQL 路径在质量/成本上均不劣于固化 → 转正；否则砍掉回滚。

**核心原则：NL2SQL 是"兜底"不是"替代"——固化工具负责稳定，SQL 负责补漏，评估数据说了算。**
