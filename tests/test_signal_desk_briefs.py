import json

import pytest

from insightbot.paths import signal_desk_briefs_file_path
from insightbot.signal_desk.briefs import create_brief_from_saved_signals, list_briefs
from insightbot.signal_desk.models import BriefingRoom


def make_room(room_id: str = "client_radar_beauty") -> BriefingRoom:
    return BriefingRoom(
        id=room_id,
        name="Beauty Client Radar",
        topic="Beauty retail signals",
        source_pack_ids=["beauty_sources"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance"],
        channels=["dry_run"],
        schedule={"hour": 8, "minute": 30},
    )


def make_saved_signal(
    signal_id: str = "saved_001",
    room_id: str = "client_radar_beauty",
    url: str = "https://example.com/ai-shopping",
) -> dict:
    return {
        "id": signal_id,
        "room_id": room_id,
        "signal": {
            "id": f"sig_{signal_id}",
            "what_happened": "Brand launches AI shopping assistant",
            "why_it_matters": "It affects retail conversion.",
            "suggested_action": "Use as a client conversation starter.",
            "source": {"title": "Example", "url": url},
        },
    }


def section_bullets(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    start = lines.index(f"## {heading}") + 1
    bullets = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            bullets.append(line)
    return bullets


def test_signal_desk_briefs_file_path_uses_default_and_env_override(tmp_path, monkeypatch):
    assert signal_desk_briefs_file_path(str(tmp_path)) == str(tmp_path / "data" / "signal_desk" / "briefs.jsonl")

    override = tmp_path / "custom" / "briefs.jsonl"
    monkeypatch.setenv("SIGNAL_DESK_BRIEFS_FILE", str(override))

    assert signal_desk_briefs_file_path(str(tmp_path)) == str(override)


def test_create_brief_from_saved_signals_appends_artifact(tmp_path):
    room = make_room()

    artifact = create_brief_from_saved_signals(
        room,
        [make_saved_signal("saved_001"), make_saved_signal("saved_002")],
        output_intent="client_follow_up",
        bot_dir=str(tmp_path),
    )

    records = list_briefs(room_id=room.id, bot_dir=str(tmp_path))
    assert artifact.id.startswith("brief_")
    assert artifact.room_id == room.id
    assert artifact.title == "Beauty Client Radar Brief"
    assert artifact.output_intent == "client_follow_up"
    assert artifact.source_signal_ids == ["saved_001", "saved_002"]
    assert records == [artifact.to_dict()]


def test_create_brief_filters_other_room_saved_signals(tmp_path):
    room = make_room()

    artifact = create_brief_from_saved_signals(
        room,
        [
            make_saved_signal("saved_001", room_id=room.id),
            make_saved_signal("saved_other", room_id="another_room"),
        ],
        bot_dir=str(tmp_path),
    )

    assert artifact.source_signal_ids == ["saved_001"]
    assert "saved_other" not in artifact.markdown


def test_create_brief_raises_when_room_has_no_saved_signals(tmp_path):
    room = make_room()

    with pytest.raises(ValueError, match="No saved signals"):
        create_brief_from_saved_signals(
            room,
            [make_saved_signal("saved_other", room_id="another_room")],
            bot_dir=str(tmp_path),
        )


def test_client_conversation_brief_uses_work_ready_sections(tmp_path):
    artifact = create_brief_from_saved_signals(
        make_room(),
        [make_saved_signal()],
        output_intent="client_conversation",
        bot_dir=str(tmp_path),
    )

    assert "# Beauty Client Radar - Client Conversation Brief" in artifact.markdown
    assert "## Executive takeaways" in artifact.markdown
    assert "## Client conversation starters" in artifact.markdown
    assert "## Source signals" in artifact.markdown
    assert "It affects retail conversion." in artifact.markdown


def test_proposal_angle_brief_uses_pitch_sections(tmp_path):
    artifact = create_brief_from_saved_signals(
        make_room(),
        [make_saved_signal()],
        output_intent="proposal_angle",
        bot_dir=str(tmp_path),
    )

    assert "# Beauty Client Radar - Proposal Angle Brief" in artifact.markdown
    assert "## Pitch angles" in artifact.markdown
    assert "## Proof points" in artifact.markdown


def test_proposal_angle_pitch_and_proof_bullets_are_distinct(tmp_path):
    artifact = create_brief_from_saved_signals(
        make_room(),
        [make_saved_signal()],
        output_intent="proposal_angle",
        bot_dir=str(tmp_path),
    )

    pitch_bullets = section_bullets(artifact.markdown, "Pitch angles")
    proof_bullets = section_bullets(artifact.markdown, "Proof points")

    assert pitch_bullets
    assert proof_bullets
    assert pitch_bullets != proof_bullets


def test_sparse_saved_signal_payloads_do_not_render_empty_rows(tmp_path):
    room = make_room()

    artifact = create_brief_from_saved_signals(
        room,
        [
            {"id": "saved_string", "room_id": room.id, "signal": "not a dict"},
            {"id": "saved_minimal", "room_id": room.id, "signal": {"what_happened": "Minimal signal title"}},
        ],
        output_intent="client_conversation",
        bot_dir=str(tmp_path),
    )

    assert "- :" not in artifact.markdown
    assert "Untitled signal" in artifact.markdown
    assert "Minimal signal title" in artifact.markdown
    assert "- URL: " not in artifact.markdown


def test_list_briefs_skips_malformed_jsonl(tmp_path):
    artifact = create_brief_from_saved_signals(make_room(), [make_saved_signal()], bot_dir=str(tmp_path))
    path = signal_desk_briefs_file_path(str(tmp_path))
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ this is not json }\n")
        f.write(json.dumps({"id": "brief_other", "room_id": "another_room"}) + "\n")

    records = list_briefs(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert records == [artifact.to_dict()]


def test_brief_markdown_contains_signal_fields(tmp_path):
    artifact = create_brief_from_saved_signals(make_room(), [make_saved_signal()], bot_dir=str(tmp_path))

    assert "# Beauty Client Radar - Client Conversation Brief" in artifact.markdown
    assert "Source signals: 1" in artifact.markdown
    assert "Brand launches AI shopping assistant" in artifact.markdown
    assert "It affects retail conversion." in artifact.markdown
    assert "Use as a client conversation starter." in artifact.markdown
    assert "https://example.com/ai-shopping" in artifact.markdown
