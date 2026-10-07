"""Canonical plans and a constrained Kestra compiler for the local workflow POC.

The canvas and the conversational planner mutate this same validated plan.  The
compiler sends only identifiers and hashes to Kestra; module configuration stays
in the application's frozen plan snapshot.  No user text becomes executable
Pebble, shell code, or an outbound URL.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


_NODE_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_EDGE_ID = re.compile(r"[a-z][a-z0-9_]{0,149}\Z")
_TIME = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_TIMEZONE = "Asia/Shanghai"
_CHANNELS = ("workbench", "wecom_simulated", "feishu_simulated")
_REGISTRY = (
    {
        "id": "source.fixture", "label": "品牌线索", "category": "source",
        "description": "收集澄野（虚构）的本机演示素材。",
        "default_config": {"keywords": ["通勤", "轻量"]},
        "config_fields": [{"key": "keywords", "label": "研究关键词", "type": "strings"}],
    },
    {
        "id": "source.competitor_fixture", "label": "竞品线索", "category": "source",
        "description": "收集指定虚构竞品的本机演示素材。",
        "default_config": {"keywords": ["通勤", "轻量"], "competitors": ["泊岸（虚构）"]},
        "config_fields": [
            {"key": "competitors", "label": "比较哪些竞品", "type": "strings"},
            {"key": "keywords", "label": "研究关键词", "type": "strings"},
        ],
    },
    {
        "id": "method.compare", "label": "竞品对照", "category": "method",
        "description": "根据上游品牌与竞品线索，逐项比较差异。",
        "default_config": {"focus": "比较卖点、使用场景和待验证差异"},
        "config_fields": [{"key": "focus", "label": "比较重点", "type": "text"}],
    },
    {
        "id": "method.summary", "label": "形成研究判断", "category": "method",
        "description": "从上游线索形成有据、具体、可检阅的研究结果。",
        "default_config": {"focus": "整理有据的判断与待验证问题"},
        "config_fields": [{"key": "focus", "label": "研究重点", "type": "text"}],
    },
    {
        "id": "review.human", "label": "人工检阅", "category": "review",
        "description": "保留当前结果，等待你选择通过或退回。",
        "default_config": {}, "config_fields": [],
    },
    {
        "id": "publish.simulated", "label": "模拟发布", "category": "publish",
        "description": "记录一次模拟发布，不发送到真实渠道。",
        "default_config": {"channel": "workbench"},
        "config_fields": [{"key": "channel", "label": "交付位置", "type": "select", "options": list(_CHANNELS)}],
    },
)
_BY_MODULE = {item["id"]: item for item in _REGISTRY}


def modules() -> list[dict[str, Any]]:
    """Return the allowed module catalog, without exposing mutable defaults."""
    return copy.deepcopy(list(_REGISTRY))


def _object(value: Any, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}需要是对象")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{label}包含不支持的设置：{', '.join(sorted(str(key) for key in unknown))}")
    return value


def _text(value: Any, label: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}需要是文字")
    result = value.strip()
    if (not result and not empty) or len(result) > maximum:
        raise ValueError(f"{label}需要包含 1 至 {maximum} 个字" if not empty else f"{label}不能超过 {maximum} 个字")
    if any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise ValueError(f"{label}包含不支持的字符")
    return result


def _identifier(value: Any, label: str, *, edge: bool = False) -> str:
    if not isinstance(value, str) or not (_EDGE_ID if edge else _NODE_ID).fullmatch(value):
        raise ValueError(f"{label}只能使用小写英文字母、数字和下划线，并以字母开头")
    if value.startswith("poc_") and not edge:
        raise ValueError(f"{label}使用了原型保留名称")
    return value


def _strings(value: Any, label: str, *, required: bool = False, maximum: int = 20) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label}需要是最多 {maximum} 项的文字列表")
    result = list(dict.fromkeys(_text(item, label, 80) for item in value))
    if required and not result:
        raise ValueError(f"请至少填写一个{label}")
    return result


def _position(value: Any) -> dict[str, float]:
    obj = _object(value, "节点位置", {"x", "y"})
    result = {}
    for field in ("x", "y"):
        number = obj.get(field)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or abs(number) > 10000:
            raise ValueError("节点位置需要是有限数字，且不能超出画布范围")
        result[field] = float(number)
    return result


def _config(module: str, value: Any) -> dict[str, Any]:
    fields = {field["key"] for field in _BY_MODULE[module]["config_fields"]}
    obj = _object(value, "模块设置", fields)
    defaults = _BY_MODULE[module]["default_config"]
    if module.startswith("source."):
        result = {"keywords": _strings(obj.get("keywords", defaults["keywords"]), "关键词")}
        if module == "source.competitor_fixture":
            result["competitors"] = _strings(obj.get("competitors", defaults["competitors"]), "竞品名称", required=True, maximum=10)
        return result
    if module.startswith("method."):
        return {"focus": _text(obj.get("focus", defaults["focus"]), "研究重点", 1000)}
    if module == "publish.simulated":
        channel = obj.get("channel", defaults["channel"])
        if channel not in _CHANNELS:
            raise ValueError("原型只支持工作台、企业微信或飞书的模拟发布")
        return {"channel": channel}
    return {}


def _schedule(value: Any) -> dict[str, Any]:
    obj = _object(value, "执行时间", {"enabled", "mode", "at", "time", "weekdays", "timezone"})
    enabled = obj.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("自动执行开关需要是开启或关闭")
    mode = obj.get("mode", "once")
    if mode not in ("once", "daily", "weekly"):
        raise ValueError("请选择执行一次、每天或每周")
    if obj.get("timezone", _TIMEZONE) != _TIMEZONE:
        raise ValueError("本机原型按上海时间执行")
    clock = obj.get("time", "09:00")
    if not isinstance(clock, str) or not _TIME.fullmatch(clock):
        raise ValueError("执行时间请使用 HH:MM 格式")
    weekdays = obj.get("weekdays", [1])
    if not isinstance(weekdays, list) or len(weekdays) > 7 or any(type(day) is not int or not 1 <= day <= 7 for day in weekdays):
        raise ValueError("每周执行日需要是 1（周一）至 7（周日）的列表")
    weekdays = sorted(set(weekdays))
    if mode == "weekly" and not weekdays:
        raise ValueError("请至少选择一个每周执行日")
    at = obj.get("at")
    if at is not None:
        if not isinstance(at, str) or len(at) > 80:
            raise ValueError("单次执行时间需要是有效日期与时间")
        try:
            date = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("单次执行时间需要是有效日期与时间") from exc
        if date.tzinfo is None:
            date = date.replace(tzinfo=ZoneInfo(_TIMEZONE))
        at = date.astimezone(ZoneInfo(_TIMEZONE)).isoformat()
    if enabled and mode == "once" and not at:
        raise ValueError("请填写单次执行日期与时间")
    return {"enabled": enabled, "mode": mode, "at": at, "time": clock, "weekdays": weekdays, "timezone": _TIMEZONE}


def _graph(plan: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, list[str]], list[str]]:
    nodes = {node["id"]: node for node in plan["nodes"]}
    incoming: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in plan["edges"]:
        incoming[edge["target"]].append(edge["source"])
        outgoing[edge["source"]].append(edge["target"])
    counts = {node_id: len(values) for node_id, values in incoming.items()}
    ready = sorted(node_id for node_id, count in counts.items() if not count)
    order = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for target in sorted(outgoing[current]):
            counts[target] -= 1
            if counts[target] == 0:
                ready.append(target)
                ready.sort()
    if len(order) != len(nodes):
        raise ValueError("研究流程不能连成循环，请调整节点连线")
    return nodes, incoming, outgoing, order


def validate_plan(plan: Any) -> dict[str, Any]:
    """Normalize and validate the complete plan; never mutate the caller's copy."""
    obj = _object(plan, "研究计划", {"id", "version", "brand", "question", "nodes", "edges", "schedule"})
    if obj.get("id") != "poc_research":
        raise ValueError("本机原型只支持演示研究任务")
    version = obj.get("version")
    if type(version) is not int or not 1 <= version <= 1000000:
        raise ValueError("研究计划版本需要是正整数")
    brand = _object(obj.get("brand"), "品牌", {"id", "name"})
    if brand.get("id") != "fictional_brand":
        raise ValueError("本机原型仅使用虚构品牌")
    brand_name = _text(brand.get("name"), "品牌名称", 100)
    if "虚构" not in brand_name:
        raise ValueError("原型品牌名称需要明确标注“虚构”")
    raw_nodes = obj.get("nodes")
    if not isinstance(raw_nodes, list) or not 4 <= len(raw_nodes) <= 24:
        raise ValueError("研究计划需要包含 4 至 24 个节点")
    nodes = []
    used = set()
    for raw in raw_nodes:
        node = _object(raw, "研究节点", {"id", "module", "label", "position", "config"})
        node_id = _identifier(node.get("id"), "节点名称")
        if node_id in used:
            raise ValueError("节点名称不能重复")
        used.add(node_id)
        module = node.get("module")
        if not isinstance(module, str) or module not in _BY_MODULE:
            raise ValueError("该研究模块尚未开放，请使用可选模块")
        nodes.append({"id": node_id, "module": module, "label": _text(node.get("label", _BY_MODULE[module]["label"]), "节点标题", 100), "position": _position(node.get("position", {"x": 0, "y": 0})), "config": _config(module, node.get("config", {}))})
    raw_edges = obj.get("edges")
    if not isinstance(raw_edges, list) or not 3 <= len(raw_edges) <= 100:
        raise ValueError("请连接完整的研究流程")
    edges = []
    edge_ids, pairs = set(), set()
    for raw in raw_edges:
        edge = _object(raw, "研究连线", {"id", "source", "target"})
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in used or target not in used:
            raise ValueError("连线引用了不存在的研究节点")
        edge_id = _identifier(edge.get("id", f"edge_{source}_{target}"), "连线名称", edge=True)
        if edge_id in edge_ids or (source, target) in pairs:
            raise ValueError("研究节点间不能重复连线")
        edge_ids.add(edge_id)
        pairs.add((source, target))
        edges.append({"id": edge_id, "source": source, "target": target})
    result = {"id": "poc_research", "version": version, "brand": {"id": "fictional_brand", "name": brand_name}, "question": _text(obj.get("question"), "研究问题", 2000), "nodes": nodes, "edges": edges, "schedule": _schedule(obj.get("schedule", {}))}
    by_id, incoming, outgoing, order = _graph(result)
    reviews = [node["id"] for node in nodes if node["module"] == "review.human"]
    publications = [node["id"] for node in nodes if node["module"] == "publish.simulated"]
    if len(reviews) != 1 or len(publications) != 1:
        raise ValueError("研究流程需要且只能有一个人工检阅节点和一个模拟发布节点")
    review, publication = reviews[0], publications[0]
    if f"{review}_wait" in used:
        raise ValueError("节点名称与人工检阅的等待步骤重名")
    if incoming[publication] != [review] or outgoing[review] != [publication] or outgoing[publication]:
        raise ValueError("模拟发布必须直接连接人工检阅，不能绕过审批")
    ancestors: dict[str, set[str]] = {}
    for node_id in order:
        node = by_id[node_id]
        module = node["module"]
        category = _BY_MODULE[module]["category"]
        upstream = incoming[node_id]
        ancestors[node_id] = set(upstream)
        for parent in upstream:
            ancestors[node_id].update(ancestors[parent])
        if category == "source":
            if upstream or not outgoing[node_id]:
                raise ValueError("数据来源需要位于流程起点，并连接后续研究方法")
        elif category == "method":
            if not upstream or any(_BY_MODULE[by_id[parent]["module"]]["category"] not in ("source", "method") for parent in upstream):
                raise ValueError("研究方法只能接收数据来源或前一道研究方法")
            if module == "method.compare":
                source_modules = {by_id[parent]["module"] for parent in ancestors[node_id]}
                if len(upstream) < 2 or not {"source.fixture", "source.competitor_fixture"}.issubset(source_modules):
                    raise ValueError("竞品对照需要同时接收品牌与竞品线索")
        elif category == "review":
            if not upstream or any(by_id[parent]["module"] != "method.summary" for parent in upstream):
                raise ValueError("人工检阅需要连接已形成稿件的研究汇总")
    if set(ancestors[publication]) != used - {publication}:
        raise ValueError("有研究节点未连接到最终交付，请补齐流程连线")
    if not any(node["module"] == "source.fixture" for node in nodes):
        raise ValueError("研究流程需要包含品牌线索来源")
    return result


def default_plan() -> dict[str, Any]:
    stages = (("collect", "source.fixture"), ("summary", "method.summary"), ("review", "review.human"), ("publish", "publish.simulated"))
    return validate_plan({
        "id": "poc_research", "version": 1,
        "brand": {"id": "fictional_brand", "name": "澄野（虚构）"},
        "question": "澄野（虚构）的通勤杯卖点，哪些更值得继续验证？",
        "nodes": [{"id": node_id, "module": module, "label": _BY_MODULE[module]["label"], "position": {"x": index * 300, "y": 140}, "config": copy.deepcopy(_BY_MODULE[module]["default_config"])} for index, (node_id, module) in enumerate(stages)],
        "edges": [{"id": f"edge_{stages[index][0]}_{stages[index + 1][0]}", "source": stages[index][0], "target": stages[index + 1][0]} for index in range(len(stages) - 1)],
        "schedule": {"enabled": False, "mode": "once", "at": None, "time": "09:00", "weekdays": [1], "timezone": _TIMEZONE},
    })


def _semantic(plan: dict[str, Any], *, version: bool = True) -> dict[str, Any]:
    result = copy.deepcopy(plan)
    if not version:
        result.pop("version")
    for node in result["nodes"]:
        node.pop("position")
    # Canvas array order is a presentation detail, not a dependency declaration.
    result["nodes"].sort(key=lambda node: node["id"])
    result["edges"].sort(key=lambda edge: (edge["source"], edge["target"]))
    for edge in result["edges"]:
        edge.pop("id")
    return result


def plan_digest(plan: Any) -> str:
    """Hash the normalized frozen semantics, including version but not layout."""
    data = _semantic(validate_plan(plan))
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _node(plan: dict[str, Any], node_id: Any) -> dict[str, Any]:
    for node in plan["nodes"]:
        if node["id"] == node_id:
            return node
    raise ValueError("找不到要修改的研究节点")


def _new_id(plan: dict[str, Any], base: str) -> str:
    used = {node["id"] for node in plan["nodes"]}
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"


def _connect(plan: dict[str, Any], source: str, target: str) -> None:
    if not any(edge["source"] == source and edge["target"] == target for edge in plan["edges"]):
        plan["edges"].append({"id": f"edge_{source}_{target}", "source": source, "target": target})


def _add_competitor(plan: dict[str, Any], op: dict[str, Any]) -> None:
    raw = op.get("competitors")
    if raw is None:
        raw = [op.get("name", op.get("competitor", "泊岸（虚构）"))]
    names = _strings(raw, "竞品名称", required=True, maximum=10)
    source = next((node for node in plan["nodes"] if node["module"] == "source.competitor_fixture"), None)
    primary = next(node for node in plan["nodes"] if node["module"] == "source.fixture")
    if source is None:
        source = {"id": _new_id(plan, "competitors"), "module": "source.competitor_fixture", "label": "竞品线索", "position": {"x": primary["position"]["x"], "y": primary["position"]["y"] + 200}, "config": {"keywords": copy.deepcopy(primary["config"]["keywords"]), "competitors": names}}
        plan["nodes"].append(source)
    else:
        source["config"]["competitors"] = _strings(source["config"]["competitors"] + names, "竞品名称", required=True, maximum=10)
    comparison = next((node for node in plan["nodes"] if node["module"] == "method.compare"), None)
    if comparison is None:
        target = next((node for node in plan["nodes"] if node["module"] == "method.summary"), None)
        if target is None:
            target = next(node for node in plan["nodes"] if node["module"] == "review.human")
        upstream = [edge["source"] for edge in plan["edges"] if edge["target"] == target["id"]]
        comparison = {"id": _new_id(plan, "compare"), "module": "method.compare", "label": "竞品对照", "position": {"x": target["position"]["x"], "y": target["position"]["y"]}, "config": {"focus": op.get("focus", _BY_MODULE["method.compare"]["default_config"]["focus"])}}
        plan["nodes"].append(comparison)
        plan["edges"] = [edge for edge in plan["edges"] if edge["target"] != target["id"]]
        for upstream_id in upstream:
            _connect(plan, upstream_id, comparison["id"])
        _connect(plan, comparison["id"], target["id"])
        for node in plan["nodes"]:
            if node["id"] not in (primary["id"], source["id"], comparison["id"]) and node["position"]["x"] >= comparison["position"]["x"]:
                node["position"]["x"] += 300
    elif "focus" in op:
        comparison["config"]["focus"] = op["focus"]
    _connect(plan, primary["id"], comparison["id"])
    _connect(plan, source["id"], comparison["id"])


def apply_operations(plan: Any, operations: Any) -> dict[str, Any]:
    """Apply a transaction of structured edits, or reject it without mutations.

    Every semantic transaction advances the version once and pauses inherited
    schedules.  A ``set_schedule`` in the same transaction can explicitly enable
    the new version.  Moving nodes changes layout only, so active runs keep their
    frozen version and approval binding.
    """
    original = validate_plan(plan)
    draft = copy.deepcopy(original)
    if not isinstance(operations, list) or len(operations) > 32:
        raise ValueError("计划修改需要是最多 32 项的操作列表")
    explicitly_enabled = False
    for raw in operations:
        if not isinstance(raw, dict):
            raise ValueError("计划修改需要是结构化操作")
        action = raw.get("op", raw.get("type"))
        if action == "add_competitor":
            op = _object(raw, "增加竞品", {"op", "type", "competitors", "name", "competitor", "focus"})
            _add_competitor(draft, op)
        elif action == "set_question":
            op = _object(raw, "修改研究问题", {"op", "type", "question"})
            draft["question"] = op.get("question")
        elif action == "update_node":
            op = _object(raw, "修改节点", {"op", "type", "node_id", "id", "label", "config", "patch"})
            node = _node(draft, op.get("node_id", op.get("id")))
            patch = _object(op.get("patch", {}), "节点修改", {"label", "config"})
            for field in ("label", "config"):
                value = op[field] if field in op else patch.get(field)
                if field in op or field in patch:
                    if field == "config":
                        config = _object(value, "模块设置", {item["key"] for item in _BY_MODULE[node["module"]]["config_fields"]})
                        node["config"].update(copy.deepcopy(config))
                    else:
                        node[field] = value
        elif action == "move_node":
            op = _object(raw, "移动节点", {"op", "type", "node_id", "id", "position", "x", "y"})
            node = _node(draft, op.get("node_id", op.get("id")))
            node["position"] = _position(op.get("position", {"x": op.get("x"), "y": op.get("y")}))
        elif action == "replace_edges":
            op = _object(raw, "修改连线", {"op", "type", "edges"})
            draft["edges"] = copy.deepcopy(op.get("edges"))
        elif action == "set_schedule":
            op = _object(raw, "修改执行时间", {"op", "type", "schedule"})
            update = _object(op.get("schedule"), "执行时间", {"enabled", "mode", "at", "time", "weekdays", "timezone"})
            draft["schedule"].update(copy.deepcopy(update))
            explicitly_enabled = update.get("enabled") is True
        else:
            raise ValueError("这项计划修改尚未支持，请使用可选操作")
    draft = validate_plan(draft)
    if _semantic(draft, version=False) != _semantic(original, version=False):
        if not explicitly_enabled:
            draft["schedule"]["enabled"] = False
        draft["version"] = original["version"] + 1
        draft = validate_plan(draft)
    return draft


def _body(static: dict[str, Any], dynamic: dict[str, str]) -> str:
    values = [f"{json.dumps(key)}: {json.dumps(value, ensure_ascii=True)}" for key, value in static.items()]
    values.extend(f"{json.dumps(key)}: {expression}" for key, expression in dynamic.items())
    return "{{ {" + ", ".join(values) + "} | toJson }}"


def compile_flow(plan: Any, *, callback_base: str, callback_token: str, namespace: str = "signaldesk.poc") -> dict[str, Any]:
    """Compile this plan to a Kestra 1.3.42/2.0 core-only Flow dictionary.

    Serialize the result with ``json.dumps`` and send as ``application/x-yaml``:
    JSON is a YAML subset, so a YAML dependency is unnecessary.  Callbacks resolve
    frozen configuration by version/digest.  Their body is rendered with toJson,
    including resume inputs, to preserve JSON escaping.
    """
    canonical = validate_plan(plan)
    parsed = urlsplit(callback_base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("原型研究步骤只能回调本机服务")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("本机回调端口无效") from exc
    if port is None or not 1 <= port <= 65535:
        raise ValueError("请指定有效的本机回调端口")
    if not isinstance(callback_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,512}", callback_token):
        raise ValueError("本机回调凭证格式无效")
    if not isinstance(namespace, str) or len(namespace) > 100 or not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,5}", namespace):
        raise ValueError("工作流分组名称无效")
    digest = plan_digest(canonical)
    by_id, incoming, _, order = _graph(canonical)
    review = next(node for node in canonical["nodes"] if node["module"] == "review.human")
    publication = next(node for node in canonical["nodes"] if node["module"] == "publish.simulated")
    wait_id = f"{review['id']}_wait"

    def callback(node: dict[str, Any], *, publication: bool = False) -> dict[str, Any]:
        static = {"plan_version": canonical["version"], "plan_digest": digest, "node_id": node["id"], "module": node["module"], "upstream": sorted(incoming[node["id"]])}
        dynamic = {"request_id": "inputs.poc_request_id ?? ''"}
        if publication:
            dynamic.update({"approved": f"outputs.{wait_id}.onResume.approved", "review_digest": f"outputs.{wait_id}.onResume.review_digest"})
        return {"id": node["id"], "type": "io.kestra.plugin.core.http.Request", "uri": f"{callback_base.rstrip('/')}/internal/executions/{{{{ execution.id }}}}/nodes/{node['id']}", "method": "POST", "contentType": "application/json", "headers": {"Authorization": f"Bearer {callback_token}"}, "body": _body(static, dynamic), "timeout": "PT30S", "options": {"connectTimeout": "PT5S", "readTimeout": "PT20S"}}

    dag_tasks = []
    for node_id in order:
        node = by_id[node_id]
        if _BY_MODULE[node["module"]]["category"] not in ("source", "method"):
            continue
        item = {"task": callback(node)}
        if incoming[node_id]:
            item["dependsOn"] = sorted(incoming[node_id])
        dag_tasks.append(item)
    flow: dict[str, Any] = {
        "id": f"research_v{canonical['version']}", "namespace": namespace,
        "description": "Signal Desk 本机研究原型，仅使用虚构素材与模拟发布。",
        "labels": {"signal_desk_plan_version": str(canonical["version"]), "signal_desk_plan_digest": digest},
        "concurrency": {"limit": 1, "behavior": "FAIL"},
        # Kestra requires a defaulted input to be marked required.  The default
        # still lets schedules omit this manual request marker.
        "inputs": [{"id": "poc_request_id", "type": "STRING", "required": True, "defaults": ""}],
        "tasks": [
            {"id": "poc_research_steps", "type": "io.kestra.plugin.core.flow.Dag", "tasks": dag_tasks},
            callback(review),
            {"id": wait_id, "type": "io.kestra.plugin.core.flow.Pause", "behavior": "CANCEL", "onResume": [{"id": "approved", "type": "BOOL", "required": True}, {"id": "review_digest", "type": "STRING", "required": True, "validator": "^[a-f0-9]{64}$"}]},
            {"id": "poc_publication_gate", "type": "io.kestra.plugin.core.flow.If", "condition": f"{{{{ outputs.{wait_id}.onResume.approved == true }}}}", "then": [callback(publication, publication=True)]},
        ],
    }
    schedule = canonical["schedule"]
    if schedule["enabled"]:
        trigger = {"id": f"schedule_v{canonical['version']}", "timezone": _TIMEZONE, "allowConcurrent": False, "recoverMissedSchedules": "NONE", "stopAfter": ["FAILED", "KILLED", "CANCELLED"]}
        if schedule["mode"] == "once":
            trigger.update({"type": "io.kestra.plugin.core.trigger.ScheduleOnDates", "dates": [schedule["at"]]})
        else:
            hour, minute = schedule["time"].split(":")
            days = "*" if schedule["mode"] == "daily" else ",".join(str(day % 7) for day in schedule["weekdays"])
            trigger.update({"type": "io.kestra.plugin.core.trigger.Schedule", "cron": f"{int(minute)} {int(hour)} * * {days}"})
        flow["triggers"] = [trigger]
    return flow
