import copy
import json
import threading

import pytest

from insightbot.signal_desk import workflow_poc as workflow
from insightbot.signal_desk.kestra_poc import EngineError, KestraClient
from insightbot.signal_desk.prototype_poc import Conflict, Prototype


class Engine:
    def __init__(self):
        self.flows, self.executions, self.starts, self.resumes = {}, {}, 0, 0
        self.available = True

    def health(self):
        return {"available": self.available, "label": "test engine"}

    def upsert_flow(self, flow):
        if not self.available:
            raise EngineError("engine unavailable")
        self.flows[flow["id"]] = copy.deepcopy(flow)
        return {"revision": 1}

    def create_execution(self, namespace, flow_id, request_id):
        self.starts += 1
        identifier = "execution_" + str(self.starts)
        self.executions[identifier] = {"id": identifier, "namespace": namespace,
                                       "flowId": flow_id, "inputs": {"poc_request_id": request_id},
                                       "state": {"current": "RUNNING"}}
        return copy.deepcopy(self.executions[identifier])

    def execution(self, identifier):
        if not self.available:
            raise EngineError("engine unavailable")
        return copy.deepcopy(self.executions[identifier])

    def find_execution(self, namespace, flow_id, request_id):
        if not self.available:
            raise EngineError("engine unavailable")
        matches = [item for item in self.executions.values()
                   if item["namespace"] == namespace and item["flowId"] == flow_id and
                   item.get("inputs", {}).get("poc_request_id") == request_id and not item.get("trigger")]
        if len(matches) > 1:
            raise EngineError("ambiguous start")
        return copy.deepcopy(matches[0]) if matches else None

    def resume(self, identifier, **decision):
        self.resumes += 1
        self.executions[identifier]["state"]["current"] = "RUNNING"
        return self.execution(identifier)


def started(tmp_path, *, planner=None):
    engine = Engine()
    app = Prototype(tmp_path, engine, planner=planner)
    result = app.execute({"expected_version": 1, "request_id": "manual_start_1"})
    return app, engine, result["runs"][0]["id"]


def callback(app, identifier, node_id, **extra):
    run = app.data["runs"][identifier]
    record = app.data["plans"][str(run["plan_version"])]
    node = next(item for item in record["plan"]["nodes"] if item["id"] == node_id)
    return app.callback(identifier, node_id, {"plan_version": run["plan_version"], "plan_digest": record["digest"],
                                              "node_id": node_id, "module": node["module"],
                                              "upstream": [edge["source"] for edge in record["plan"]["edges"] if edge["target"] == node_id],
                                              "request_id": app.engine.executions[identifier].get("inputs", {}).get("poc_request_id", ""), **extra})


def ready_review(app, engine, identifier):
    callback(app, identifier, "collect")
    callback(app, identifier, "summary")
    draft = callback(app, identifier, "review")
    engine.executions[identifier]["state"]["current"] = "PAUSED"
    app.sync_runs()
    return draft


def test_review_exact_draft_and_idempotent_publication(tmp_path):
    app, engine, identifier = started(tmp_path)
    draft = ready_review(app, engine, identifier)
    with pytest.raises(Conflict):
        callback(app, identifier, "publish", approved=True, review_digest=draft["review_digest"])
    with pytest.raises(Conflict):
        app.review({"execution_id": identifier, "approved": True, "review_digest": "0" * 64})
    app.review({"execution_id": identifier, "approved": True, "review_digest": draft["review_digest"]})
    first = callback(app, identifier, "publish", approved=True, review_digest=draft["review_digest"])
    second = callback(app, identifier, "publish", approved=True, review_digest=draft["review_digest"])
    assert first == second and first["simulated"]
    assert len([step for step in app.data["runs"][identifier]["steps"] if step["node_id"] == "publish"]) == 1
    with pytest.raises(Conflict):
        callback(app, identifier, "publish", approved=True, review_digest="0" * 64)
    app.review({"execution_id": identifier, "approved": True, "review_digest": draft["review_digest"]})
    assert engine.resumes == 1


def test_declining_does_not_allow_later_publication(tmp_path):
    app, engine, identifier = started(tmp_path)
    draft = ready_review(app, engine, identifier)
    app.review({"execution_id": identifier, "approved": False, "review_digest": draft["review_digest"]})
    with pytest.raises(Conflict):
        callback(app, identifier, "publish", approved=True, review_digest=draft["review_digest"])
    with pytest.raises(Conflict):
        app.review({"execution_id": identifier, "approved": True, "review_digest": draft["review_digest"]})


def test_restart_preserves_frozen_plan_review_and_completed_steps(tmp_path):
    app, engine, identifier = started(tmp_path)
    draft = ready_review(app, engine, identifier)
    plan = copy.deepcopy(app.data["plan"])
    plan["question"] = "新的问题（虚构）"
    app.save_plan({"expected_version": 1, "plan": plan})
    restarted = Prototype(tmp_path, engine)
    assert restarted.state()["runs"][0]["state"] == "PAUSED"
    assert restarted.data["runs"][identifier]["plan_version"] == 1
    assert restarted.data["plan"]["version"] == 2
    assert callback(restarted, identifier, "review") == draft
    restarted.review({"execution_id": identifier, "approved": True, "review_digest": draft["review_digest"]})
    assert callback(restarted, identifier, "publish", approved=True, review_digest=draft["review_digest"])["markdown"] == draft["markdown"]


def test_ai_operations_change_actual_graph_not_only_the_reply(tmp_path):
    def planner(message, plan):
        return {"reply": "增加竞品比较。", "operations": [{"op": "add_competitor", "name": "映山（虚构）"}]}
    app = Prototype(tmp_path, Engine(), planner=planner)
    result = app.chat({"expected_version": 1, "request_id": "conversation_1", "message": "增加竞品比较"})
    assert result["plan"]["version"] == 2
    assert "method.compare" in {node["module"] for node in result["plan"]["nodes"]}
    compiled = app._flow(result["plan"])
    assert "method.compare" in json.dumps(compiled)
    assert app.chat({"expected_version": 1, "request_id": "conversation_1", "message": "增加竞品比较"})["plan"]["version"] == 2


def test_unapproved_modules_from_model_rejected_atomically(tmp_path):
    app = Prototype(tmp_path, Engine(), planner=lambda *_: {"reply": "修改了。", "operations": [{"op": "run_script", "code": "bad"}]})
    old = copy.deepcopy(app.data["plan"])
    with pytest.raises(ValueError):
        app.chat({"expected_version": 1, "request_id": "bad_planning_1", "message": "执行任意代码"})
    assert app.data["plan"] == old
    assert not app.data["planning"]
    assert app.data["requests"]["bad_planning_1"]["status"] == "failed"


def test_double_execute_and_active_review_cannot_start_twice(tmp_path):
    app, engine, identifier = started(tmp_path)
    assert app.execute({"expected_version": 1, "request_id": "manual_start_1"})["runs"][0]["id"] == identifier
    with pytest.raises(Conflict):
        app.execute({"expected_version": 1, "request_id": "manual_start_2"})
    assert engine.starts == 1


def test_layout_only_keeps_version_and_manual_semantics_pause_schedule(tmp_path):
    app, engine, _ = started(tmp_path)
    app.schedule({"expected_version": 1, "schedule": {"enabled": True, "mode": "daily", "time": "09:00"}})
    version = app.data["plan"]["version"]
    moved = copy.deepcopy(app.data["plan"])
    moved["nodes"][0]["position"]["x"] = 456
    app.save_plan({"expected_version": version, "plan": moved})
    assert app.data["plan"]["version"] == version and app.data["plan"]["schedule"]["enabled"]
    edited = copy.deepcopy(app.data["plan"])
    edited["question"] = "另一个问题"
    app.save_plan({"expected_version": version, "plan": edited})
    assert not app.data["plan"]["schedule"]["enabled"]
    assert all(trigger["disabled"] for trigger in engine.flows[f"research_v{version}"]["triggers"])


def test_callback_rejects_wrong_version_module_and_missing_upstream(tmp_path):
    app, engine, identifier = started(tmp_path)
    with pytest.raises(Conflict):
        callback(app, identifier, "summary")
    record = app.data["plans"]["1"]
    with pytest.raises(Conflict):
        app.callback(identifier, "collect", {"plan_version": 1, "plan_digest": "0" * 64, "node_id": "collect", "module": "source.fixture", "upstream": []})
    with pytest.raises(Conflict):
        app.callback(identifier, "collect", {"plan_version": 1, "plan_digest": record["digest"], "node_id": "collect", "module": "publish.simulated", "upstream": []})


def test_schedule_import_failure_is_visible_and_not_enabled(tmp_path):
    engine = Engine()
    app = Prototype(tmp_path, engine)
    engine.available = False
    with pytest.raises(EngineError):
        app.schedule({"expected_version": 1, "schedule": {"enabled": True, "mode": "daily", "time": "09:00"}})
    assert not app.data["plan"]["schedule"]["enabled"]


def test_loopback_engine_and_sanitized_errors():
    import httpx
    with pytest.raises(ValueError):
        KestraClient("https://example.com")
    client = KestraClient(transport=httpx.MockTransport(lambda _: httpx.Response(500, text="secret configuration")))
    with pytest.raises(EngineError, match="HTTP 500") as error:
        client.execution("foo")
    assert "secret" not in str(error.value)
    client.close()


def test_lost_start_response_is_found_without_repeating_start(tmp_path):
    class LostResponse(Engine):
        def create_execution(self, *args):
            super().create_execution(*args)
            raise EngineError("response lost")
    engine = LostResponse()
    app = Prototype(tmp_path, engine)
    with pytest.raises(EngineError):
        app.execute({"expected_version": 1, "request_id": "lost_response_1"})
    with pytest.raises(Conflict, match="正在执行"):
        app.execute({"expected_version": 1, "request_id": "new_attempt_1"})
    assert app.data["requests"]["lost_response_1"]["status"] == "complete"
    assert app.data["runs"]["execution_1"]["state"] == "RUNNING"
    record = app.data["plans"]["1"]
    result = app.callback("execution_1", "collect", {"plan_version": 1, "plan_digest": record["digest"],
                                                      "node_id": "collect", "module": "source.fixture",
                                                      "upstream": [], "request_id": "lost_response_1"})
    assert result["fictional"]
    assert app.data["requests"]["lost_response_1"]["status"] == "complete"
    assert engine.starts == 1


class FailedStart(Engine):
    def create_execution(self, *args):
        if self.starts == 0:
            self.starts += 1
            raise EngineError("connection failed before engine accepted start")
        return super().create_execution(*args)


def failed_start(tmp_path):
    engine = FailedStart()
    app = Prototype(tmp_path, engine)
    with pytest.raises(EngineError):
        app.execute({"expected_version": 1, "request_id": "failed_start_1"})
    return app, engine


def test_absent_start_is_released_but_only_a_new_manual_request_can_execute(tmp_path):
    app, engine = failed_start(tmp_path)
    assert app.state()["runs"] == []
    assert app.data["requests"]["failed_start_1"]["status"] == "not_started"
    assert engine.starts == 1
    restored = Prototype(tmp_path, engine)
    with pytest.raises(Conflict):
        restored.execute({"expected_version": 1, "request_id": "failed_start_1"})
    result = restored.execute({"expected_version": 1, "request_id": "new_manual_start"})
    assert result["runs"][0]["state"] == "RUNNING"
    assert engine.starts == 2


def test_unavailable_engine_keeps_unknown_start_blocked_without_replay(tmp_path):
    app, engine = failed_start(tmp_path)
    engine.available = False
    assert app.state()["runs"] == []
    assert app.data["requests"]["failed_start_1"]["status"] == "unknown"
    with pytest.raises(Conflict, match="尚未确认"):
        app.execute({"expected_version": 1, "request_id": "new_manual_start"})
    assert engine.starts == 1
    engine.available = True
    app.sync_runs()
    assert app.data["requests"]["failed_start_1"]["status"] == "not_started"
    assert engine.starts == 1


def test_late_execution_of_retired_request_cannot_run_a_module(tmp_path, monkeypatch):
    app, engine = failed_start(tmp_path)
    app.sync_runs()
    record = app.data["plans"]["1"]
    engine.executions["late_execution"] = {"id": "late_execution", "namespace": app.data["namespace"],
                                           "flowId": record["flow_id"], "inputs": {"poc_request_id": "failed_start_1"},
                                           "state": {"current": "RUNNING"}}
    def forbidden(*args):
        pytest.fail("A retired request must not execute a module")
    monkeypatch.setattr(app, "_module", forbidden)
    with pytest.raises(Conflict, match="已确认"):
        app.callback("late_execution", "collect", {"plan_version": 1, "plan_digest": record["digest"],
                                                    "node_id": "collect", "module": "source.fixture",
                                                    "upstream": [], "request_id": "failed_start_1"})
    assert "late_execution" not in app.data["runs"]


def test_callback_can_confirm_unknown_start_without_search_index(tmp_path, monkeypatch):
    app, engine = failed_start(tmp_path)
    record = app.data["plans"]["1"]
    engine.executions["confirmed_execution"] = {"id": "confirmed_execution", "namespace": app.data["namespace"],
                                                "flowId": record["flow_id"], "inputs": {"poc_request_id": "failed_start_1"},
                                                "state": {"current": "RUNNING"}}
    def forbidden(*args):
        pytest.fail("A callback verifies its own execution directly")
    monkeypatch.setattr(engine, "find_execution", forbidden)
    result = app.callback("confirmed_execution", "collect", {"plan_version": 1, "plan_digest": record["digest"],
                                                             "node_id": "collect", "module": "source.fixture",
                                                             "upstream": [], "request_id": "failed_start_1"})
    assert result["fictional"]
    assert app.data["requests"]["failed_start_1"]["execution_id"] == "confirmed_execution"


def test_lookup_does_not_override_concurrent_callback_confirmation(tmp_path, monkeypatch):
    app, engine = failed_start(tmp_path)
    record = app.data["plans"]["1"]
    engine.executions["confirmed_execution"] = {"id": "confirmed_execution", "namespace": app.data["namespace"],
                                                "flowId": record["flow_id"], "inputs": {"poc_request_id": "failed_start_1"},
                                                "state": {"current": "RUNNING"}}
    def lookup(*args):
        app.callback("confirmed_execution", "collect", {"plan_version": 1, "plan_digest": record["digest"],
                                                       "node_id": "collect", "module": "source.fixture",
                                                       "upstream": [], "request_id": "failed_start_1"})
        return None  # A stale search response arrived after the callback.
    monkeypatch.setattr(engine, "find_execution", lookup)
    app.sync_runs()
    assert app.data["requests"]["failed_start_1"]["status"] == "complete"
    assert engine.starts == 1


@pytest.mark.parametrize("result", [{}, {"id": "unrelated_execution"}])
def test_malformed_lookup_result_keeps_start_unknown(tmp_path, monkeypatch, result):
    app, engine = failed_start(tmp_path)
    monkeypatch.setattr(engine, "find_execution", lambda *args: result)
    app.sync_runs()
    assert app.data["requests"]["failed_start_1"]["status"] == "unknown"
    assert not app.data["runs"]


@pytest.mark.parametrize("status", ["starting", "unknown"])
@pytest.mark.parametrize("created", [True, False])
def test_restart_reconciles_interrupted_start_against_engine(tmp_path, status, created):
    engine = Engine()
    app = Prototype(tmp_path, engine)
    flow_id = app._install(app.data["plan"])
    app.data["requests"]["interrupted_start"] = {"kind": "execute", "status": status, "plan_version": 1}
    if created:
        engine.create_execution(app.data["namespace"], flow_id, "interrupted_start")
    app._save()
    restored = Prototype(tmp_path, engine)
    result = restored.state()
    assert restored.data["requests"]["interrupted_start"]["status"] == ("complete" if created else "not_started")
    assert len(result["runs"]) == int(created)
    assert engine.starts == int(created)


def test_next_schedule_refreshes_finished_run_without_browser_poll(tmp_path):
    app, engine, identifier = started(tmp_path)
    ready_review(app, engine, identifier)
    app.schedule({"expected_version": 1, "schedule": {"enabled": True, "mode": "daily", "time": "09:00"}})
    engine.executions[identifier]["state"]["current"] = "SUCCESS"
    assert app.data["runs"][identifier]["state"] == "PAUSED"  # stale UI state
    record = app.data["plans"]["2"]
    engine.executions["scheduled_2"] = {"id": "scheduled_2", "namespace": app.data["namespace"],
                                         "flowId": record["flow_id"], "trigger": {"id": "schedule_v2"},
                                         "state": {"current": "RUNNING"}, "inputs": {"poc_request_id": ""}}
    app.callback("scheduled_2", "collect", {"plan_version": 2, "plan_digest": record["digest"],
                                             "node_id": "collect", "module": "source.fixture", "upstream": [], "request_id": ""})
    assert app.data["runs"][identifier]["state"] == "SUCCESS"
    assert app.data["runs"]["scheduled_2"]["trigger"] == "schedule"


def test_unknown_schedule_import_is_journalled_and_can_be_disabled(tmp_path):
    class LostImport(Engine):
        def __init__(self):
            super().__init__()
            self.fail_once = True
        def upsert_flow(self, flow):
            result = super().upsert_flow(flow)
            if self.fail_once:
                self.fail_once = False
                raise EngineError("import response lost")
            return result
    engine = LostImport()
    app = Prototype(tmp_path, engine)
    with pytest.raises(EngineError):
        app.schedule({"expected_version": 1, "schedule": {"enabled": True, "mode": "daily", "time": "09:00"}})
    restored = Prototype(tmp_path, engine)
    assert restored.state()["schedule_status"] == "unknown"
    assert not restored.data["plans"]["2"]["schedule_active"]
    restored.schedule({"expected_version": 2, "schedule": {"enabled": False}})
    assert restored.state()["schedule_status"] == "paused"
    assert engine.flows["research_v2"]["triggers"][0]["disabled"] is True


def test_saving_unchanged_schedule_keeps_live_trigger_enabled(tmp_path):
    app = Prototype(tmp_path, Engine())
    body = {"enabled": True, "mode": "daily", "time": "09:00"}
    app.schedule({"expected_version": 1, "schedule": body})
    app.schedule({"expected_version": 2, "schedule": body})
    assert app.data["plan"]["version"] == 2
    assert app.data["plans"]["2"]["schedule_active"]
    assert not app.engine.flows["research_v2"]["triggers"][0].get("disabled")
