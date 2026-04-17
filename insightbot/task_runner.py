"""
Task execution engine.

run_task() assembles a task's config and dispatches to the correct pipeline
(editorial or classic). It owns all channel sends — pipelines themselves only
return final_markdown and do not call any channel APIs.
"""

import logging
import time
from datetime import datetime
from typing import Callable

from .channels import send_to_channel
from .run_history import append_run_record

logger = logging.getLogger("TaskRunner")


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
    from .editorial_pipeline import run_editorial_pipeline

    return run_editorial_pipeline(config=config, logger=logger)


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
    send_to_channel(channel_id, header_msg)
    time.sleep(1)

    # Send content blocks
    send_to_channel(channel_id, content)
    time.sleep(1)

    # Send footer
    if settings.get("show_footer", False):
        footer = f"\n{settings.get('footer_text', '')}"
        send_to_channel(channel_id, footer)
        time.sleep(1)

    return True
