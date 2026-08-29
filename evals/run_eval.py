"""行为级回归评估 — 对部署好的 Agent 服务跑黄金问题集
================================================================
为什么需要它：pytest 只能验证 SQL 对不对，验证不了"回答质量"。
Agent 的行为是非确定性的——改一行工具描述，可能就让某个问题答砸。
这个脚本把历史踩过的坑固化成"黄金问题集"，每次改代码后跑一遍。

判定方式（三层）：
  1. 工具调用检查：该调哪个工具（must_call_tool）、不该调哪个（must_not_call_tool）、
     参数对不对（tool_params_any）、调用轮数上限（max_tool_calls）
  2. 回答内容检查：必须包含 / 必须不包含的关键字（must_contain / must_not_contain）
  3. （可选）LLM 裁判：设 DEEPSEEK_API_KEY 后，对每个回答 1-5 分质量打分

用法：
  python evals/run_eval.py                              # 默认打 localhost:8006
  EVAL_BASE_URL=http://175.178.9.58:8006 python evals/run_eval.py
  DEEPSEEK_API_KEY=xxx python evals/run_eval.py         # 启用 LLM 裁判
  python evals/run_eval.py --id revenue_may_2026        # 只跑某一条

返回码：全部通过=0，有失败=1（可接 CI 回归闸门）。
"""
import argparse
import json
import os
import sys
import time

import requests

BASE_URL = os.getenv("EVAL_BASE_URL", "http://localhost:8006")
GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden_questions.json")
TIMEOUT = 120  # 每个问题最长等待（LLM + 工具循环可能较慢）


def load_golden() -> list[dict]:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        return json.load(f)


def ask(question: str, sid: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/chat",
        json={"question": question, "session_id": sid},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def check_item(item: dict, resp: dict) -> list[str]:
    """对一条黄金问题做确定性断言，返回问题列表（空=通过）"""
    answer = resp.get("answer", "")
    trace = resp.get("trace", [])
    calls = [t.get("name") for t in trace]
    problems: list[str] = []

    # 1. 工具调用检查
    if item.get("must_call_tool"):
        allowed = item["must_call_tool"]
        if isinstance(allowed, str):
            allowed = [allowed]
        if not any(c in allowed for c in calls):
            problems.append(f"未调用任何期望工具 {allowed}（实际调用: {calls or '无'}）")
    for bad in item.get("must_not_call_tool", []) or []:
        if bad in calls:
            problems.append(f"不应调用工具 {bad}")
    for want in item.get("tool_params_any", []) or []:
        if not any(all(t.get("params", {}).get(k) == v for k, v in want.items()) for t in trace):
            problems.append(f"工具参数未命中要求 {want}（实际: {[t.get('params') for t in trace]}）")
    if item.get("max_tool_calls") is not None and len(trace) > item["max_tool_calls"]:
        problems.append(f"工具调用轮数 {len(trace)} 超过上限 {item['max_tool_calls']}")

    # 2. 回答内容检查
    for must in item.get("must_contain", []) or []:
        if must and must not in answer:
            problems.append(f"回答缺少关键字: {must}")
    for notmust in item.get("must_not_contain", []) or []:
        if notmust and notmust in answer:
            problems.append(f"回答不应包含: {notmust}")
    return problems


def llm_judge(question: str, answer: str, trace: list[dict]) -> tuple[int, str] | None:
    """可选：用 DeepSeek 给回答质量打分（1-5）"""
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    prompt = (
        "你是严格的数据 Agent 评估员。请给回答打分 1-5：\n"
        "- 数据是否来自工具返回、没有编造\n"
        "- 是否正面回答了问题\n"
        "- 中文是否自然简洁\n"
        f"问题: {question}\n"
        f"工具调用轨迹: {json.dumps(trace, ensure_ascii=False)[:500]}\n"
        f"回答: {answer}\n"
        "只输出 JSON: {\"score\": N, \"reason\": \"一句话理由\"}"
    )
    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0, "max_tokens": 200},
            timeout=60,
        )
        text = r.json()["choices"][0]["message"]["content"]
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
        return int(data.get("score", 0)), str(data.get("reason", ""))[:80]
    except Exception as e:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="行为级回归评估")
    parser.add_argument("--id", default="", help="只跑指定 id 的黄金问题")
    parser.add_argument("--base-url", default=BASE_URL, help="Agent 服务地址")
    args = parser.parse_args()

    golden = load_golden()
    if args.id:
        golden = [g for g in golden if g["id"] == args.id]
        if not golden:
            print(f"找不到 id={args.id}")
            return 1

    print(f"评估目标: {args.base_url}")
    print(f"黄金问题数: {len(golden)}\n{'=' * 70}")

    failed = 0
    for i, item in enumerate(golden, 1):
        q = item["question"]
        sid = f"eval-{item['id']}-{int(time.time())}"
        try:
            resp = ask(q, sid)
        except Exception as e:
            print(f"[{i:02d}] ✗ {item['id']} — 请求失败: {e}")
            failed += 1
            continue

        problems = check_item(item, resp)
        answer = resp.get("answer", "")
        calls = [t.get("name") for t in resp.get("trace", [])]
        judge = llm_judge(q, answer, resp.get("trace", []))

        status = "PASS" if not problems else "FAIL"
        if problems:
            failed += 1
        print(f"[{i:02d}] {status} {item['id']}")
        print(f"      Q: {q}")
        print(f"      工具: {calls}")
        for p in problems:
            print(f"      ✗ {p}")
        print(f"      A: {answer[:110]}")
        if judge:
            print(f"      AI评分: {judge[0]}/5 — {judge[1]}")
        print()

    print("=" * 70)
    passed = len(golden) - failed
    print(f"结果: {passed}/{len(golden)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
