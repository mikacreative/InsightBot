"""Loopback-only client for the disposable Kestra proof of concept."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx


class EngineError(RuntimeError):
    def __init__(self, message, *, unknown=True):
        super().__init__(message)
        self.unknown = unknown


class KestraClient:
    def __init__(self, base_url="http://127.0.0.1:18978", auth_file=None, *, transport=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.path not in ("", "/")):
            raise ValueError("原型执行引擎必须是独立的 127.0.0.1 HTTP 服务")
        auth = None
        if auth_file:
            credentials = json.loads(Path(auth_file).read_text(encoding="utf-8"))
            auth = (credentials["username"], credentials["password"])
        self.client = httpx.Client(base_url=base_url.rstrip("/"), auth=auth, timeout=15,
                                   follow_redirects=False, trust_env=False, transport=transport)

    def close(self):
        self.client.close()

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise EngineError("执行引擎暂时无法连接；已发出的请求不自动重试") from None
        if response.status_code >= 300:
            # Never relay upstream response bodies containing internal configuration.
            raise EngineError(f"执行引擎返回 HTTP {response.status_code}", unknown=not 400 <= response.status_code < 500)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise EngineError("执行引擎返回了无法识别的结果") from None

    def health(self):
        try:
            config = self._request("GET", "/api/v1/configs")
            return {"available": True, "label": "Kestra", "version": config.get("version")}
        except EngineError as error:
            return {"available": False, "label": "Kestra", "error": str(error)}

    def upsert_flow(self, flow):
        namespace, flow_id = quote(flow["namespace"], safe=""), quote(flow["id"], safe="")
        source = json.dumps(flow, ensure_ascii=False)
        # JSON is a YAML subset; Kestra retains the source as a versioned flow.
        try:
            existing = self.client.get(f"/api/v1/main/flows/{namespace}/{flow_id}")
        except httpx.HTTPError:
            raise EngineError("执行引擎暂时无法连接") from None
        if existing.status_code == 404:
            return self._request("POST", "/api/v1/main/flows", content=source,
                                 headers={"Content-Type": "application/x-yaml"})
        if existing.status_code != 200:
            raise EngineError(f"执行引擎返回 HTTP {existing.status_code}", unknown=False)
        return self._request("PUT", f"/api/v1/main/flows/{namespace}/{flow_id}", content=source,
                             headers={"Content-Type": "application/x-yaml"})

    def create_execution(self, namespace, flow_id, request_id):
        return self._request("POST", f"/api/v1/main/executions/{quote(namespace, safe='')}/{quote(flow_id, safe='')}",
                             files={"poc_request_id": (None, request_id)})

    def execution(self, execution_id):
        return self._request("GET", "/api/v1/main/executions/" + quote(execution_id, safe=""))

    def find_execution(self, namespace, flow_id, request_id):
        """Reconcile a lost start response; incomplete searches never prove absence."""
        seen, matches, total = set(), {}, None
        for page in range(1, 11):
            result = self._request("GET", "/api/v1/main/executions/search",
                                   params={"namespace": namespace, "flowId": flow_id, "page": page, "size": 100})
            if (not isinstance(result, dict) or not isinstance(result.get("results"), list) or
                    type(result.get("total")) is not int or result["total"] < 0):
                raise EngineError("执行记录无法完整核对；启动状态仍待确认")
            if total is None:
                total = result["total"]
            entries = result["results"]
            if result["total"] != total or len(entries) > 100 or len(seen) + len(entries) > total:
                raise EngineError("执行记录核对期间发生变化；启动状态仍待确认")
            for execution in entries:
                if (not isinstance(execution, dict) or not isinstance(execution.get("id"), str) or
                        not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", execution["id"]) or
                        execution["id"] in seen or not isinstance(execution.get("namespace"), str) or
                        not isinstance(execution.get("flowId"), str)):
                    raise EngineError("执行记录无法完整核对；启动状态仍待确认")
                seen.add(execution["id"])
                if execution["namespace"] != namespace or execution["flowId"] != flow_id or execution.get("trigger"):
                    continue
                if not isinstance(execution.get("inputs"), dict):
                    raise EngineError("执行请求标识无法核对；启动状态仍待确认")
                if execution["inputs"].get("poc_request_id") == request_id:
                    if (not isinstance(execution.get("state"), dict) or
                            not isinstance(execution["state"].get("current"), str) or not execution["state"]["current"]):
                        raise EngineError("执行状态无法核对；启动状态仍待确认")
                    matches[execution["id"]] = execution
            if len(seen) == total:
                if len(matches) > 1:
                    raise EngineError("同一启动请求对应多个执行；需要核对")
                return next(iter(matches.values()), None)
            if len(entries) < 100:
                raise EngineError("执行记录未完整返回；启动状态仍待确认")
        raise EngineError("执行记录超出本次核对范围；启动状态仍待确认")

    def resume(self, execution_id, *, approved, review_digest):
        return self._request("POST", "/api/v1/main/executions/" + quote(execution_id, safe="") + "/resume",
                             files={"approved": (None, "true" if approved else "false"),
                                    "review_digest": (None, review_digest)})
