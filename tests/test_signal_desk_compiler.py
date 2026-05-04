from insightbot.signal_desk.compiler import compile_room_to_task
from insightbot.signal_desk.models import BriefingRoom
from insightbot.task_validation import validate_task_definition


def test_compile_room_to_task_outputs_existing_task_shape():
    room = BriefingRoom(
        id="client_radar_beauty",
        name="Beauty Client Opportunity Radar",
        topic="Beauty and retail marketing signals in China",
        source_pack_ids=["marketing_comms_cn", "ai_martech"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance", "pitch_potential"],
        channels=["wecom_main"],
        schedule={"hour": 8, "minute": 0},
        focus_areas=["brand campaigns", "retail activation"],
    )

    task_id, task_def = compile_room_to_task(room)

    assert task_id == "room_client_radar_beauty"
    assert task_def["name"] == "Beauty Client Opportunity Radar"
    assert task_def["pipeline"] == "editorial"
    assert task_def["_editorial_pipeline_mode"] == "editorial-intelligence"
    assert task_def["_signal_desk_room_id"] == "client_radar_beauty"
    assert task_def["_signal_desk_compiled"] is True
    assert task_def["channels"] == ["wecom_main"]
    assert task_def["schedule"] == {"hour": 8, "minute": 0}
    assert task_def["search"]["enabled"] is True
    assert "Marketing Communications" in task_def["feeds"]
    assert task_def["pipeline_config"]["shortlist_size"] == 8
    assert any("Client Relevance" in rule for rule in task_def["pipeline_config"]["selection_rules"])
    assert all(isinstance(query, dict) for query in task_def["search"]["queries"])
    assert validate_task_definition("room_client_radar_beauty", task_def, {"channels": {"wecom_main": {}}})["is_runnable"] is True


def test_compile_room_adds_room_focus_and_topic_to_policy():
    room = BriefingRoom(
        id="client_radar_ai",
        name="AI Client Radar",
        topic="AI marketing opportunities",
        source_pack_ids=["ai_martech"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["strategic_implication"],
        channels=[],
        schedule={"hour": 9, "minute": 30},
        focus_areas=["AI agent", "content workflow"],
    )

    _, task_def = compile_room_to_task(room)
    rules = "\n".join(task_def["pipeline_config"]["selection_rules"])

    assert "AI marketing opportunities" in rules
    assert "AI agent" in rules
    assert "content workflow" in rules
