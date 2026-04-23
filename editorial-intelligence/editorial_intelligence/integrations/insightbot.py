import logging

from editorial_intelligence.contracts.briefing_result import BriefingResult
from editorial_intelligence.contracts.execution_mode import ExecutionMode


def _default_logger():
    logger = logging.getLogger("editorial_intelligence.insightbot_bridge")
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


def _map_legacy_result(result: dict, *, execution_mode: ExecutionMode) -> BriefingResult:
    screened_result = result.get("screened_result", {}) or {}
    assignment_result = result.get("assignment_result", {}) or {}
    category_results = result.get("category_results", {}) or {}
    global_candidates = result.get("global_candidates", []) or []
    shortlist = screened_result.get("screened", []) or []
    diagnostics = {
        "execution_mode": execution_mode.value,
        "error": result.get("error"),
        "coverage_gaps": [],
        "source_failures": [],
        "selection_mode": screened_result.get("selection_mode"),
        "global_shortlist_size": screened_result.get("global_shortlist_size", len(shortlist)),
    }

    if result.get("error"):
        diagnostics["coverage_gaps"].append("legacy_pipeline_failed")

    return BriefingResult(
        ok=bool(result.get("ok")),
        source_summary={
            "candidate_count": len(global_candidates),
            "shortlist_size": len(shortlist),
            "assigned_category_count": len(
                [k for k, v in assignment_result.get("category_candidate_map", {}).items() if v]
            ),
        },
        candidate_pool=global_candidates,
        shortlist=shortlist,
        section_assignments=assignment_result.get("category_candidate_map", {}),
        final_brief={"markdown": result.get("final_markdown", "")},
        diagnostics=diagnostics,
    )


def _run_legacy_pipeline(*, config: dict, logger):
    from insightbot.editorial_pipeline import run_editorial_pipeline

    return run_editorial_pipeline(config=config, logger=logger)


def run_from_insightbot_config(
    *,
    config: dict,
    logger=None,
    execution_mode: ExecutionMode = ExecutionMode.PRODUCTION_RUN,
) -> BriefingResult:
    """
    Migration bridge for running the existing InsightBot editorial pipeline through
    the new editorial-intelligence result contract.
    """
    active_logger = logger or _default_logger()
    result = _run_legacy_pipeline(config=config, logger=active_logger)
    return _map_legacy_result(result, execution_mode=execution_mode)
