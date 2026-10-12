import httpx
import pytest

from insightbot.signal_desk.kestra_poc import EngineError, KestraClient

NAMESPACE, FLOW, REQUEST = "signaldesk.poc.fictional", "research_v1", "fictional_start"


def execution(identifier, marker=REQUEST, **extra):
    return {"id": identifier, "namespace": NAMESPACE, "flowId": FLOW,
            "inputs": {"poc_request_id": marker}, "state": {"current": "RUNNING"}, **extra}


def test_lookup_finds_exact_manual_request_on_later_page():
    entries = [execution(f"other_{i}", f"other_request_{i}") for i in range(100)]
    entries[0] = execution("wrong_namespace", namespace="signaldesk.poc.other")
    entries[1] = execution("wrong_flow", flowId="research_v2")
    entries[2] = execution("scheduled", trigger={"id": "schedule_v1"})
    expected = execution("matching_execution")
    calls = []
    def search(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/main/executions/search"
        assert request.url.params["namespace"] == NAMESPACE
        assert request.url.params["flowId"] == FLOW
        assert request.url.params["size"] == "100"
        page = int(request.url.params["page"])
        calls.append(page)
        return httpx.Response(200, json={"results": entries if page == 1 else [expected], "total": 101})
    client = KestraClient(transport=httpx.MockTransport(search))
    try:
        assert client.find_execution(NAMESPACE, FLOW, REQUEST) == expected
        assert calls == [1, 2]
    finally:
        client.close()


@pytest.mark.parametrize("entries", [[], [execution("other", "other_request")],
                                      [execution("scheduled", trigger={"id": "schedule_v1"})]])
def test_complete_lookup_can_confirm_absence(entries):
    client = KestraClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json={"results": entries, "total": len(entries)})))
    try:
        assert client.find_execution(NAMESPACE, FLOW, REQUEST) is None
    finally:
        client.close()


@pytest.mark.parametrize("result", [
    {}, [], {"results": [], "total": "0"}, {"results": [], "total": 1},
    {"results": [execution("duplicate"), execution("duplicate")], "total": 2},
    {"results": [execution("one"), execution("two")], "total": 2},
    {"results": [execution("missing_marker", inputs=None)], "total": 1},
    {"results": [execution("missing_state", state=None)], "total": 1},
], ids=["missing-fields", "wrong-shape", "invalid-total", "incomplete-page", "repeated-id",
        "multiple-matches", "missing-inputs", "missing-state"])
def test_ambiguous_or_incomplete_lookup_does_not_release_unknown_start(result):
    client = KestraClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=result)))
    try:
        with pytest.raises(EngineError) as error:
            client.find_execution(NAMESPACE, FLOW, REQUEST)
        assert error.value.unknown
    finally:
        client.close()


def test_lookup_bound_does_not_claim_absence_after_truncated_history():
    calls = []
    def search(request):
        page = int(request.url.params["page"])
        calls.append(page)
        entries = [execution(f"other_{page}_{i}", "other_request") for i in range(100)]
        return httpx.Response(200, json={"results": entries, "total": 1001})
    client = KestraClient(transport=httpx.MockTransport(search))
    try:
        with pytest.raises(EngineError, match="核对范围"):
            client.find_execution(NAMESPACE, FLOW, REQUEST)
        assert len(calls) == 10
    finally:
        client.close()


def test_lookup_http_failure_is_unknown_and_does_not_leak_response_body():
    client = KestraClient(transport=httpx.MockTransport(lambda _: httpx.Response(503, text="private engine configuration")))
    try:
        with pytest.raises(EngineError, match="HTTP 503") as error:
            client.find_execution(NAMESPACE, FLOW, REQUEST)
        assert error.value.unknown and "private" not in str(error.value)
    finally:
        client.close()
