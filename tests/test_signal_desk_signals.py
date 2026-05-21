from insightbot.signal_desk.signals import (
    signal_items_from_run_result,
    summarize_signal_output_quality,
)


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


def test_signal_items_from_editorial_intelligence_candidate_shape_have_required_fields():
    run_result = {
        "stage_results": {
            "shortlist": [
                {
                    "source_type": "agent_search",
                    "source_id": "duckduckgo",
                    "title": "Brand launches AI shopping assistant",
                    "summary": "A beauty brand launched an AI shopping assistant.",
                    "url": "https://example.com/ai-shopping",
                    "published_at": "2026-05-04T00:00:00+00:00",
                    "signals": {"provider": "duckduckgo"},
                }
            ]
        },
    }

    items = signal_items_from_run_result(
        room_id="client_radar_beauty",
        run_id="run_ei_001",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Brand launches AI shopping assistant"
    assert items[0].why_it_matters == "A beauty brand launched an AI shopping assistant."
    assert items[0].client_relevance
    assert items[0].suggested_action
    assert items[0].source["url"] == "https://example.com/ai-shopping"


def test_signal_items_from_section_assignments_when_shortlist_missing():
    run_result = {
        "stage_results": {
            "section_assignments": {
                "Client Conversation Starters": [
                    {
                        "title": "Retailer launches AI shelf assistant",
                        "summary": "A retailer is using AI to support in-store recommendations.",
                        "why_it_matters": "It changes retail experience expectations.",
                        "url": "https://example.com/retail-ai",
                        "source_title": "Retail AI Report",
                    }
                ]
            }
        }
    }

    items = signal_items_from_run_result(
        room_id="client_radar_retail",
        run_id="run_assignments",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Retailer launches AI shelf assistant"
    assert items[0].judgement_lens == ["Client Conversation Starters"]
    assert items[0].source == {
        "title": "Retail AI Report",
        "url": "https://example.com/retail-ai",
    }


def test_signal_items_preserve_nested_source_metadata():
    run_result = {
        "stage_results": {
            "shortlist": [
                {
                    "title": "Brand pilots creator commerce",
                    "summary": "The campaign combines creators and store conversion.",
                    "source": {
                        "title": "Campaign Source",
                        "url": "https://example.com/creator-commerce",
                        "published_at": "2026-05-20",
                    },
                }
            ]
        }
    }

    items = signal_items_from_run_result("client_radar_brand", "run_source", run_result)

    assert items[0].source["title"] == "Campaign Source"
    assert items[0].source["url"] == "https://example.com/creator-commerce"
    assert items[0].source["published_at"] == "2026-05-20"


def test_summarize_signal_output_quality_counts_fallback_and_missing_sources():
    structured = signal_items_from_run_result(
        "room_quality",
        "run_quality",
        {
            "stage_results": {
                "shortlist": [
                    {"title": "Signal with source", "url": "https://example.com/source"},
                    {"title": "Signal without source"},
                ]
            }
        },
    )
    fallback = signal_items_from_run_result(
        "room_quality",
        "run_fallback",
        {"stage_results": {}, "final_markdown": "## Fallback signal"},
    )

    summary = summarize_signal_output_quality(structured + fallback)

    assert summary == {
        "signal_count": 3,
        "fallback_count": 1,
        "missing_source_count": 2,
        "structured_count": 2,
        "status": "needs_attention",
        "recommendations": [
            "Review fallback cards before saving; structured shortlist was incomplete.",
            "Add or repair source metadata for signals without source URLs.",
        ],
    }


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


def test_signal_items_from_contract_shaped_shortlist_candidate():
    run_result = {
        "stage_results": {
            "shortlist": [
                {
                    "what_happened": "Retailer expands creator commerce",
                    "why_it_matters": "It changes how brands structure commerce content.",
                    "client_relevance": "Relevant to beauty retailers testing social conversion.",
                    "suggested_action": "Review creator-commerce pilots for the client.",
                }
            ]
        },
    }

    items = signal_items_from_run_result(
        room_id="client_radar_beauty",
        run_id="run_003",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].id
    assert items[0].what_happened == "Retailer expands creator commerce"
    assert items[0].why_it_matters == "It changes how brands structure commerce content."
    assert (
        items[0].client_relevance
        == "Relevant to beauty retailers testing social conversion."
    )
    assert items[0].suggested_action == "Review creator-commerce pilots for the client."


def test_signal_items_fallback_when_shortlist_has_no_dict_candidates():
    run_result = {
        "final_markdown": "## Search platform updates ranking\nBrands may need to adjust content discovery.",
        "stage_results": {"shortlist": ["not a candidate"]},
    }

    items = signal_items_from_run_result(
        room_id="client_radar_social",
        run_id="run_004",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Search platform updates ranking"
    assert items[0].confidence == "low"


def test_signal_items_fallback_when_shortlist_dict_candidate_is_empty():
    run_result = {
        "final_markdown": "## Social platform expands search ads\nTeams may need to revisit channel plans.",
        "stage_results": {"shortlist": [{}]},
    }

    items = signal_items_from_run_result(
        room_id="client_radar_social",
        run_id="run_007",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Social platform expands search ads"
    assert items[0].confidence == "low"


def test_signal_items_fallback_when_stage_results_is_none():
    run_result = {
        "final_markdown": "### Marketplace adds AI ads tool\nThis affects media planning workflows.",
        "stage_results": None,
    }

    items = signal_items_from_run_result(
        room_id="client_radar_media",
        run_id="run_005",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Marketplace adds AI ads tool"
    assert items[0].confidence == "low"


def test_fallback_signal_has_useful_default_fields():
    run_result = {
        "final_markdown": "### Platform changes social search\nThis may affect content discovery.",
        "stage_results": {},
    }

    items = signal_items_from_run_result(
        room_id="client_radar_social",
        run_id="run_006",
        run_result=run_result,
    )

    assert items[0].why_it_matters
    assert items[0].client_relevance
    assert items[0].suggested_action
