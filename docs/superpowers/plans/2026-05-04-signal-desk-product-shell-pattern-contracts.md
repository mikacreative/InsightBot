# Signal Desk Product Shell And Pattern Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the current Streamlit console into a user-facing Signal Desk workspace and an operator-facing Control Center, while adding agent-ready Pattern, Intent, Quality Gate, and Feedback contracts.

**Architecture:** Keep the existing InsightBot runtime intact. Add structured product contracts under `insightbot/signal_desk/`, then make `scripts/app.py` render a product shell that defaults to Signal Desk and groups existing operational tabs under Control Center.

**Tech Stack:** Python dataclasses, existing Streamlit app, existing JSONL feedback storage, pytest.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `insightbot/signal_desk/patterns.py` | Pattern, intent, quality gate contracts and built-in registries |
| `insightbot/signal_desk/models.py` | Existing room/signal/feedback dataclasses; extend feedback record only if needed |
| `insightbot/signal_desk/feedback.py` | Persist richer feedback events with optional pattern/context metadata |
| `scripts/ui/signal_desk/product_shell.py` | Pure helpers for user workspace and Control Center labels |
| `scripts/ui/signal_desk/rooms.py` | Replace raw room creation form with pattern invocation context fields |
| `scripts/ui/signal_desk/room_detail.py` | Pass pattern/context metadata when recording feedback |
| `scripts/app.py` | Add two-mode shell: Signal Desk default and Control Center secondary |
| `tests/test_signal_desk_patterns.py` | Contract tests for patterns, intent, quality gates |
| `tests/test_signal_desk_feedback.py` | Backward-compatible richer feedback tests |
| `tests/test_signal_desk_product_shell.py` | Pure shell label/grouping tests |

## Task 1: Add Pattern, Intent, And Quality Gate Contracts

**Files:**
- Create: `insightbot/signal_desk/patterns.py`
- Create: `tests/test_signal_desk_patterns.py`
- Modify: `insightbot/signal_desk/__init__.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
from insightbot.signal_desk.patterns import (
    IntentContract,
    get_pattern_contract,
    get_quality_gate_contract,
    list_pattern_contracts,
)


def test_client_opportunity_radar_pattern_contract_exists():
    pattern = get_pattern_contract("client_opportunity_radar")

    assert pattern.id == "client_opportunity_radar"
    assert pattern.status == "published"
    assert "client" in pattern.required_context
    assert "category" in pattern.required_context
    assert pattern.default_quality_gate_id == "client_opportunity_radar_basic_quality"


def test_quality_gate_contract_requires_signal_card_fields():
    gate = get_quality_gate_contract("client_opportunity_radar_basic_quality")

    assert gate.requires_source is True
    assert gate.requires_why_it_matters is True
    assert gate.requires_suggested_action is True
    assert gate.requires_client_relevance is True
    assert gate.min_signal_count == 3


def test_intent_contract_round_trips_to_dict():
    intent = IntentContract(
        pattern_id="client_opportunity_radar",
        room_id="beauty_radar",
        client="Sephora",
        category="beauty retail",
        focus_topics=["AI retail"],
        output_intent="client_conversation",
        time_window="last_7_days",
    )

    assert intent.to_dict()["client"] == "Sephora"
    assert IntentContract.from_dict(intent.to_dict()).focus_topics == ["AI retail"]


def test_list_pattern_contracts_returns_published_patterns():
    patterns = list_pattern_contracts()

    assert any(pattern.id == "client_opportunity_radar" for pattern in patterns)
```

- [ ] **Step 2: Run red test**

Run:

```powershell
pytest tests/test_signal_desk_patterns.py -q
```

Expected: FAIL because `insightbot.signal_desk.patterns` does not exist.

- [ ] **Step 3: Implement contracts**

Create dataclasses:

```python
@dataclass(slots=True)
class PatternContract:
    id: str
    version: str
    name: str
    user_job: str
    required_context: list[str]
    optional_context: list[str]
    default_source_pack_ids: list[str]
    default_judgement_lens_ids: list[str]
    default_output_contract_ids: list[str]
    default_quality_gate_id: str
    status: str = "draft"
```

```python
@dataclass(slots=True)
class QualityGateContract:
    id: str
    requires_source: bool = True
    requires_why_it_matters: bool = True
    requires_suggested_action: bool = True
    requires_client_relevance: bool = True
    max_fallback_ratio: float = 0.2
    min_signal_count: int = 3
    max_duplicate_ratio: float = 0.25
```

```python
@dataclass(slots=True)
class IntentContract:
    pattern_id: str
    room_id: str
    client: str = ""
    category: str = ""
    focus_topics: list[str] = field(default_factory=list)
    output_intent: str = "client_conversation"
    time_window: str = "last_7_days"
```

Include `to_dict()` and `from_dict()` methods for all three.

- [ ] **Step 4: Run green test**

Run:

```powershell
pytest tests/test_signal_desk_patterns.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add insightbot/signal_desk/patterns.py insightbot/signal_desk/__init__.py tests/test_signal_desk_patterns.py
git commit -m "feat: add signal desk pattern contracts"
```

## Task 2: Add Product Shell Helpers

**Files:**
- Create: `scripts/ui/signal_desk/product_shell.py`
- Create: `tests/test_signal_desk_product_shell.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
from scripts.ui.signal_desk.product_shell import (
    CONTROL_CENTER_TABS,
    USER_WORKSPACE_TABS,
    normalize_product_mode,
)


def test_user_workspace_tabs_hide_operator_surfaces():
    assert USER_WORKSPACE_TABS == ["Rooms", "Signals", "Saved", "Briefs"]
    assert "Task Management" not in USER_WORKSPACE_TABS
    assert "Channels" not in USER_WORKSPACE_TABS
    assert "Logs" not in USER_WORKSPACE_TABS


def test_control_center_tabs_keep_operator_surfaces():
    assert "Task Management" in CONTROL_CENTER_TABS
    assert "Channels" in CONTROL_CENTER_TABS
    assert "Validation" in CONTROL_CENTER_TABS
    assert "Logs" in CONTROL_CENTER_TABS


def test_normalize_product_mode_defaults_to_signal_desk():
    assert normalize_product_mode("") == "Signal Desk"
    assert normalize_product_mode("Control Center") == "Control Center"
```

- [ ] **Step 2: Run red test**

```powershell
pytest tests/test_signal_desk_product_shell.py -q
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement helper module**

Create constants and helper:

```python
USER_WORKSPACE_TABS = ["Rooms", "Signals", "Saved", "Briefs"]
CONTROL_CENTER_TABS = [
    "Overview",
    "Task Management",
    "Channels",
    "Validation",
    "Logs",
    "Delivery Format",
    "Task Debug",
]

def normalize_product_mode(value: str) -> str:
    return "Control Center" if value == "Control Center" else "Signal Desk"
```

- [ ] **Step 4: Run green test**

```powershell
pytest tests/test_signal_desk_product_shell.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/ui/signal_desk/product_shell.py tests/test_signal_desk_product_shell.py
git commit -m "feat: add signal desk product shell helpers"
```

## Task 3: Split Streamlit Into Signal Desk And Control Center Modes

**Files:**
- Modify: `scripts/app.py`
- Modify: `scripts/ui/signal_desk/rooms.py` only if needed for labels

- [ ] **Step 1: Add a lightweight smoke test guard**

Use existing Streamlit testing as smoke verification after implementation:

```powershell
@'
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("scripts/app.py")
at.run(timeout=30)
print("exception_count=", len(at.exception))
assert len(at.exception) == 0
text = "\n".join(str(item.value) for item in at.markdown if getattr(item, "value", ""))
assert "Signal Desk" in text or len(at.tabs) > 0
'@ | python -
```

This is not committed as a test file because Streamlit app state depends on local config; use it as smoke verification.

- [ ] **Step 2: Modify app shell**

Import:

```python
from scripts.ui.signal_desk.product_shell import normalize_product_mode
```

Near the current tab creation, add a mode selector:

```python
product_mode = normalize_product_mode(
    st.sidebar.radio(
        "Product mode",
        options=["Signal Desk", "Control Center"],
        index=0,
    )
)
```

If `product_mode == "Signal Desk"`, render only:

- Rooms
- Signals placeholder
- Saved
- Briefs placeholder

If `product_mode == "Control Center"`, render existing operational tabs.

- [ ] **Step 3: Verify smoke**

Run:

```powershell
python -m compileall scripts
```

Expected: exit 0.

Run the AppTest smoke command from Step 1.

Expected: `exception_count= 0`.

- [ ] **Step 4: Commit**

```powershell
git add scripts/app.py
git commit -m "feat: split signal desk product shell"
```

## Task 4: Wire Pattern Invocation Context Into Room Creation

**Files:**
- Modify: `scripts/ui/signal_desk/rooms.py`
- Modify: `insightbot/signal_desk/models.py` only if room fields need helper methods
- Modify: `tests/test_signal_desk_storage.py` or `tests/test_signal_desk_patterns.py`

- [ ] **Step 1: Write failing test**

Add a test that a room can persist pattern invocation context through `client_context`:

```python
from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.patterns import IntentContract


def test_room_stores_pattern_intent_context():
    intent = IntentContract(
        pattern_id="client_opportunity_radar",
        room_id="beauty_radar",
        client="Sephora",
        category="beauty retail",
        focus_topics=["AI retail"],
        output_intent="client_conversation",
    )
    room = BriefingRoom(
        id="beauty_radar",
        name="Beauty Radar",
        topic="Beauty retail signals",
        source_pack_ids=["marketing_comms_cn"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance"],
        channels=[],
        schedule={"hour": 8, "minute": 0},
        client_context={"intent": intent.to_dict()},
    )

    restored = BriefingRoom.from_dict(room.to_dict())

    assert restored.client_context["intent"]["client"] == "Sephora"
```

- [ ] **Step 2: Run red or confirm existing behavior**

Run:

```powershell
pytest tests/test_signal_desk_storage.py::test_room_stores_pattern_intent_context -q
```

If it passes immediately because `client_context` already round-trips, keep the test as regression and proceed to UI changes.

- [ ] **Step 3: Update room creation UI**

In `render_rooms_tab()`, replace low-level default copy with pattern-driven context fields:

- pattern selector, default `Client Opportunity Radar`
- client
- category
- focus topics
- output intent
- time window

Build `IntentContract` and store it under:

```python
client_context={"intent": intent.to_dict()}
```

Use pattern defaults for source packs and judgement lenses.

- [ ] **Step 4: Run verification**

```powershell
pytest tests/test_signal_desk_storage.py tests/test_signal_desk_patterns.py -q
python -m compileall scripts insightbot
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/ui/signal_desk/rooms.py tests/test_signal_desk_storage.py
git commit -m "feat: capture room pattern intent"
```

## Task 5: Enrich Feedback Events With Pattern And Context

**Files:**
- Modify: `insightbot/signal_desk/models.py`
- Modify: `insightbot/signal_desk/feedback.py`
- Modify: `scripts/ui/signal_desk/room_detail.py`
- Modify: `tests/test_signal_desk_feedback.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_append_feedback_records_pattern_and_context(tmp_path):
    append_feedback(
        "sig_001",
        "client_radar_beauty",
        "good_for_pitch",
        pattern_id="client_opportunity_radar",
        context={"client": "Sephora", "category": "beauty retail"},
        bot_dir=str(tmp_path),
    )

    records = list_feedback(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert records[0]["pattern_id"] == "client_opportunity_radar"
    assert records[0]["context"]["client"] == "Sephora"
```

- [ ] **Step 2: Run red test**

```powershell
pytest tests/test_signal_desk_feedback.py::test_append_feedback_records_pattern_and_context -q
```

Expected: FAIL because `append_feedback()` does not accept these kwargs.

- [ ] **Step 3: Implement backward-compatible feedback fields**

Add optional fields to `FeedbackRecord`:

```python
pattern_id: str = ""
context: dict[str, Any] = field(default_factory=dict)
```

Update `append_feedback()` signature:

```python
def append_feedback(..., pattern_id: str = "", context: dict[str, Any] | None = None, ...)
```

Pass these into `FeedbackRecord`.

- [ ] **Step 4: Update UI feedback call**

In `room_detail.py`, pass:

```python
pattern_id=room.use_case_template_id
context=room.client_context.get("intent", room.client_context)
```

- [ ] **Step 5: Run verification**

```powershell
pytest tests/test_signal_desk_feedback.py -q
python -m compileall insightbot scripts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add insightbot/signal_desk/models.py insightbot/signal_desk/feedback.py scripts/ui/signal_desk/room_detail.py tests/test_signal_desk_feedback.py
git commit -m "feat: enrich signal desk feedback context"
```

## Task 6: Final Verification

**Files:**
- No new files unless a smoke script is added.

- [ ] **Step 1: Compile**

```powershell
python -m compileall insightbot scripts
```

Expected: exit 0.

- [ ] **Step 2: Run focused Signal Desk tests**

```powershell
pytest tests/test_signal_desk_storage.py tests/test_signal_desk_presets.py tests/test_signal_desk_patterns.py tests/test_signal_desk_compiler.py tests/test_signal_desk_signals.py tests/test_signal_desk_feedback.py tests/test_signal_desk_product_shell.py -q
```

Expected: all pass.

- [ ] **Step 3: Run regression tests**

```powershell
pytest tests/test_config_paths.py tests/test_task_runner.py tests/test_task_validation.py tests/test_run_history.py -q
```

Expected: all pass.

- [ ] **Step 4: Run Streamlit smoke**

```powershell
@'
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("scripts/app.py")
at.run(timeout=30)
print("exception_count=", len(at.exception))
assert len(at.exception) == 0
'@ | python -
```

Expected: `exception_count= 0`.

- [ ] **Step 5: Final status**

Confirm:

```powershell
git status --short --branch
git log --oneline -n 12
```

Expected: only pre-existing untracked `* 2` files remain.

