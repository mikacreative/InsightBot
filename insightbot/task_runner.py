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

logger = logging.getLogger("TaskRunner")


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
            from .editorial_pipeline import run_editorial_pipeline

            result = run_editorial_pipeline(config=config, logger=logger)
            pipeline_ok = result.get("ok", False)
            pipeline_error = result.get("error")
            final_markdown = result.get("final_markdown", "")
            # Forward everything useful from editorial result
            stage_results = {k: v for k, v in result.items() if k != "final_markdown"}
        else:
            from .smart_brief_runner import run_task as run_classic_task

            result = run_classic_task(config=config, logger=logger)
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
        return {
            "ok": pipeline_ok,
            "task_id": task_id,
            "pipeline": task_pipeline,
            "dry_run": True,
            "final_markdown": final_markdown,
            "channel_results": [],
            "stage_results": stage_results,
            "error": pipeline_error,
        }

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

    return {
        "ok": pipeline_ok,
        "task_id": task_id,
        "pipeline": task_pipeline,
        "dry_run": False,
        "final_markdown": final_markdown,
        "channel_results": channel_results,
        "stage_results": stage_results,
        "error": pipeline_error,
    }


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
