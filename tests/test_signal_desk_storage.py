from insightbot.paths import (
    signal_desk_dir,
    signal_desk_rooms_file_path,
    signal_desk_saved_signals_file_path,
    signal_desk_feedback_file_path,
)
from insightbot.signal_desk.models import BriefingRoom


def test_signal_desk_paths_respect_bot_dir(tmp_path):
    bot_dir = str(tmp_path)

    assert signal_desk_dir(bot_dir) == str(tmp_path / "data" / "signal_desk")
    assert signal_desk_rooms_file_path(bot_dir) == str(tmp_path / "data" / "signal_desk" / "rooms.json")
    assert signal_desk_saved_signals_file_path(bot_dir) == str(tmp_path / "data" / "signal_desk" / "saved_signals.jsonl")
    assert signal_desk_feedback_file_path(bot_dir) == str(tmp_path / "data" / "signal_desk" / "feedback.jsonl")


def test_briefing_room_round_trip_dict():
    room = BriefingRoom(
        id="client_radar_beauty",
        name="Beauty Client Opportunity Radar",
        topic="Beauty and retail marketing signals in China",
        source_pack_ids=["marketing_comms_cn"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance", "pitch_potential"],
        channels=["wecom_main"],
        schedule={"hour": 8, "minute": 0},
    )

    payload = room.to_dict()
    restored = BriefingRoom.from_dict(payload)

    assert restored.id == "client_radar_beauty"
    assert restored.compiled_task_id == "room_client_radar_beauty"
    assert restored.use_case_template_id == "client_opportunity_radar"
    assert restored.channels == ["wecom_main"]
    assert restored.schedule == {"hour": 8, "minute": 0}
