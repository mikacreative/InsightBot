import re
from pathlib import Path
from typing import Any


TASK_START_MARKER = "🚀 === 营销情报抓取任务开始 ==="


def read_recent_task_block(log_path: str) -> list[str]:
    path = Path(log_path)
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start_index = -1
    for index, line in enumerate(lines):
        if TASK_START_MARKER in line:
            start_index = index
    if start_index < 0:
        return []
    return lines[start_index:]


def parse_recent_run_summary(log_path: str) -> dict[str, Any]:
    lines = read_recent_task_block(log_path)
    if not lines:
        return {
            "status": "missing_log",
            "overall_no_push": False,
            "categories": {},
            "task_started_at": None,
            "log_excerpt": [],
        }

    categories: dict[str, dict[str, Any]] = {}
    current_category: str | None = None
    task_started_at: str | None = None
    overall_no_push = False
    runtime_errors: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not task_started_at and line:
            task_started_at = raw_line[:19] if len(raw_line) >= 19 else None

        match = re.search(r"📁 正在处理板块: 【(.+?)】", line)
        if match:
            current_category = match.group(1)
            categories.setdefault(
                current_category,
                {
                    "category": current_category,
                    "candidate_count": None,
                    "status": "running",
                    "reason": "处理中",
                },
            )
            continue

        match = re.search(r"⏳ 板块 【(.+?)】 排重后剩余 (\d+) 条数据交由 AI 筛选", line)
        if match:
            category = match.group(1)
            categories.setdefault(category, {"category": category})
            categories[category]["candidate_count"] = int(match.group(2))
            categories[category]["status"] = "ai_filtering"
            categories[category]["reason"] = "有候选，交由 AI 筛选"
            continue

        match = re.search(r"📭 板块 【(.+?)】 今日无更新数据", line)
        if match:
            category = match.group(1)
            categories.setdefault(category, {"category": category})
            categories[category]["candidate_count"] = 0
            categories[category]["status"] = "no_candidates"
            categories[category]["reason"] = "近 24h 无有效候选"
            continue

        match = re.search(r"🈳 AI 判定 \[(.+?)\] 无合格内容，已拦截", line)
        if match:
            category = match.group(1)
            categories.setdefault(category, {"category": category})
            categories[category]["status"] = "blocked_by_prompt"
            categories[category]["reason"] = "有候选，但被 Prompt 全部拦截"
            continue

        match = re.search(r"❌ AI 分析彻底失败 \[(.+?)\]", line)
        if match:
            category = match.group(1)
            categories.setdefault(category, {"category": category})
            categories[category]["status"] = "ai_error"
            categories[category]["reason"] = "AI 调用失败"
            continue

        match = re.search(r"📤 推送板块 【(.+?)】 成功", line)
        if match:
            category = match.group(1)
            categories.setdefault(category, {"category": category})
            categories[category]["status"] = "pushed"
            categories[category]["reason"] = "已成功推送"
            continue

        if "📭 今日全网无更新内容被推送" in line:
            overall_no_push = True
            continue

        if "Traceback" in line or "ERROR" in line or "Exception" in line:
            runtime_errors.append(line)

    return {
        "status": "ok",
        "overall_no_push": overall_no_push,
        "categories": categories,
        "task_started_at": task_started_at,
        "runtime_errors": runtime_errors[-5:],
        "log_excerpt": lines[-30:],
    }


def build_no_push_diagnosis(*, health_snapshot: dict[str, Any] | None, run_summary: dict[str, Any], configured_categories: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    category_states = run_summary.get("categories", {})

    if health_snapshot:
        unhealthy_feeds: list[dict[str, Any]] = []
        stale_feeds: list[dict[str, Any]] = []
        for category in health_snapshot.get("categories", []):
            for feed in category.get("feeds", []):
                if feed.get("status") == "error":
                    unhealthy_feeds.append(
                        {
                            "category": category["category"],
                            "url": feed.get("url"),
                            "error_type": feed.get("error_type"),
                            "error_message": feed.get("error_message"),
                        }
                    )
                elif feed.get("status") == "stale":
                    stale_feeds.append(
                        {
                            "category": category["category"],
                            "url": feed.get("url"),
                            "latest_pub": feed.get("latest_pub"),
                        }
                    )
        if unhealthy_feeds:
            cards.append(
                {
                    "priority": 1,
                    "kind": "source_error",
                    "title": "源异常优先排查",
                    "summary": f"发现 {len(unhealthy_feeds)} 个 RSS 源报错，优先怀疑源不可达、超时或解析失败。",
                    "next_step": "先去 RSS 健康度面板定位异常源。",
                    "details": unhealthy_feeds[:8],
                }
            )

    blocked_categories = [value for value in category_states.values() if value.get("status") == "blocked_by_prompt"]
    if blocked_categories:
        cards.append(
            {
                "priority": 2,
                "kind": "prompt_block",
                "title": "候选有值，但被 Prompt 全拦截",
                "summary": f"共有 {len(blocked_categories)} 个板块出现“有候选但无合格内容”，优先怀疑 Prompt 过严或信源与板块目标失配。",
                "next_step": "去 Prompt Debug 台对这些板块跑“当前版 vs 草稿版”。",
                "details": blocked_categories,
            }
        )

    no_candidate_categories = [value for value in category_states.values() if value.get("status") == "no_candidates"]
    if no_candidate_categories:
        cards.append(
            {
                "priority": 3,
                "kind": "no_candidates",
                "title": "板块没有候选内容",
                "summary": f"共有 {len(no_candidate_categories)} 个板块近 24h 没抓到有效候选，可能是源没更新，也可能需要补源。",
                "next_step": "检查板块源配置，必要时补充或替换信源。",
                "details": no_candidate_categories,
            }
        )

    if run_summary.get("runtime_errors"):
        cards.append(
            {
                "priority": 4,
                "kind": "runtime_error",
                "title": "运行异常需要查看日志",
                "summary": "最新任务里出现运行异常或错误日志，需要进一步查看原始日志。",
                "next_step": "前往运行日志查看完整堆栈和上下文。",
                "details": run_summary.get("runtime_errors", []),
            }
        )

    if not cards and run_summary.get("overall_no_push"):
        cards.append(
            {
                "priority": 5,
                "kind": "no_push_unknown",
                "title": "本次无推送，但未识别到明确根因",
                "summary": "日志没有明显报错，可能需要结合健康度和 Prompt 调试进一步确认。",
                "next_step": "先看 RSS 健康度，再看 Prompt Debug 台。",
                "details": [{"category": category, **category_states.get(category, {})} for category in configured_categories],
            }
        )

    cards.sort(key=lambda item: item["priority"])
    return cards
