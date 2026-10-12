"""Safety and semantic binding tests for the isolated, fictional workflow POC."""
import copy
import json

import pytest

from insightbot.signal_desk.workflow_poc import (
    apply_operations,
    compile_flow,
    default_plan,
    modules,
    plan_digest,
    validate_plan,
)


def _edge(source, target):
    return {"id": f"edge_{source}_{target}", "source": source, "target": target}


def _compile(plan):
    return compile_flow(plan, callback_base="http://127.0.0.1:18977", callback_token="fictional-test-callback-token")


def test_catalog_and_plan_copies_cannot_modify_shared_defaults():
    first = modules()
    first[0]["default_config"]["keywords"].append("changed")
    first[0]["id"] = "custom.remote_script"
    assert modules()[0]["id"] == "source.fixture"
    assert "changed" not in default_plan()["nodes"][0]["config"]["keywords"]
    plan = default_plan()
    normalized = validate_plan(plan)
    normalized["nodes"][0]["config"]["keywords"].append("other")
    assert "other" not in plan["nodes"][0]["config"]["keywords"]


def test_add_competitor_changes_real_flow_dependencies_and_keeps_old_plan():
    original = default_plan()
    changed = apply_operations(original, [{"op": "add_competitor", "competitors": ["泊岸（虚构）", "森岭（虚构）"], "focus": "比较便携与防漏的证据"}])
    assert original == default_plan()
    assert changed["version"] == 2
    by_id = {node["id"]: node for node in changed["nodes"]}
    assert by_id["competitors"]["config"]["competitors"] == ["泊岸（虚构）", "森岭（虚构）"]
    assert by_id["compare"]["config"]["focus"] == "比较便携与防漏的证据"
    tasks = {item["task"]["id"]: item for item in _compile(changed)["tasks"][0]["tasks"]}
    assert tasks["compare"]["dependsOn"] == ["collect", "competitors"]
    assert tasks["summary"]["dependsOn"] == ["compare"]
    assert tasks["competitors"]["task"]["uri"].endswith("/nodes/competitors")
    assert "\"module\": \"method.compare\"" in tasks["compare"]["task"]["body"]
    assert plan_digest(changed) != plan_digest(original)


def test_repeating_same_competitor_is_a_noop_and_adding_one_merges_the_source():
    compared = apply_operations(default_plan(), [{"op": "add_competitor", "name": "泊岸（虚构）"}])
    assert apply_operations(compared, [{"op": "add_competitor", "name": "泊岸（虚构）"}]) == compared
    changed = apply_operations(compared, [{"op": "add_competitor", "name": "森岭（虚构）"}])
    assert changed["version"] == 3
    assert len(changed["nodes"]) == len(compared["nodes"])


def test_layout_changes_preserve_approval_version_and_digest():
    original = default_plan()
    moved = apply_operations(original, [{"op": "move_node", "node_id": "summary", "position": {"x": 513.25, "y": -30}}])
    assert moved["version"] == original["version"]
    assert moved["nodes"][1]["position"] == {"x": 513.25, "y": -30.0}
    assert plan_digest(moved) == plan_digest(original)
    assert _compile(moved) == _compile(original)


def test_semantic_transaction_advances_once_and_pauses_inherited_schedule():
    scheduled = apply_operations(default_plan(), [{"op": "set_schedule", "schedule": {"enabled": True, "mode": "daily", "time": "08:30"}}])
    changed = apply_operations(scheduled, [
        {"op": "set_question", "question": "虚构品牌的通勤杯，防漏卖点有什么证据？"},
        {"op": "update_node", "node_id": "collect", "config": {"keywords": ["防漏", "通勤"]}},
        {"op": "update_node", "node_id": "publish", "patch": {"config": {"channel": "wecom_simulated"}}},
    ])
    assert changed["version"] == scheduled["version"] + 1
    assert changed["schedule"]["enabled"] is False
    assert "triggers" not in _compile(changed)
    assert _compile(scheduled)["triggers"][0]["cron"] == "30 8 * * *"
    assert changed["nodes"][0]["config"]["keywords"] == ["防漏", "通勤"]


def test_explicit_new_schedule_can_accompany_semantic_changes():
    updated = apply_operations(default_plan(), [
        {"op": "add_competitor", "competitors": ["泊岸（虚构）"]},
        {"op": "set_schedule", "schedule": {"enabled": True, "mode": "weekly", "time": "10:05", "weekdays": [7, 1, 1]}},
    ])
    trigger = _compile(updated)["triggers"][0]
    assert updated["version"] == 2
    assert updated["schedule"]["enabled"] is True
    assert trigger["cron"] == "5 10 * * 1,0"
    assert trigger["timezone"] == "Asia/Shanghai"
    assert trigger["allowConcurrent"] is False
    assert trigger["recoverMissedSchedules"] == "NONE"


def test_once_schedule_is_single_explicit_date_not_repeating_cron():
    plan = apply_operations(default_plan(), [{"op": "set_schedule", "schedule": {"enabled": True, "mode": "once", "at": "2030-10-07T10:30:25"}}])
    trigger = _compile(plan)["triggers"][0]
    assert trigger["type"] == "io.kestra.plugin.core.trigger.ScheduleOnDates"
    assert trigger["dates"] == ["2030-10-07T10:30:25+08:00"]
    assert "cron" not in trigger


def test_cycle_and_disconnected_research_are_rejected():
    cyclic = default_plan()
    cyclic["nodes"].insert(2, {"id": "extra", "module": "method.summary", "label": "补充研究", "position": {"x": 500, "y": 300}, "config": {}})
    cyclic["edges"].extend([_edge("summary", "extra"), _edge("extra", "summary")])
    with pytest.raises(ValueError, match="循环"):
        validate_plan(cyclic)
    disconnected = default_plan()
    disconnected["nodes"].append({"id": "extra", "module": "method.summary", "position": {"x": 300, "y": 400}, "config": {}})
    disconnected["edges"].append(_edge("collect", "extra"))
    with pytest.raises(ValueError, match="未连接"):
        validate_plan(disconnected)


def test_canvas_rewiring_cannot_bypass_review_and_invalid_edits_are_atomic():
    original = default_plan()
    before = copy.deepcopy(original)
    with pytest.raises(ValueError, match="不能绕过审批"):
        apply_operations(original, [
            {"op": "set_question", "question": "这个修改不应保存"},
            {"op": "replace_edges", "edges": [_edge("collect", "summary"), _edge("summary", "review"), _edge("summary", "publish")]},
        ])
    assert original == before
    with pytest.raises(ValueError, match="循环"):
        plan = default_plan()
        plan["edges"].append(_edge("review", "summary"))
        validate_plan(plan)


def test_compare_requires_distinct_brand_and_competitor_inputs():
    plan = default_plan()
    plan["nodes"][1]["module"] = "method.compare"
    with pytest.raises(ValueError, match="品牌与竞品"):
        validate_plan(plan)


def test_review_cannot_accept_comparison_without_a_finished_draft():
    compared = apply_operations(default_plan(), [{"op": "add_competitor", "name": "泊岸（虚构）"}])
    with pytest.raises(ValueError, match="已形成稿件"):
        apply_operations(compared, [{"op": "replace_edges", "edges": [
            _edge("collect", "summary"), _edge("summary", "compare"),
            _edge("competitors", "compare"), _edge("compare", "review"),
            _edge("review", "publish"),
        ]}])


@pytest.mark.parametrize("mutate, message", [
    (lambda plan: plan["nodes"][0].update(module="source.remote_script"), "尚未开放"),
    (lambda plan: plan["nodes"][0]["config"].update(url="https://example.com"), "不支持"),
    (lambda plan: plan["nodes"][0].update(id="collect{{ secret('TEST') }}"), "只能使用"),
    (lambda plan: plan["nodes"][0]["position"].update(x=float("nan")), "有限数字"),
    (lambda plan: plan["brand"].update(id="real_customer"), "虚构品牌"),
    (lambda plan: plan["schedule"].update(timezone="Etc/UTC"), "上海时间"),
    (lambda plan: plan["schedule"].update(mode="weekly", weekdays=[]), "执行日"),
    (lambda plan: plan["schedule"].update(enabled=True, mode="once", at=None), "执行日期"),
])
def test_invalid_modules_configuration_and_schedule_are_rejected(mutate, message):
    plan = default_plan()
    mutate(plan)
    with pytest.raises(ValueError, match=message):
        validate_plan(plan)


def test_compiler_has_real_indefinite_pause_and_boolean_publication_gate():
    plan = default_plan()
    flow = _compile(plan)
    pause, gate = flow["tasks"][2:]
    assert pause["type"] == "io.kestra.plugin.core.flow.Pause"
    assert pause["behavior"] == "CANCEL"
    assert "pauseDuration" not in pause
    assert "timeout" not in pause
    assert pause["onResume"][0] == {"id": "approved", "type": "BOOL", "required": True}
    assert pause["onResume"][1]["required"] is True
    assert pause["onResume"][1]["validator"] == "^[a-f0-9]{64}$"
    assert gate["condition"] == "{{ outputs.review_wait.onResume.approved == true }}"
    publish = gate["then"][0]
    assert "outputs.review_wait.onResume.review_digest" in publish["body"]
    assert "outputs.review_wait.onResume.approved" in publish["body"]
    assert "| toJson" in publish["body"]
    assert "else" not in gate
    assert json.loads(json.dumps(flow)) == flow
    assert flow["inputs"][0]["id"] == "poc_request_id"
    assert flow["labels"]["signal_desk_plan_digest"] == plan_digest(plan)
    assert flow["concurrency"] == {"limit": 1, "behavior": "FAIL"}


def test_free_text_templates_never_become_kestra_expressions():
    plan = apply_operations(default_plan(), [{"op": "update_node", "node_id": "summary", "label": "{{ secret('FAKE_SECRET') }}", "config": {"focus": "{{ secret('FAKE_SECRET') }}"}}, {"op": "set_question", "question": "{{ secret('FAKE_SECRET') }}"}])
    assert "FAKE_SECRET" not in json.dumps(_compile(plan))


def test_reordering_canvas_and_replacing_edge_labels_do_not_change_semantics():
    original = default_plan()
    changed = copy.deepcopy(original)
    changed["nodes"].reverse()
    changed["edges"].reverse()
    for index, edge in enumerate(changed["edges"]):
        edge["id"] = f"canvas_edge_{index}"
    assert plan_digest(changed) == plan_digest(original)


def test_partial_schedule_edit_does_not_reenable_a_changed_plan_implicitly():
    scheduled = apply_operations(default_plan(), [{"op": "set_schedule", "schedule": {"enabled": True, "mode": "daily"}}])
    changed = apply_operations(scheduled, [{"op": "set_question", "question": "虚构产品的便携卖点是否有依据？"}, {"op": "set_schedule", "schedule": {"time": "10:30"}}])
    assert changed["schedule"]["enabled"] is False


def test_malformed_edge_and_null_config_are_validation_errors():
    malformed = default_plan()
    malformed["edges"][0]["source"] = ["collect"]
    with pytest.raises(ValueError, match="不存在"):
        validate_plan(malformed)
    with pytest.raises(ValueError, match="对象"):
        apply_operations(default_plan(), [{"op": "update_node", "node_id": "collect", "config": None}])


@pytest.mark.parametrize("base", ["https://127.0.0.1:18977", "http://example.com:18977", "http://127.0.0.1:18977/other", "http://user:pass@127.0.0.1:18977", "http://127.0.0.1:18977?token=123", "http://127.0.0.1"])
def test_compiler_refuses_nonlocal_or_ambiguous_callback(base):
    with pytest.raises(ValueError):
        compile_flow(default_plan(), callback_base=base, callback_token="fictional-test-callback-token")


def test_callback_credentials_cannot_inject_headers_or_pebble():
    with pytest.raises(ValueError, match="凭证"):
        compile_flow(default_plan(), callback_base="http://127.0.0.1:18977", callback_token="{{ secret('UNRELATED') }}")
