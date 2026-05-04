from insightbot.signal_desk.signals import signal_items_from_run_result


def test_signal_items_from_structured_shortlist():
    run_result = {
        "task_id": "room_client_radar_beauty",
        "stage_results": {
            "shortlist": [
                {
                    "title": "Brand launches AI shopping assistant",
                    "summary": "A beauty brand launched an AI shopping assistant.",
                    "why_it_matters": "It shows AI moving into retail conversion.",
                    "url": "https://example.com/ai-shopping",
                    "published_at": "2026-05-04",
                    "judgement_lens": ["client_relevance"],
                    "confidence": "high",
                }
            ]
        },
    }

    items = signal_items_from_run_result(
        room_id="client_radar_beauty",
        run_id="run_001",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Brand launches AI shopping assistant"
    assert items[0].why_it_matters == "It shows AI moving into retail conversion."
    assert items[0].source["url"] == "https://example.com/ai-shopping"
    assert items[0].confidence == "high"


def test_signal_items_fallback_to_final_markdown():
    run_result = {
        "final_markdown": "### Platform changes social search\nThis may affect content discovery.",
        "stage_results": {},
    }

    items = signal_items_from_run_result(
        room_id="client_radar_social",
        run_id="run_002",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Platform changes social search"
    assert items[0].confidence == "low"
    assert items[0].source == {}
