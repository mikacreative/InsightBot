from insightbot.signal_desk.patterns import IntentContract
from insightbot.signal_desk.routing import (
    DEFAULT_OUTPUT_INTENT,
    DEFAULT_PATTERN_ID,
    DEFAULT_RESULT_MODE,
    DEFAULT_TIME_WINDOW,
    SignalDeskAccessRequest,
    SignalDeskRoute,
    normalize_output_intent,
    normalize_pattern_id,
    normalize_result_mode,
    normalize_time_window,
    resolve_signal_desk_route,
    route_to_intent_contract,
)


def test_default_route_uses_signal_desk_defaults():
    route = resolve_signal_desk_route(None)

    assert route == SignalDeskRoute(
        pattern_id=DEFAULT_PATTERN_ID,
        time_window=DEFAULT_TIME_WINDOW,
        output_intent=DEFAULT_OUTPUT_INTENT,
        result_mode=DEFAULT_RESULT_MODE,
    )
    assert route.warnings == []


def test_text_can_request_raw_feed_result_mode():
    route = resolve_signal_desk_route({"text": "Show me the raw source feed."})

    assert route.result_mode == "raw_feed"
    assert route.warnings == []


def test_text_can_request_brief_output_result_mode():
    route = resolve_signal_desk_route(SignalDeskAccessRequest(text="需要一份 client brief"))

    assert route.result_mode == "brief_output"
    assert route.warnings == []


def test_explicit_parameters_win_over_text_hints():
    route = resolve_signal_desk_route(
        SignalDeskAccessRequest(
            text="raw feed proposal brief for 30 days",
            pattern_id="client_opportunity_radar",
            time_window="last_14_days",
            output_intent="trend_observation",
            result_mode="selected_signals",
            room_id="room_123",
        )
    )

    assert route.pattern_id == "client_opportunity_radar"
    assert route.time_window == "last_14_days"
    assert route.output_intent == "trend_observation"
    assert route.result_mode == "selected_signals"
    assert route.room_id == "room_123"


def test_output_intent_normalizes_from_text():
    route = resolve_signal_desk_route({"text": "找一些案例灵感和销售角度"})

    assert route.output_intent == "proposal_angle"


def test_output_intent_can_return_internal_inspiration():
    value, warnings = normalize_output_intent(text="找一些案例灵感")

    assert value == "internal_inspiration"
    assert warnings == []


def test_time_window_normalizes_from_text():
    assert normalize_time_window(text="past month trends")[0] == "last_30_days"
    assert normalize_time_window(text="看过去两周")[0] == "last_14_days"
    assert normalize_time_window(text="this week")[0] == "last_7_days"


def test_pattern_id_normalizes_from_text():
    value, warnings = normalize_pattern_id(text="client radar for this category")

    assert value == "client_opportunity_radar"
    assert warnings == []


def test_unknown_explicit_values_fall_back_with_warnings():
    route = resolve_signal_desk_route(
        {
            "pattern_id": "unknown_pattern",
            "time_window": "last_90_days",
            "output_intent": "unknown_intent",
            "result_mode": "spreadsheet",
        }
    )

    assert route.pattern_id == DEFAULT_PATTERN_ID
    assert route.time_window == DEFAULT_TIME_WINDOW
    assert route.output_intent == DEFAULT_OUTPUT_INTENT
    assert route.result_mode == DEFAULT_RESULT_MODE
    assert route.warnings == [
        "Unknown pattern_id 'unknown_pattern'; using client_opportunity_radar.",
        "Unknown time_window 'last_90_days'; using last_7_days.",
        "Unknown output_intent 'unknown_intent'; using client_conversation.",
        "Unknown result_mode 'spreadsheet'; using selected_signals.",
    ]


def test_empty_values_do_not_warn():
    assert normalize_result_mode("", "") == (DEFAULT_RESULT_MODE, [])
    assert normalize_output_intent("", "") == (DEFAULT_OUTPUT_INTENT, [])
    assert normalize_time_window("", "") == (DEFAULT_TIME_WINDOW, [])
    assert normalize_pattern_id("", "") == (DEFAULT_PATTERN_ID, [])


def test_route_to_intent_contract_does_not_include_result_mode():
    route = SignalDeskRoute(
        pattern_id="client_opportunity_radar",
        time_window="last_30_days",
        output_intent="proposal_angle",
        result_mode="raw_feed",
        room_id="route_room",
    )

    intent = route_to_intent_contract(route, room_id="override_room")

    assert isinstance(intent, IntentContract)
    assert intent.to_dict() == {
        "pattern_id": "client_opportunity_radar",
        "room_id": "override_room",
        "client": "",
        "category": "",
        "focus_topics": [],
        "output_intent": "proposal_angle",
        "time_window": "last_30_days",
    }
    assert "result_mode" not in intent.to_dict()


def test_access_request_dict_roundtrip_and_route_dict_output():
    request = SignalDeskAccessRequest(
        text="client opportunity last month brief",
        room_id="room_abc",
        client="Nike",
        category="sports",
        focus_topics=["retail", "community"],
    )

    restored = SignalDeskAccessRequest.from_dict(request.to_dict())
    route = resolve_signal_desk_route(restored)

    assert restored == request
    assert route.to_dict() == {
        "pattern_id": "client_opportunity_radar",
        "time_window": "last_30_days",
        "output_intent": "client_conversation",
        "result_mode": "brief_output",
        "room_id": "room_abc",
        "confidence": "rule_based",
        "warnings": [],
    }
