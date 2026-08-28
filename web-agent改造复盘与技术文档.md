# Web 版智能体（Agent）本地闭环改造 —— 完整复盘与技术文档

> 日期：2026-08-16 ｜ 项目：pos_daily_report ｜ 作者：zjr
> 目标：把「卡在企业微信入口」的 POS Agent 改造成「浏览器直连、本地闭环」的完整 Agent
> 用途：面试技术复盘材料 / 代码理解索引 / 部署操作手册

---

## 一、背景：为什么做这个改造

1. **现实约束**：POS Agent 原本的对话入口是企业微信自建应用（`callback_server.py`）。企微自建应用要求开发者具备「三方服务商」资质，个人无法开通——**入口被卡死，Agent 空有大脑但没有嘴**。
2. **认知升级**：Agent 的价值在「核心循环 + 工具 + 数据」，不在某个入口。入口被卡，换一个入口即可——把企微回调换成浏览器网页。
3. **求职价值**：改造完成后，Agent 链路 100% 自主可控，可公网部署、可现场演示（面试官当场提问、当场查库回答），且正好命中实施交付岗「不依赖第三方平台、能适配客户环境」的要求。

## 二、改造前：项目已有能力盘点

改造前项目已经具备完整的 Agent 架构（6 个模块分工清晰）：

| 文件 | 职责 | 状态 |
|---|---|---|
| `agent.py` | Agent 循环（LLM 思考→选工具→执行→再思考），`MAX_TURNS=5` 护栏 | ✅ 已有，但只挂了 5 个会计工具 |
| `agent_llm.py` | 封装 DeepSeek API 调用，返回 `(reply, tool_call)` | ✅ 已有 |
| `agent_tools.py` | 5 个会计工具（dict 注册表）+ `execute_tool()` 分发器 | ✅ 已有 |
| `agent_tools_rfm.py` | 4 个 RFM 工具（LangChain `@tool` 装饰器定义） | ✅ 已有，**但未接入循环** |
| `callback_server.py` | 企微回调入口（FastAPI，端口 8003） | ⚠️ 被企微资质卡住 |
| `database.py` | SQLite 数据访问层 | ✅ 已有 |

**探查时的三个关键发现**：
1. `run_agent()` 内部 `from agent_tools import TOOLS` 只用了 5 个会计工具——**RFM 的 4 个工具从没进过 Agent 循环**（`agent_tools_rfm.py` 注释里写着 `ALL_TOOLS = TOOLS + RFM_TOOLS`，但没真正实现）。
2. 两套工具**格式不兼容**：`agent_tools.py` 的 TOOLS 是手写 dict（`{"name", "description", "parameters"}`），而 `agent_tools_rfm.py` 的 RFM_TOOLS 是 LangChain `@tool` 装饰后的 `BaseTool` 对象。`agent_llm.py` 的 `build_tool_prompt()` 用 `t.get("name")` 取值——**dict 能取，BaseTool 对象没有 `.get()`，直接合并会崩**。
3. LangChain `@tool` 对象本身带有足够信息可转换：`.name`（工具名）、`.description`（描述）、`.args`（JSON Schema，含 `properties`）、`.func`（原始 Python 函数）。

## 三、改造后：目标架构

```
改造前（卡死）：老板在企微发消息 → 企微服务器 → callback_server(企微资质被卡✗) → agent.py → 数据库
改造后（闭环）：老板在浏览器提问 → web_agent.py(/api/chat) → agent.py(9个工具) → SQLite(POS+RFM) → 网页回答
```

- Agent 本体（循环/工具/数据库访问）**零改动复用**
- 只新增一个 Web 入口 + 合并工具注册表

---

## 四、代码改动详解

### 4.1 `agent.py` —— 合并 9 个工具（核心改动）

改动点：导入 RFM 工具 → 写转换函数 → 构造统一注册表 → 统一执行器 → `run_agent` 换用新表。

**① 新增 `_rfm_tool_to_dict()`：把 LangChain `@tool` 对象转成 `agent_llm` 认识的 dict**

```python
def _rfm_tool_to_dict(tool) -> dict:
    """把 LangChain @tool 对象转成 agent_llm 认识的 dict 格式"""
    schema = tool.args  # JSON schema dict，参数在 properties 里
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    params = {}
    for name, meta in properties.items():
        if isinstance(meta, dict):
            params[name] = meta.get("description", "") or name
        else:
            params[name] = str(meta)
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": params,
    }
```

设计要点：
- `tool.args` 返回的是 Pydantic 生成的 JSON Schema，参数列表藏在 `properties` 里，**不是顶层**——这是最容易踩的坑。
- 参数描述为空时回退成参数名，保证 LLM 拿到的是可读的提示。

**② 构造 9 工具完整清单 + RFM 执行器**

```python
ALL_TOOLS = TOOLS + [_rfm_tool_to_dict(t) for t in RFM_TOOLS]   # 5 + 4 = 9
_RFM_EXECUTORS = {t.name: t.func for t in RFM_TOOLS}            # LangChain 对象暴露原始函数
```

**③ 新增 `execute_any_tool()`：统一执行器（两套工具一条路执行）**

```python
def execute_any_tool(name: str, params: dict) -> str:
    """统一执行器：会计工具走 execute_tool，RFM 工具走 LangChain func"""
    if name in _RFM_EXECUTORS:
        try:
            return str(_RFM_EXECUTORS[name](**params))
        except Exception as e:
            return f"工具 {name} 执行失败: {e}"
    return execute_tool(name, params)
```

设计要点：
- 会计工具（手写 dict 注册表）走原来的 `execute_tool()`，RFM 工具（LangChain 装饰器）走 `t.func(**params)`。
- 异常兜底返回字符串而不是抛异常——**保证 Agent 循环不会因为单个工具报错而中断**（防御性编程，符合项目一贯风格）。

**④ `run_agent()` 只改两行**

```python
raw_reply, tool_call = call_llm(messages, ALL_TOOLS)      # 原来传 TOOLS，现在传 ALL_TOOLS
tool_result = execute_any_tool(tool_call["name"], tool_call.get("params", {}))  # 统一执行器
```

函数签名 `run_agent(user_question, conversation_history=None)` 不变 → `callback_server.py` 无需改动，向后兼容。

### 4.2 `web_agent.py` —— 新建 Web 入口（FastAPI）

**路由设计（3 个接口）：**

| 路由 | 方法 | 职责 |
|---|---|---|
| `/` | GET | 返回聊天页面 HTML |
| `/api/chat` | POST | 接收 `{question, session_id}`，调 `run_agent` 返回 `{answer, session_id}` |
| `/health` | GET | 健康检查，返回 `{"status":"ok","tools":9}` |

**核心逻辑（会话记忆 + 错误兜底）：**

```python
_sessions: dict[str, list[dict]] = {}   # session_id → 对话历史（内存实现）
MAX_HISTORY = 20                         # 只保留最近 20 条，控制 token 成本

@app.post("/api/chat")
async def chat(req: ChatRequest):
    question = req.question.strip()
    if not question:
        return JSONResponse({"answer": "请输入问题。"})
    sid = req.session_id or uuid.uuid4().hex[:12]
    history = _get_history(sid)
    try:
        answer = run_agent(question, history)
    except Exception as e:
        logger.error(f"Agent 处理失败: {e}")
        answer = "抱歉，暂时无法处理您的问题，请稍后再试。"   # 不把堆栈暴露给用户
    _remember(sid, "user", question)
    _remember(sid, "assistant", answer)
    return JSONResponse({"answer": answer, "session_id": sid})
```

设计要点：
- **多轮记忆**：会话历史跟着 `session_id` 存在内存 dict，传给 `run_agent` 的 `conversation_history` 参数——Agent 循环原生支持，零额外改造。
- **错误兜底**：Agent 异常时返回友好提示，不暴露 traceback（沿用 callback_server 的「不向业务人员暴露 Python 堆栈」原则）。
- **前端身份**：浏览器用 `localStorage` 存 session_id，刷新页面不丢会话。

### 4.3 聊天页面（前端，单文件内嵌）

- 深色主题（`#0f172a` 背景 + 蓝色发送按钮），聊天气泡布局
- 纯原生 JS：`fetch` 调 `/api/chat`，`Enter` 发送，发送中禁用按钮 + 显示「Agent 正在查库分析…」
- 引导消息列出 5 个示例问题，面试演示时直接点问题就能问
- **零外部依赖**（不引 CDN），符合「可离线、可私有化」的交付风格


---

## 五、遇到的问题与解决方案（完整记录）

| # | 问题 | 原因 | 解决 |
|---|---|---|---|
| 1 | **工具格式不统一**：直接 `TOOLS + RFM_TOOLS` 传给 `build_tool_prompt` 会崩 | dict 用 `t.get()`，BaseTool 对象没有 `.get()` | 写 `_rfm_tool_to_dict()` 统一转成 dict；参数要从 `schema["properties"]` 取 |
| 2 | **RFM 工具从未真正进过循环** | 之前只写了注释没实现合并 | 本次实际合并，验证 9 个工具全部挂载 |
| 3 | **编辑工具单次写入超限**（6123 > 6000 字符） | 聊天页面 HTML 太大 | 拆成两步：先建 Python 主体，再把 HTML 拆成 `_HTML_A` + `_HTML_B` 两段拼接 |
| 4 | **`curl -d` 传中文请求 → HTTP 400 "error parsing the body"** | Windows shell 中文编码问题，JSON body 被 shell 破坏 | 改用 Python `requests.post(json=...)` 测试，绕开 shell 编码 |
| 5 | **Playwright 拒绝访问 `127.0.0.1`** | MCP 工具安全限制（禁止内网地址） | 用 `curl` 验证页面 HTML（title、按钮、接口） |
| 6 | **测试后 8005 端口残留多个进程** | 后台启动了多个 python 实例 | `netstat -ano | grep :8005` 找 PID → `taskkill //PID //F` 逐个清理，最终确认端口释放 |

> 复盘心得：6 个问题里有 3 个是「环境/工具链」问题（编码、编辑限制、内网限制），2 个是「技术坑」（格式不统一、schema 结构），1 个是「历史遗留」（RFM 没合并）。**真正有价值的是问题 1 和 2**——它们暴露了「两套工具格式不统一」这个架构隐患，修好它，Agent 的能力从 5 个工具扩到 9 个。

## 六、测试与验证结果

| 测试项 | 方法 | 结果 |
|---|---|---|
| 9 工具注册 | `python -c "from agent import ALL_TOOLS"` | ✅ 5 会计 + 4 RFM 全部挂载 |
| 会计工具直查 | `execute_any_tool("query_summary", {})` | ✅ 20 天累计 ¥36,067，日均 ¥1,803 |
| RFM 工具直查 | `execute_any_tool("query_segments", {})` | ✅ 5303 名会员，8 级分群 |
| HTTP 接口 | `curl /health` | ✅ `{"status":"ok","tools":9}` |
| 真实对话① | 「最近一周营收怎么样？」 | ✅ 调 `query_history` → 数据为空 → **如实告知未编造** |
| 真实对话② | 「开业以来一共赚了多少？」 | ✅ 调 `query_summary` → 返回 ¥36,067 |
| 真实对话③ | 「哪些客户是流失客户？」 | ✅ 调 RFM 工具 → 1555 人 + 前 20 名 + 运营建议 |

**关键质量验证**：当工具返回「暂无数据」时，Agent 按 SYSTEM_PROMPT 规则如实告知，没有编造数字——说明 Prompt 约束生效、护栏可靠（`temperature=0.1` 低温度 + `MAX_TURNS=5` 硬上限 + 数据兜底三件套全部生效）。


---

## 七、部署指南（含 Nginx 反代 + 可选 Basic Auth）

### 7.1 服务器环境要求
- Ubuntu 22.04（与现有三套系统一致）
- Python 3.10+
- 依赖：`fastapi` `uvicorn` `pydantic` `requests` `pyyaml` `langchain-core`

### 7.2 部署步骤

```bash
# ① 上传代码（保持目录结构！RFM 数据库是相对路径引用）
#    必须保证两个数据库同级存在：
#    pos_daily_report/data/daily_report.db        ← POS 数据
#    rfm_report/data/rfm_data.db                  ← RFM 数据（agent_tools_rfm.py 用 ../rfm_report 引用）

# ② 安装依赖
cd pos_daily_report
pip install -r requirements.txt

# ③ 配置环境变量（不进 git）
export DEEPSEEK_API_KEY="sk-xxxx"
export POS_ACCOUNT="银豹账号"
export POS_PASSWORD="银豹密码"

# ④ 启动服务（后台常驻）
nohup python web_agent.py > web_agent.log 2>&1 &

# ⑤ 验证
curl http://127.0.0.1:8005/health
```

### 7.3 Nginx 反向代理配置

```nginx
# /etc/nginx/conf.d/agent.conf
server {
    listen 80;
    server_name rongno2.cn;

    # 聊天页面 + API 全部反代到 8005
    location /agent/ {
        proxy_pass http://127.0.0.1:8005/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # 聊天是长文本回复，加大超时
        proxy_read_timeout 120s;
    }

    # 可选：加 Basic Auth（与 knowledge-assistant 一致的安全策略）
    # auth_basic "Agent Login";
    # auth_basic_user_file /etc/nginx/.htpasswd_agent;
}

# 生效
# nginx -t && nginx -s reload
```

访问地址：`http://rongno2.cn/agent/`

### 7.4 部署注意事项
- **RFM 数据库路径是相对路径**（`agent_tools_rfm.py` 里写死 `../rfm_report/data/rfm_data.db`）——部署时 `pos_daily_report` 和 `rfm_report` 两个目录必须保持同级，否则 RFM 工具会报「数据库不存在」。
- 会话记忆是**内存实现**，服务重启后清空（够用，不为此上 Redis，控制复杂度）。
- 若加 HTTPS：在 Nginx 配置里加证书（其他三套系统已有现成模板可抄）。
- 前端零外部依赖（不引 CDN），Nginx 无需额外配置跨域/资源白名单。

---

## 八、面试怎么讲（复盘话术）

> 「当时我的 POS Agent 对话入口是企业微信，但企微自建应用需要三方服务商资质，个人开不了，等于 Agent 卡死了。我没有放弃这套系统，而是**只换入口、不动大脑**——写了个 `web_agent.py`，把对话入口换成浏览器网页，一天内跑通。
>
> 过程中遇到两个真问题：
> ① 我的工具是两套格式——会计工具是手写 dict，RFM 工具是 LangChain 对象，直接合并会崩。我写了个 `_rfm_tool_to_dict()` 把 LangChain 对象转成统一 dict，再用一个 `execute_any_tool()` 统一执行，9 个工具全部进循环。
> ② 参数要从 `tool.args` 的 `properties` 里取，不是顶层——这是 LangChain 的坑。
>
> 做完以后我意识到：**智能体的价值在核心循环、在工具、在数据，不在某个入口**。入口被卡就换入口，环境受限就换方案——这件事让我真正理解了'智能体落地'和'能跑通 demo'的区别。」

---

## 九、可扩展方向

- [ ] 会话记忆升级：内存 → Redis（knowledge-assistant 已有现成封装可复用）
- [ ] 前端升级：SSE 流式输出（打字机效果），体验对齐 ChatGPT
- [ ] 接入 Text-to-SQL 工具：让 Agent 直接查任意 SQL（RAG 项目已有 Text-to-SQL 经验）
- [ ] 对话日志落库：SQLite 存问答记录，方便复盘问答质量（对应实施岗「故障归档」）
- [x] Dockerfile + docker-compose：与现有三套系统统一容器化部署（2026-08-28 已完成：三服务含 pos-agent-web，端口 8005）
- [ ] 多轮上下文压缩：历史超长时用 LLM 摘要，控制 token 成本

---

## 十、待优化清单（2026-08-28 部署前代码评审，部署后处理）

> 评审共 6 条意见，其中 4 条属实、2 条不成立。属实项与「九、可扩展方向」互补，按优先级排列，**部署稳定后再逐项做**。

| # | 问题 | 现状 | 计划 |
|---|------|------|------|
| 1 | 会话记忆存内存（`_sessions`），重启即丢、多进程割裂 | `web_agent.py` 第 35 行，注释已声明「重启即清空」 | 升级 SQLite/Redis 持久化（复用 knowledge-assistant 封装） |
| 2 | 前端无 Markdown 渲染，代码块/表格/列表原样输出 | `b.textContent = text`（第 137 行） | 引入轻量 Markdown 渲染（本地 bundle，不引 CDN） |
| 3 | 无流式输出，长查询一次性等待、页面无进度 | `/api/chat` 同步等 `run_agent` 返回（第 70 行） | 改 SSE 流式（打字机效果） |
| 4 | 前端 fetch 无超时控制，后端卡住页面一直挂起 | `fetch("/api/chat")` 无 AbortController（第 157 行） | 加超时 + 超时提示 |

**已核查不成立 / 不适用**：端口不一致（代码内无 8005，三处均 8004→8005 已统一）；CORS（本部署页面与 API 同源，无需配置）。

