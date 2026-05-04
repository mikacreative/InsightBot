from insightbot.signal_desk.patterns import (
    IntentContract,
    get_pattern_contract,
    get_quality_gate_contract,
    list_pattern_contracts,
)


def test_client_opportunity_radar_pattern_contract_exists():
    pattern = get_pattern_contract("client_opportunity_radar")

    assert pattern.id == "client_opportunity_radar"
    assert pattern.status == "published"
    assert "client" in pattern.required_context
    assert "category" in pattern.required_context
    assert pattern.default_quality_gate_id == "client_opportunity_radar_basic_quality"


def test_quality_gate_contract_requires_signal_card_fields():
    gate = get_quality_gate_contract("client_opportunity_radar_basic_quality")

    assert gate.requires_source is True
    assert gate.requires_why_it_matters is True
    assert gate.requires_suggested_action is True
    assert gate.requires_client_relevance is True
    assert gate.min_signal_count == 3


def test_intent_contract_round_trips_to_dict():
    intent = IntentContract(
        pattern_id="client_opportunity_radar",
        room_id="beauty_radar",
        client="Sephora",
        category="beauty retail",
        focus_topics=["AI retail"],
        output_intent="client_conversation",
        time_window="last_7_days",
    )

    assert intent.to_dict()["client"] == "Sephora"
    assert IntentContract.from_dict(intent.to_dict()).focus_topics == ["AI retail"]


def test_list_pattern_contracts_returns_published_patterns():
    patterns = list_pattern_contracts()

    assert any(pattern.id == "client_opportunity_radar" for pattern in patterns)
