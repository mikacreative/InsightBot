from insightbot.signal_desk.models import BriefingRoom
from scripts.ui.signal_desk.briefs import build_brief_room_options
from scripts.ui.signal_desk.signals import build_signal_workspace_rows


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
    )


def test_build_signal_workspace_rows_summarizes_room_health():
    rooms = {"beauty_radar": make_room()}
    saved = [{"id": "saved_1", "room_id": "beauty_radar", "signal": {}}]
    feedback = [{"id": "fb_1", "room_id": "beauty_radar", "action": "useful"}]

    rows = build_signal_workspace_rows(rooms, saved, feedback)

    assert rows == [
        {
            "room_id": "beauty_radar",
            "room_name": "Beauty Radar",
            "pattern_id": "client_opportunity_radar",
            "status": "healthy",
            "saved_count": 1,
            "feedback_count": 1,
            "recommendations": ["Pattern is healthy. Keep collecting examples and feedback."],
        }
    ]


def test_build_brief_room_options_only_returns_rooms_with_saved_signals():
    rooms = {
        "beauty_radar": make_room("beauty_radar"),
        "auto_radar": make_room("auto_radar"),
    }
    saved = [
        {"id": "saved_1", "room_id": "beauty_radar"},
        {"id": "saved_other", "room_id": "missing_room"},
    ]

    assert build_brief_room_options(rooms, saved) == ["beauty_radar"]
