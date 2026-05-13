from editorial_intelligence.contracts.execution_mode import ExecutionMode
from editorial_intelligence.integrations.insightbot import (
    _map_legacy_result,
    run_from_insightbot_config,
)


def test_map_legacy_result_exposes_structured_fields():
    legacy = {
        "ok": True,
        "global_candidates": [{"title": "A"}, {"title": "B"}],
        "screened_result": {
            "screened": [{"title": "A"}],
            "selection_mode": "chunked",
            "global_shortlist_size": 1,
        },
        "assignment_result": {
            "category_candidate_map": {
                "产品动态": [{"title": "A"}],
                "市场信号": [],
            }
        },
        "category_results": {},
        "final_markdown": "## Brief",
        "error": None,
    }

    result = _map_legacy_result(legacy, execution_mode=ExecutionMode.PRODUCTION_RUN)

    assert result.ok is True
    assert result.source_summary["candidate_count"] == 2
    assert len(result.shortlist) == 1
    assert result.final_brief["markdown"] == "## Brief"
    assert result.diagnostics["selection_mode"] == "chunked"


def test_run_from_insightbot_config_uses_legacy_pipeline(monkeypatch):
    def fake_run_editorial_pipeline(*, config, logger):
        assert config["feeds"] == {}
        return {
            "ok": False,
            "global_candidates": [],
            "screened_result": {},
            "assignment_result": {"category_candidate_map": {}},
            "category_results": {},
            "final_markdown": "",
            "error": "boom",
        }

    monkeypatch.setattr(
        "editorial_intelligence.integrations.insightbot._run_legacy_pipeline",
        fake_run_editorial_pipeline,
    )

    result = run_from_insightbot_config(
        config={"feeds": {}, "ai": {"editorial_pipeline": {"enabled": True}}},
        execution_mode=ExecutionMode.DIAGNOSTIC_RUN,
    )

    assert result.ok is False
    assert result.diagnostics["error"] == "boom"
    assert "legacy_pipeline_failed" in result.diagnostics["coverage_gaps"]
