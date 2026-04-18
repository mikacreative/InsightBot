from editorial_intelligence.contracts.briefing_result import BriefingResult


def run_editorial_pipeline(*, context: dict) -> BriefingResult:
    """Bootstrap workflow stub for the first editorial skill implementation."""

    return BriefingResult(
        ok=True,
        source_summary={"status": "bootstrap"},
        candidate_pool=[],
        shortlist=[],
        section_assignments={},
        final_brief={"markdown": ""},
        diagnostics={"coverage_gaps": [], "source_failures": []},
    )
