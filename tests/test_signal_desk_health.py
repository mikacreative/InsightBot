from insightbot.signal_desk.health import build_pattern_health_summary
from insightbot.signal_desk.models import BriefingRoom, FeedbackRecord, SavedSignal, SignalItem


def make_room(room_id="beauty_radar") -> BriefingRoom:
    return BriefingRoom(
        id=room_id,
        name="Beauty Radar",
        topic="Beauty retail signals",
        source_pack_ids=["marketing_comms_cn"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance"],
        channels=[],
        schedule={"hour": 8, "minute": 0},
        use_case_template_id="client_opportunity_radar",
    )


def make_signal(
    signal_id="sig_001",
    room_id="beauty_radar",
    confidence="high",
    save_tags=None,
    judgement_lens=None,
) -> SignalItem:
    return SignalItem(
        id=signal_id,
        room_id=room_id,
        run_id="run_001",
        what_happened="Brand launches AI shopping assistant",
        why_it_matters="It affects retail conversion.",
        client_relevance="Beauty and retail clients.",
        suggested_action="Use as a client conversation starter.",
        judgement_lens=judgement_lens or ["client_relevance"],
        source={"title": "Example", "url": "https://example.com"},
        confidence=confidence,
        save_tags=save_tags or [],
    )


def make_saved(signal_id="sig_001", room_id="beauty_radar") -> SavedSignal:
    return SavedSignal(
        id=f"saved_{signal_id}",
        signal=make_signal(signal_id=signal_id, room_id=room_id).to_dict(),
        room_id=room_id,
    )


def make_feedback(action="useful", signal_id="sig_001", room_id="beauty_radar") -> FeedbackRecord:
    return FeedbackRecord(
        id=f"feedback_{signal_id}_{action}",
        signal_id=signal_id,
        room_id=room_id,
        action=action,
    )


def test_build_pattern_health_summary_returns_no_data_without_inputs():
    summary = build_pattern_health_summary(make_room(), [], [])

    assert summary == {
        "room_id": "beauty_radar",
        "pattern_id": "client_opportunity_radar",
        "status": "no_data",
        "saved_count": 0,
        "feedback_count": 0,
        "latest_signal_count": 0,
        "fallback_signal_count": 0,
        "negative_feedback_count": 0,
        "positive_feedback_count": 0,
        "recommendations": ["No pattern data yet. Run this room and review the first signal cards."],
    }


def test_build_pattern_health_summary_marks_saved_room_healthy():
    summary = build_pattern_health_summary(
        make_room(),
        [make_saved()],
        [make_feedback("useful")],
        latest_signals=[make_signal()],
    )

    assert summary["status"] == "healthy"
    assert summary["saved_count"] == 1
    assert summary["feedback_count"] == 1
    assert summary["latest_signal_count"] == 1
    assert summary["negative_feedback_count"] == 0
    assert summary["fallback_signal_count"] == 0
    assert summary["positive_feedback_count"] == 1
    assert summary["recommendations"] == ["Pattern is healthy. Keep collecting examples and feedback."]


def test_build_pattern_health_summary_warns_on_fallback_signals():
    summary = build_pattern_health_summary(
        make_room(),
        [make_saved()],
        [],
        latest_signals=[
            make_signal(signal_id="sig_low_fallback", confidence="low", save_tags=["fallback"]),
            make_signal(signal_id="sig_manual_review", judgement_lens=["manual_review"]),
        ],
    )

    assert summary["status"] == "needs_attention"
    assert summary["fallback_signal_count"] == 2
    assert "Review fallback cards and tighten source packs or judgement lenses." in summary["recommendations"]


def test_build_pattern_health_summary_warns_on_negative_feedback():
    summary = build_pattern_health_summary(
        make_room(),
        [make_saved()],
        [
            make_feedback("not_relevant"),
            make_feedback("too_shallow", signal_id="sig_002"),
            make_feedback("already_known", signal_id="sig_003"),
            make_feedback("good_for_client", signal_id="sig_004"),
        ],
    )

    assert summary["status"] == "needs_attention"
    assert summary["feedback_count"] == 4
    assert summary["negative_feedback_count"] == 3
    assert summary["positive_feedback_count"] == 1
    assert "Inspect negative feedback and adjust pattern context before scaling." in summary["recommendations"]


def test_build_pattern_health_summary_filters_records_to_current_room():
    summary = build_pattern_health_summary(
        make_room(),
        [make_saved(), make_saved(signal_id="sig_other", room_id="other_room")],
        [make_feedback("useful"), make_feedback("not_relevant", signal_id="sig_other", room_id="other_room")],
        latest_signals=[make_signal(), make_signal(signal_id="sig_other", room_id="other_room")],
    )

    assert summary["status"] == "healthy"
    assert summary["saved_count"] == 1
    assert summary["feedback_count"] == 1
    assert summary["latest_signal_count"] == 1
    assert summary["negative_feedback_count"] == 0


def test_build_pattern_health_summary_accepts_signalitem_and_dict_latest_signals():
    dict_signal_without_room = {
        "id": "sig_dict",
        "confidence": "low",
        "save_tags": ["fallback"],
        "judgement_lens": ["client_relevance"],
    }
    dict_signal_other_room = {
        "id": "sig_other",
        "room_id": "other_room",
        "confidence": "low",
        "save_tags": ["fallback"],
        "judgement_lens": ["manual_review"],
    }

    summary = build_pattern_health_summary(
        make_room(),
        [],
        [],
        latest_signals=[
            make_signal(signal_id="sig_obj", judgement_lens=["manual_review"]),
            dict_signal_without_room,
            dict_signal_other_room,
        ],
    )

    assert summary["status"] == "needs_attention"
    assert summary["latest_signal_count"] == 2
    assert summary["fallback_signal_count"] == 2
    assert summary["recommendations"] == [
        "Review fallback cards and tighten source packs or judgement lenses.",
        "Save useful signals so the pattern has positive examples.",
    ]
