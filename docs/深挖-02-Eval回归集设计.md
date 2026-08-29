# 深挖-02：Eval 回归集设计

> 承接《Agent架构与生产化笔记》第五章。本文讲本项目已落地的 eval 体系：
> 为什么 pytest 不够、三层断言怎么设计、trace 从哪来、黄金集怎么选、如何接 CI 闸门。

---

## 1. 为什么 pytest 不够

pytest 只能验证**确定性**的东西：SQL 返回行数、聚合对不对。而 Agent 的问题是**非确定性**的：

- 同一个问题，改一行工具描述，回答就可能从"蹦床3612次"变成"抱歉查不到"；
- 工具参数传错不报错（文本 JSON 协议）——SQL 层正确，但 LLM 根本没调对工具；
- 回答质量（有没有编造、有没有正面回答）**没有任何断言**能测。

所以需要**行为级 eval**：把"历史上答砸过的问题"固化成黄金集，每次改完代码跑一遍。

本项目四天踩的坑，就是黄金集的第一批素材：

| 历史故障 | 本质 | 固化成的 eval 断言 |
|---|---|---|
| "蹦床只有6次"（没跨天聚合） | 数据层 | 必调 `query_product_ranking`，参数 `days=30`，回答含"蹦床"且不含"6 次" |
| "只能查最近30天" | 工具层 | 必调 `query_revenue_range`，参数 `start_date=2026-05-01`，回答含"2026-05"且不含"只能查最近一个月" |
| "今年趋势答成本月" | 上下文层 | 必调 `query_new_member_trend`，轮数 ≤3 |
| "编 0 人持平" | 统计口径层 | 必调 `query_new_members`，回答含"新增" |
| "新会员 902（应为549）" | 统计口径层 | 数据层测试已锁死口径；eval 断言回答含"新增" |

---

## 2. 三层断言设计

### 第一层：工具调用断言（trace 断言）——这是 Agent 特有的层

```
must_call_tool     该问题必须调用哪些工具（可以是候选清单，如 ["query_revenue_range","query_history"]）
must_not_call_tool 不该调用哪些工具
tool_params_any    工具参数必须命中（如 {"days": 30}）
max_tool_calls     调用轮数上限（防 LLM 空转）
```

这一层是 pytest 测不到的：**LLM 有没有"想对"**。比如"2026年5月收入"——数据层测试只保证 `get_revenue_range` 正确，但模型可能根本不调它。eval 把"必须调哪个工具"变成断言。

### 第二层：回答内容断言（确定性）

```
must_contain      回答必须包含的关键字（如 "2026-05"、"新增"、"环比"）
must_not_contain  回答必须不含的关键字（如 "只能查最近一个月"、"6 次"）
```

便宜、可解释、不依赖模型。覆盖"模型有没有正面回答"。

### 第三层：LLM-as-Judge（可选，主观质量分）

```
设 DEEPSEEK_API_KEY 后，run_eval 对每个回答让 DeepSeek 打 1-5 分：
  数据是否来自工具返回（不编造）？是否正面回答？中文是否自然？
```

成本低（一次调用）、可抓前两层漏掉的"数字对但语气错/口径含混"问题。

---

## 3. trace 从哪来：一次可观测性改造

eval 要断言工具调用，先要让 Agent 把调用过程交出来。本项目加了两个东西：

1. `agent.py` → `run_agent(question, history, return_trace=True)`：循环里把每轮
   `{"name", "params", "result"}` 记下来返回（result 截断 400 字符防爆响应）。
2. `web_agent.py` → `/api/chat` 响应新增 `trace` 字段。

收益不止 eval：**任何一次对话，都能从 API 响应里看到"它调了什么、传了什么参数、工具回了什么"**——
这就是《笔记》第五章说的可观测性，面试时可以直接打开浏览器看。

---

## 4. 黄金集怎么选（本项目 14 条的结构）

```
evals/golden_questions.json   —— 黄金问题集（14 条）
evals/run_eval.py             —— 评估器（确定性断言 + 可选 LLM 裁判）
```

覆盖原则：
- **每个工具至少一条**（10 个工具全扫一遍，防"某工具描述写坏了没人知道"）；
- **每个历史故障至少一条**（回归闸门的核心）；
- **异常路径要有**（"你好"——必须 0 工具调用，防"闲聊也去查库"）；
- **数量控制在 30 条内**（每条都是真 LLM 调用，跑一次约 1-2 分钟，贵的是时间不是钱）。

一条黄金问题的结构：

```json
{
  "id": "revenue_may_2026",
  "question": "2026年5月的收入是多少？",
  "must_call_tool": ["query_revenue_range"],
  "tool_params_any": [{"start_date": "2026-05-01"}],
  "must_contain": ["2026-05"],
  "must_not_contain": ["只能查最近一个月", "没有2026年5月"]
}
```

注意：断言要**时间相对化**。`2026-05` 是当前数据覆盖范围内的固定月（今天 8/29），
日期会随部署时间推移而失效的断言不要写进黄金集。

---

## 5. 运行方法与 CI 闸门

```bash
# 本地（对已部署的服务）
python evals/run_eval.py
EVAL_BASE_URL=http://175.178.9.58:8006 python evals/run_eval.py
# 启用 LLM 裁判打分
DEEPSEEK_API_KEY=xxx python evals/run_eval.py
# 只跑单条（调试用）
python evals/run_eval.py --id revenue_may_2026
```

返回码：全部通过 = 0，有失败 = 1。**接 CI 只需要一行：**

```yaml
# .github/workflows/agent-eval.yml
- run: python evals/run_eval.py --base-url ${{ secrets.EVAL_URL }}
```

每次改 `agent_tools.py` / `agent_llm.py` / 系统提示词 → 跑 eval → 全绿才允许合入。
**这是"Agent 质量可管理"的最小闭环：改了什么 → 有没有让某个老问题答砸 → 立刻知道。**

---

## 6. 诚实说明 eval 的边界

- 黄金集是"抽样"不是"全覆盖"：14 条通过 ≠ 所有问题都好。它抓的是**回归**（以前好的别变坏），抓不了**新问题的引入**——那要靠线上日志 + 把新故障补进黄金集。
- LLM-as-Judge 本身不稳定：温度 0、给明确 rubic，但仍可能误判。**用确定性断言当硬闸门，用 LLM 分当趋势参考。**
- eval 和 pytest 是互补关系：pytest 锁 SQL 正确性，eval 锁 Agent 行为。**两层都绿才叫"测试通过"。**
