from insightbot.signal_desk.presets import (
    get_editorial_preset,
    get_judgement_lenses,
    get_use_case_template,
)
from insightbot.signal_desk.source_packs import get_source_pack, merge_source_packs


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

    assert len(rss) == len(set(rss))
    assert len(queries) == len(set(queries))
    assert merged["search"]["enabled"] is True
