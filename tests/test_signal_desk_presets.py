from insightbot.signal_desk.presets import (
    get_editorial_preset,
    get_judgement_lenses,
    get_use_case_template,
)
from insightbot.signal_desk.source_packs import get_source_pack, merge_source_packs
from insightbot.task_validation import validate_task_definition
from scripts.ui.signal_desk.rooms import _build_signal_desk_inspector


def test_client_opportunity_radar_defaults_exist():
    template = get_use_case_template("client_opportunity_radar")
    preset = get_editorial_preset("client_opportunity_radar")
    lenses = get_judgement_lenses(["client_relevance", "pitch_potential"])

    assert template["default_editorial_preset_id"] == "client_opportunity_radar"
    assert "suggested action" in " ".join(preset["quality_checks"]).lower()
    assert [lens["id"] for lens in lenses] == [
        "client_relevance",
        "pitch_potential",
    ]


def test_signal_desk_inspector_exposes_trust_preset_and_lens_metadata():
    template = get_use_case_template("client_opportunity_radar")
    inspector = _build_signal_desk_inspector(
        template=template,
        source_packs=[get_source_pack("marketing_comms_cn")],
        judgement_lenses=get_judgement_lenses(["client_relevance", "pitch_potential"]),
    )

    pack = inspector["source_packs"][0]
    assert pack["coverage"]
    assert pack["limitations"]
    assert pack["bias"]
    assert pack["freshness"] == "daily"
    assert inspector["editorial_preset"]["selection_rules"]
    assert inspector["editorial_preset"]["quality_checks"]
    assert [lens["core_question"] for lens in inspector["judgement_lenses"]]


def test_source_pack_has_trust_metadata():
    pack = get_source_pack("marketing_comms_cn")

    assert pack["coverage"]
    assert pack["limitations"]
    assert "China-heavy" in pack["bias"]
    assert pack["freshness"] == "daily"


def test_merge_source_packs_dedupes_feeds_and_queries():
    merged = merge_source_packs(
        [
            get_source_pack("marketing_comms_cn"),
            get_source_pack("marketing_comms_cn"),
        ]
    )

    rss = merged["feeds"]["Marketing Communications"]["rss"]
    queries = merged["search"]["queries"]
    keywords = [query["keywords"] for query in queries]

    assert len(rss) == len(set(rss))
    assert all(isinstance(query, dict) for query in queries)
    assert all(query.get("keywords") for query in queries)
    assert len(keywords) == len(set(keywords))
    assert merged["search"]["enabled"] is True


def test_merge_source_packs_dedupes_rss_by_url_before_comment():
    merged = merge_source_packs(
        [
            {
                "id": "pack_a",
                "name": "Pack A",
                "feeds": {
                    "Marketing Communications": {
                        "rss": ["https://example.com/feed # First label"],
                        "keywords": [],
                    }
                },
                "search": {"enabled": False, "queries": []},
            },
            {
                "id": "pack_b",
                "name": "Pack B",
                "feeds": {
                    "Marketing Communications": {
                        "rss": ["https://example.com/feed # Second label"],
                        "keywords": [],
                    }
                },
                "search": {"enabled": False, "queries": []},
            },
        ]
    )

    rss = merged["feeds"]["Marketing Communications"]["rss"]

    assert rss == ["https://example.com/feed # First label"]


def test_merged_search_queries_validate_with_task_definition():
    merged = merge_source_packs([get_source_pack("marketing_comms_cn")])
    task_def = {
        "feeds": merged["feeds"],
        "search": merged["search"],
        "schedule": {"hour": 8, "minute": 0},
        "channels": ["wecom_main"],
        "pipeline": "editorial",
        "pipeline_config": {"shortlist_size": 8},
    }
    channels_data = {"channels": {"wecom_main": {"name": "WeCom Main"}}}

    result = validate_task_definition("signal_desk_smoke", task_def, channels_data)

    assert result["summary"]["search_query_count"] > 0
