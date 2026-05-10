# Signal Desk Agent Access Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small, testable routing contract that lets future UI, REST API, RSS/API connectors, and Skill entrypoints resolve user requests into Signal Desk product intent.

**Architecture:** Keep routing above execution. The new layer maps text and structured parameters into `pattern_id`, `time_window`, `output_intent`, and `result_mode`, without changing `task_runner`, compiled tasks, or persisted room intent. This follows the AIHOT lesson: default to selected results; only route to raw feed or brief output when the user explicitly asks.

**Tech Stack:** Python dataclasses, existing `insightbot.signal_desk` package, pytest.

---

### Task 1: Agent Access Routing Contract

**Files:**
- Create: `insightbot/signal_desk/routing.py`
- Modify: `insightbot/signal_desk/__init__.py`
- Test: `tests/test_signal_desk_routing.py`

- [ ] **Step 1: Write routing tests**

Add tests for:

- empty request returns `client_opportunity_radar`, `last_7_days`, `client_conversation`, `selected_signals`;
- explicit `raw`, `raw feed`, `全部`, `全量`, or `原始` returns `raw_feed`;
- explicit `brief`, `简报`, `日报`, `client brief`, or `proposal brief` returns `brief_output`;
- structured parameters override text;
- `proposal` / `pitch` maps to `proposal_angle`;
- `inspiration` / `案例` maps to `internal_inspiration`;
- `trend` / `趋势` maps to `trend_observation`;
- `30 days` / `30天` / `past month` maps to `last_30_days`;
- unknown explicit values fall back to defaults and return warnings;
- `route_to_intent_contract()` returns the existing `IntentContract` shape and does not persist `result_mode`.

- [ ] **Step 2: Implement `routing.py`**

Create:

```python
DEFAULT_PATTERN_ID = "client_opportunity_radar"
DEFAULT_TIME_WINDOW = "last_7_days"
DEFAULT_OUTPUT_INTENT = "client_conversation"
DEFAULT_RESULT_MODE = "selected_signals"
```

Add:

```python
@dataclass(slots=True)
class SignalDeskAccessRequest:
    text: str = ""
    pattern_id: str = ""
    room_id: str = ""
    client: str = ""
    category: str = ""
    focus_topics: list[str] = field(default_factory=list)
    time_window: str = ""
    output_intent: str = ""
    result_mode: str = ""
```

Add:

```python
@dataclass(slots=True)
class SignalDeskRoute:
    pattern_id: str
    time_window: str
    output_intent: str
    result_mode: str
    room_id: str = ""
    confidence: str = "rule_based"
    warnings: list[str] = field(default_factory=list)
```

Add resolver functions:

```python
resolve_signal_desk_route(request: SignalDeskAccessRequest | dict | None) -> SignalDeskRoute
route_to_intent_contract(route: SignalDeskRoute, *, room_id: str | None = None) -> IntentContract
```

- [ ] **Step 3: Export public routing contract**

Update `insightbot/signal_desk/__init__.py` so future UI/API/Skill callers can import routing objects from the package.

- [ ] **Step 4: Verify**

Run:

```powershell
python -m pytest tests/test_signal_desk_routing.py tests/test_signal_desk_patterns.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add insightbot/signal_desk/routing.py insightbot/signal_desk/__init__.py tests/test_signal_desk_routing.py
git commit -m "feat: add signal desk agent access routing"
```

### Task 2: Agent Access Documentation

**Files:**
- Create: `docs/signal_desk_agent_access_routing.md`
- Modify: `README.md`
- Modify: `docs/signal_desk_product_ia_pattern_architecture.md`
- Modify: `docs/signal_desk_mvp_architecture.md`

- [ ] **Step 1: Document routing semantics**

Create a short document that explains:

- Agent Access is a routing contract, not an autonomous agent;
- default route is selected signals;
- raw feed and brief output require explicit user intent;
- structured parameters override natural language;
- this contract is the future bridge for Skill/API/Web use.

- [ ] **Step 2: Link the document**

Add the document to `README.md` and mention it in the product IA and MVP architecture docs.

- [ ] **Step 3: Verify docs**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 4: Commit**

```powershell
git add README.md docs/signal_desk_agent_access_routing.md docs/signal_desk_product_ia_pattern_architecture.md docs/signal_desk_mvp_architecture.md docs/superpowers/plans/2026-05-11-signal-desk-agent-access-routing.md
git commit -m "docs: define signal desk agent access routing"
```
