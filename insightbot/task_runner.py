"""
Task execution engine.

run_task() assembles a task's config and dispatches to the correct pipeline
(editorial or classic). It owns all channel sends — pipelines themselves only
return final_markdown and do not call any channel APIs.
"""

import logging
import os
import time
from datetime import datetime
from typing import Any, Callable

from .channels import send_to_channel
from .run_history import append_run_record

logger = logging.getLogger("TaskRunner")


def _normalize_search_queries(raw_queries: list[Any]) -> list[str]:
    """Normalize task-level search query config into executable query strings."""
    normalized: list[str] = []
    seen: set[str] = set()

    for item in raw_queries or []:
        if isinstance(item, dict):
            query = str(item.get("keywords", "")).strip()
        else:
            query = str(item or "").strip()

        if not query or query in seen:
            continue
        normalized.append(query)
        seen.add(query)

    return normalized


def _estimate_counts(stage_results: dict) -> tuple[int, int]:
    candidate_count = 0
    selected_count = 0

    if isinstance(stage_results.get("global_candidates"), list):
        candidate_count = len(stage_results["global_candidates"])
    elif isinstance(stage_results.get("screened_result"), dict):
        candidate_count = len(stage_results.get("screened_result", {}).get("input_candidates", []))
    elif isinstance(stage_results.get("candidate_count"), int):
        candidate_count = stage_results["candidate_count"]

    if isinstance(stage_results.get("category_results"), dict):
        selected_count = sum(
            len((item or {}).get("selected_items", []))
            for item in stage_results["category_results"].values()
            if isinstance(item, dict)
        )
    elif isinstance(stage_results.get("selected_items"), list):
        selected_count = len(stage_results["selected_items"])

    return candidate_count, selected_count


def _build_run_record(
    *,
    task_id: str,
    config: dict,
    task_pipeline: str,
    started_at: datetime,
    ended_at: datetime,
    dry_run: bool,
    ok: bool,
    stage_results: dict,
    channel_results: list[dict],
    error: str | None,
) -> dict:
    candidate_count, selected_count = _estimate_counts(stage_results)
    return {
        "task_id": task_id,
        "task_name": config.get("_task_name", task_id),
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "ok": ok,
        "dry_run": dry_run,
        "pipeline": task_pipeline,
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "channel_results": channel_results,
        "error": error,
    }


def _run_editorial_pipeline(*, config: dict, logger) -> dict:
    pipeline_mode = config.get("_editorial_pipeline_mode", "legacy")

    if pipeline_mode == "editorial-intelligence":
        return _run_editorial_intelligence_pipeline(config=config, logger=logger)

    # legacy fallback
    from .editorial_pipeline import run_editorial_pipeline
    return run_editorial_pipeline(config=config, logger=logger)


def _run_editorial_intelligence_pipeline(*, config: dict, logger) -> dict:
    """
    Run the new editorial-intelligence pipeline instead of the legacy one.

    Maps tasks.json config → SourceStrategy + BriefingGoal → pipeline → legacy result shape.
    """
    try:
        from editorial_intelligence.contracts import BriefingGoal, SourceStrategy, SourceWeightConfig
        from editorial_intelligence.workflows.editorial_pipeline import run_editorial_pipeline as run_ei_pipeline
        from editorial_intelligence.contracts.source_weight import SearchProvider
    except ImportError:
        logger.error("editorial-intelligence not installed: pip install -e editorial-intelligence/")
        return {"ok": False, "error": "editorial-intelligence not installed", "final_markdown": ""}

    feeds = config.get("feeds", {})
    search_config = config.get("search", {})

    # Build primary_sources from feeds
    primary_sources = []
    for feed_id, feed_data in feeds.items():
        rss_urls = feed_data.get("rss", [])
        if isinstance(rss_urls, list):
            for url in rss_urls:
                if url:
                    primary_sources.append(str(url))

    # Build search providers
    search_providers = {}
    if search_config.get("enabled", False):
        provider_type = search_config.get("provider", "duckduckgo")
        if provider_type == "baidu":
            search_providers["baidu"] = SearchProvider(
                provider_id="baidu",
                name="Baidu",
                weight=0.8,
                enabled=True,
            )
        elif provider_type == "duckduckgo":
            search_providers["duckduckgo"] = SearchProvider(
                provider_id="duckduckgo",
                name="DuckDuckGo",
                weight=0.6,
                enabled=True,
            )
        elif provider_type == "brave":
            brave_key = search_config.get("api_key") or os.getenv("BRAVE_API_KEY", "")
            search_providers["brave"] = SearchProvider(
                provider_id="brave",
                name="Brave Search",
                api_key=brave_key,
                base_url="https://api.search.brave.com/res/v1/web/search",
                weight=0.4,
                enabled=True,
            )
        elif provider_type == "bocha":
            bocha_key = search_config.get("api_key") or os.getenv("BOCHA_API_KEY", "")
            search_providers["bocha"] = SearchProvider(
                provider_id="bocha",
                name="博查 AI 搜索",
                api_key=bocha_key,
                base_url="https://api.bocha.cn",
                weight=0.8,
                enabled=True,
                timeout_s=30,
            )
        else:
            logger.warning(f"editorial-intelligence: unsupported search provider '{provider_type}'")

    source_weight_config = SourceWeightConfig(search_providers=search_providers)
    normalized_queries = _normalize_search_queries(search_config.get("queries", []))

    # Build goal from feeds structure
    topic_parts = list(feeds.keys()) or ["营销情报"]
    goal = BriefingGoal(
        topic=" / ".join(topic_parts),
        queries=normalized_queries,
        description="",
    )
    # Pipeline expects dict-like goal, so convert dataclass to dict
    goal_dict = {
        "topic": goal.topic,
        "queries": goal.queries,
        "description": goal.description,
        "audience": goal.audience,
    }

    source_strategy = SourceStrategy(
        primary_sources=primary_sources,
        search_enabled=search_config.get("enabled", False),
    )

    editorial_policy = config.get("pipeline_config", {})

    ei_result = run_ei_pipeline(
        context={
            "goal": goal_dict,
            "source_strategy": source_strategy,
            "editorial_policy": editorial_policy,
            "source_weight_config": source_weight_config,
        }
    )

    return {
        "ok": ei_result.ok,
        "error": None,
        "final_markdown": ei_result.final_brief.get("markdown", ""),
        "source_summary": ei_result.source_summary,
        "candidate_count": len(ei_result.candidate_pool),
        "shortlist_size": len(ei_result.shortlist),
        "diagnostics": ei_result.diagnostics,
        "stage_results": {},
    }


def _run_classic_pipeline(*, config: dict, logger):
    from .smart_brief_runner import run_task as run_classic_task

    return run_classic_task(config=config, logger=logger)


def run_task(
    task_id: str,
    config_loader_fn: Callable[[], dict],
    dry_run: bool = False,
) -> dict:
    """
    Execute a task by ID.

    Args:
        task_id: The task identifier in tasks.json.
        config_loader_fn: Callable that returns the assembled runtime config dict.
        dry_run: If True, runs the pipeline but sends nothing to channels.
                 Returns the full result dict for UI display.

    Returns:
        dict with keys:
            - ok: bool
            - task_id: str
            - pipeline: str ("editorial" | "classic")
            - dry_run: bool
            - final_markdown: str
            - channel_results: list[dict]  (only when dry_run=False)
            - stage_results: dict  (full pipeline intermediate results)
            - error: str | None
    """
    config = config_loader_fn()
    task_pipeline = config.get("_task_pipeline", "editorial")
    task_channels = config.get("_task_channels", [])
    started_at = datetime.now()

    logger.info(
        f"TaskRunner: task_id={task_id}, pipeline={task_pipeline}, "
        f"dry_run={dry_run}, channels={task_channels}"
    )

    # Run the appropriate pipeline
    stage_results: dict = {}
    final_markdown: str = ""
    pipeline_ok: bool = False
    pipeline_error: str | None = None

    try:
        if task_pipeline == "editorial":
            result = _run_editorial_pipeline(config=config, logger=logger)
            pipeline_ok = result.get("ok", False)
            pipeline_error = result.get("error")
            final_markdown = result.get("final_markdown", "")
            # Forward everything useful from editorial result
            stage_results = {k: v for k, v in result.items() if k != "final_markdown"}
        else:
            result = _run_classic_pipeline(config=config, logger=logger)
            pipeline_ok = result.get("ok", False) if isinstance(result, dict) else (result is not None)
            if isinstance(result, dict):
                pipeline_error = result.get("error")
                final_markdown = result.get("final_markdown", "")
                stage_results = {k: v for k, v in result.items() if k != "final_markdown"}
            else:
                # Legacy: result was None (old implementation)
                final_markdown = result or "" if result else ""
                stage_results = {}

        logger.info(
            f"TaskRunner: pipeline completed ok={pipeline_ok}, "
            f"markdown_len={len(final_markdown)}"
        )
    except Exception as e:
        logger.error(f"TaskRunner: pipeline exception: {e}")
        pipeline_ok = False
        pipeline_error = str(e)
        final_markdown = ""

    # Dry run — return without any channel sends
    if dry_run:
        payload = {
            "ok": pipeline_ok,
            "task_id": task_id,
            "pipeline": task_pipeline,
            "dry_run": True,
            "final_markdown": final_markdown,
            "channel_results": [],
            "stage_results": stage_results,
            "error": pipeline_error,
        }
        try:
            append_run_record(
                None,
                _build_run_record(
                    task_id=task_id,
                    config=config,
                    task_pipeline=task_pipeline,
                    started_at=started_at,
                    ended_at=datetime.now(),
                    dry_run=True,
                    ok=pipeline_ok,
                    stage_results=stage_results,
                    channel_results=[],
                    error=pipeline_error,
                ),
            )
        except Exception as exc:
            logger.warning(f"TaskRunner: failed to write run history: {exc}")
        return payload

    # Real run — send to all configured channels
    channel_results: list[dict] = []
    for channel_id in task_channels:
        try:
            ok = _send_content_to_channel(channel_id, final_markdown, config)
            channel_results.append({"channel_id": channel_id, "ok": ok})
            logger.info(f"TaskRunner: sent to channel '{channel_id}': ok={ok}")
        except Exception as e:
            logger.error(f"TaskRunner: failed to send to '{channel_id}': {e}")
            channel_results.append({"channel_id": channel_id, "ok": False, "error": str(e)})

    payload = {
        "ok": pipeline_ok,
        "task_id": task_id,
        "pipeline": task_pipeline,
        "dry_run": False,
        "final_markdown": final_markdown,
        "channel_results": channel_results,
        "stage_results": stage_results,
        "error": pipeline_error,
    }
    try:
        append_run_record(
            None,
            _build_run_record(
                task_id=task_id,
                config=config,
                task_pipeline=task_pipeline,
                started_at=started_at,
                ended_at=datetime.now(),
                dry_run=False,
                ok=pipeline_ok,
                stage_results=stage_results,
                channel_results=channel_results,
                error=pipeline_error,
            ),
        )
    except Exception as exc:
        logger.warning(f"TaskRunner: failed to write run history: {exc}")
    return payload


def _send_content_to_channel(channel_id: str, content: str, config: dict) -> bool:
    """
    Build the full message (header + content + footer/empty) and send via channel.
    """
    settings = config.get("settings", {})
    today_str = datetime.now().strftime("%m-%d")
    title_template = settings.get("report_title", "📅 营销情报早报 | {date}")
    header_msg = f"# {title_template.replace('{date}', today_str)}\n> 正在为您通过 AI 融合检索定向信源与全网热词..."

    if not content:
        empty_msg = settings.get("empty_message", "📭 今日全网无重要更新。")
        return send_to_channel(channel_id, empty_msg)

    # Send header
    if not send_to_channel(channel_id, header_msg):
        return False
    time.sleep(1)

    # Send content blocks
    if not send_to_channel(channel_id, content):
        return False
    time.sleep(1)

    # Send footer
    if settings.get("show_footer", False):
        footer = f"\n{settings.get('footer_text', '')}"
        if not send_to_channel(channel_id, footer):
            return False
        time.sleep(1)

    return True
