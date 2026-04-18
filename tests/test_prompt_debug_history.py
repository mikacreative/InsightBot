from insightbot.prompt_debug_history import (
    MAX_HISTORY_ITEMS,
    append_prompt_debug_history,
    load_prompt_debug_history,
    make_compare_record,
    make_draft_run_record,
)


def test_append_prompt_debug_history_keeps_recent_20(tmp_path):
    for index in range(MAX_HISTORY_ITEMS + 5):
        append_prompt_debug_history(
            str(tmp_path),
            {
                "id": str(index),
                "created_at": f"2026-04-07T10:{index:02d}:00",
                "category": "营销",
                "mode": "draft_run",
            },
        )

    history = load_prompt_debug_history(str(tmp_path))
    assert len(history) == MAX_HISTORY_ITEMS
    assert history[0]["id"] == str(MAX_HISTORY_ITEMS + 4)
    assert history[-1]["id"] == "5"


def test_make_draft_run_record_shapes_expected_fields():
    record = make_draft_run_record(
        category="💡 营销行业",
        candidate_count=14,
        result={"status": "empty", "selected_items": []},
        using_fallback_candidates=True,
        draft_prompt="只保留中国大陆营销案例",
    )

    assert record["mode"] == "draft_run"
    assert record["candidate_count"] == 14
    assert record["draft_status"] == "empty"
    assert record["using_fallback_candidates"] is True
    assert "中国大陆营销案例" in record["draft_prompt_excerpt"]


def test_make_compare_record_contains_saved_and_draft_counts():
    record = make_compare_record(
        category="📢 政策导向",
        candidate_count=20,
        saved_result={"status": "success", "selected_items": [{"url": "https://example.com/1"}]},
        draft_result={"status": "empty", "selected_items": []},
        using_fallback_candidates=False,
        draft_prompt="只保留中国大陆官方政策信息",
    )

    assert record["mode"] == "compare"
    assert record["saved_selected_count"] == 1
    assert record["draft_selected_count"] == 0
    assert record["saved_status"] == "success"
    assert record["draft_status"] == "empty"
