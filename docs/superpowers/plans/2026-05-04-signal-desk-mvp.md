# Signal Desk MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Signal Desk MVP slice for `Client Opportunity Radar`: product-layer room objects, source/preset defaults, room-to-task compilation, dry-run signal preview, saved signals, feedback, and minimal Streamlit wiring.

**Architecture:** Add a new `insightbot/signal_desk/` product layer above the existing `tasks.json` runtime. `BriefingRoom` remains the user-facing source of truth and compiles into a normal InsightBot task using the current `task_runner` and `editorial-intelligence` bridge.

**Tech Stack:** Python dataclasses, JSON / JSONL local storage, existing InsightBot task config helpers, pytest, Streamlit UI modules.

---

## Current Context

Read these first:

- `docs/signal_desk_prd.md`
- `docs/signal_desk_mvp_architecture.md`
- `insightbot/config.py`
- `insightbot/task_runner.py`
- `insightbot/paths.py`
- `scripts/app.py`

Do not touch unrelated untracked files currently present in the worktree:

- `AGENTS 2.md`
- `editorial-intelligence/editorial_intelligence/contracts/source_strategy 2.py`
- `editorial-intelligence/examples/insightbot_integration 2.py`
- `editorial-intelligence/tests/test_insightbot_bridge 2.py`
- `insightbot/wecom_callback 2.py`

## File Structure

Create:

```text
insightbot/signal_desk/
  __init__.py
  models.py
  storage.py
  presets.py
  source_packs.py
  compiler.py
  signals.py
  feedback.py

scripts/ui/signal_desk/
  __init__.py
  rooms.py
  room_detail.py
  saved_signals.py

tests/test_signal_desk_storage.py
tests/test_signal_desk_presets.py
tests/test_signal_desk_compiler.py
tests/test_signal_desk_signals.py
tests/test_signal_desk_feedback.py
```

Modify:

```text
insightbot/paths.py
scripts/app.py
README.md
```

Do not modify `task_runner.py` in this first implementation unless tests prove a missing integration point. The compiler should output a task definition that the existing runtime already understands.

---

### Task 1: Add Signal Desk Models And Paths

**Files:**

- Create: `insightbot/signal_desk/__init__.py`
- Create: `insightbot/signal_desk/models.py`
- Modify: `insightbot/paths.py`
- Test: `tests/test_signal_desk_storage.py`

- [ ] **Step 1: Write failing tests for new path helpers and model serialization**

Create `tests/test_signal_desk_storage.py` with:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_signal_desk_storage.py -v
```

Expected: FAIL with import errors for `signal_desk_dir` and `BriefingRoom`.

- [ ] **Step 3: Add path helpers**

Modify `insightbot/paths.py` by adding:

```python
def signal_desk_dir(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("SIGNAL_DESK_DIR", os.path.join(data_dir(bot_dir), "signal_desk"))


def signal_desk_rooms_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("SIGNAL_DESK_ROOMS_FILE", os.path.join(signal_desk_dir(bot_dir), "rooms.json"))


def signal_desk_saved_signals_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("SIGNAL_DESK_SAVED_SIGNALS_FILE", os.path.join(signal_desk_dir(bot_dir), "saved_signals.jsonl"))


def signal_desk_feedback_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("SIGNAL_DESK_FEEDBACK_FILE", os.path.join(signal_desk_dir(bot_dir), "feedback.jsonl"))
```

- [ ] **Step 4: Add models**

Create `insightbot/signal_desk/__init__.py`:

```python
"""Signal Desk product-layer helpers."""
```

Create `insightbot/signal_desk/models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass(slots=True)
class BriefingRoom:
    id: str
    name: str
    topic: str
    source_pack_ids: list[str]
    editorial_preset_id: str
    judgement_lens_ids: list[str]
    channels: list[str]
    schedule: dict[str, int]
    enabled: bool = False
    use_case_template_id: str = "client_opportunity_radar"
    audience: str = "senior account and strategy team"
    focus_areas: list[str] = field(default_factory=list)
    client_context: dict[str, Any] = field(default_factory=dict)
    compiled_task_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.compiled_task_id:
            self.compiled_task_id = f"room_{self.id}"
        now = _utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BriefingRoom":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            topic=str(data["topic"]),
            source_pack_ids=list(data.get("source_pack_ids", [])),
            editorial_preset_id=str(data.get("editorial_preset_id", "client_opportunity_radar")),
            judgement_lens_ids=list(data.get("judgement_lens_ids", [])),
            channels=list(data.get("channels", [])),
            schedule=dict(data.get("schedule", {"hour": 8, "minute": 0})),
            enabled=bool(data.get("enabled", False)),
            use_case_template_id=str(data.get("use_case_template_id", "client_opportunity_radar")),
            audience=str(data.get("audience", "senior account and strategy team")),
            focus_areas=list(data.get("focus_areas", [])),
            client_context=dict(data.get("client_context", {})),
            compiled_task_id=str(data.get("compiled_task_id", "")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )


@dataclass(slots=True)
class SignalItem:
    id: str
    room_id: str
    run_id: str
    what_happened: str
    why_it_matters: str
    client_relevance: str
    suggested_action: str
    judgement_lens: list[str]
    source: dict[str, str]
    confidence: str = "medium"
    save_tags: list[str] = field(default_factory=list)
    raw_candidate_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SavedSignal:
    id: str
    signal: dict[str, Any]
    room_id: str
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FeedbackRecord:
    id: str
    signal_id: str
    room_id: str
    action: str
    note: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
pytest tests/test_signal_desk_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add insightbot/paths.py insightbot/signal_desk/__init__.py insightbot/signal_desk/models.py tests/test_signal_desk_storage.py
git commit -m "feat: add signal desk models and paths"
```

---

### Task 2: Add Room Storage

**Files:**

- Create: `insightbot/signal_desk/storage.py`
- Modify: `tests/test_signal_desk_storage.py`

- [ ] **Step 1: Add failing storage tests**

Append to `tests/test_signal_desk_storage.py`:

```python
from insightbot.signal_desk.storage import load_rooms, save_room, delete_room


def test_save_load_and_delete_room(tmp_path):
    bot_dir = str(tmp_path)
    room = BriefingRoom(
        id="client_radar_beauty",
        name="Beauty Client Opportunity Radar",
        topic="Beauty signals",
        source_pack_ids=["marketing_comms_cn"],
        editorial_preset_id="client_opportunity_radar",
        judgement_lens_ids=["client_relevance"],
        channels=["wecom_main"],
        schedule={"hour": 8, "minute": 0},
    )

    save_room(room, bot_dir=bot_dir)
    rooms = load_rooms(bot_dir=bot_dir)

    assert list(rooms.keys()) == ["client_radar_beauty"]
    assert rooms["client_radar_beauty"].name == "Beauty Client Opportunity Radar"

    delete_room("client_radar_beauty", bot_dir=bot_dir)

    assert load_rooms(bot_dir=bot_dir) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/test_signal_desk_storage.py::test_save_load_and_delete_room -v
```

Expected: FAIL with import error for `insightbot.signal_desk.storage`.

- [ ] **Step 3: Implement room storage**

Create `insightbot/signal_desk/storage.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path

from insightbot.paths import signal_desk_rooms_file_path
from insightbot.signal_desk.models import BriefingRoom


def _atomic_write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    os.replace(tmp, target)


def load_rooms(bot_dir: str | None = None) -> dict[str, BriefingRoom]:
    path = signal_desk_rooms_file_path(bot_dir)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rooms = payload.get("rooms", {})
    return {
        room_id: BriefingRoom.from_dict(room_data)
        for room_id, room_data in rooms.items()
        if isinstance(room_data, dict)
    }


def save_rooms(rooms: dict[str, BriefingRoom], bot_dir: str | None = None) -> None:
    payload = {"rooms": {room_id: room.to_dict() for room_id, room in rooms.items()}}
    _atomic_write_json(signal_desk_rooms_file_path(bot_dir), payload)


def save_room(room: BriefingRoom, bot_dir: str | None = None) -> None:
    rooms = load_rooms(bot_dir=bot_dir)
    rooms[room.id] = room
    save_rooms(rooms, bot_dir=bot_dir)


def delete_room(room_id: str, bot_dir: str | None = None) -> None:
    rooms = load_rooms(bot_dir=bot_dir)
    rooms.pop(room_id, None)
    save_rooms(rooms, bot_dir=bot_dir)
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
pytest tests/test_signal_desk_storage.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add insightbot/signal_desk/storage.py tests/test_signal_desk_storage.py
git commit -m "feat: add signal desk room storage"
```

---

### Task 3: Add Presets, Judgement Lenses, And Source Packs

**Files:**

- Create: `insightbot/signal_desk/presets.py`
- Create: `insightbot/signal_desk/source_packs.py`
- Test: `tests/test_signal_desk_presets.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_signal_desk_presets.py`:

```python
from insightbot.signal_desk.presets import (
    get_editorial_preset,
    get_judgement_lenses,
    get_use_case_template,
)
from insightbot.signal_desk.source_packs import get_source_pack, merge_source_packs


def test_client_opportunity_radar_defaults_exist():
    template = get_use_case_template("client_opportunity_radar")
    preset = get_editorial_preset("client_opportunity_radar")
    lenses = get_judgement_lenses(["client_relevance", "pitch_potential"])

    assert template["default_editorial_preset_id"] == "client_opportunity_radar"
    assert "suggested action" in " ".join(preset["quality_checks"]).lower()
    assert [lens["id"] for lens in lenses] == ["client_relevance", "pitch_potential"]


def test_source_pack_has_trust_metadata():
    pack = get_source_pack("marketing_comms_cn")

    assert pack["coverage"]
    assert pack["limitations"]
    assert "China-heavy" in pack["bias"]
    assert pack["freshness"] == "daily"


def test_merge_source_packs_dedupes_feeds_and_queries():
    merged = merge_source_packs([
        get_source_pack("marketing_comms_cn"),
        get_source_pack("marketing_comms_cn"),
    ])

    rss = merged["feeds"]["Marketing Communications"]["rss"]
    queries = merged["search"]["queries"]

    assert len(rss) == len(set(rss))
    assert len(queries) == len(set(queries))
    assert merged["search"]["enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_signal_desk_presets.py -v
```

Expected: FAIL with import errors for `presets` and `source_packs`.

- [ ] **Step 3: Implement presets**

Create `insightbot/signal_desk/presets.py`:

```python
from __future__ import annotations

from copy import deepcopy


USE_CASE_TEMPLATES = {
    "client_opportunity_radar": {
        "id": "client_opportunity_radar",
        "name": "Client Opportunity Radar",
        "description": "Find client-relevant market signals, cases, trends, and pitchable ideas.",
        "default_editorial_preset_id": "client_opportunity_radar",
        "default_judgement_lens_ids": [
            "client_relevance",
            "pitch_potential",
            "case_inspiration",
            "strategic_implication",
        ],
        "recommended_source_pack_ids": [
            "marketing_comms_cn",
            "brand_marketing_global",
            "ai_martech",
        ],
        "default_schedule": {"hour": 8, "minute": 0},
    }
}


EDITORIAL_PRESETS = {
    "client_opportunity_radar": {
        "id": "client_opportunity_radar",
        "name": "Client Opportunity Radar",
        "shortlist_size": 8,
        "selection_rules": [
            "Prefer signals that can support client service, proposal development, or strategic advice.",
            "Reject generic news without a clear marketing communications implication.",
            "Prefer cases, category movement, platform changes, consumer behavior shifts, and brand actions.",
        ],
        "section_rules": {
            "Client Conversation Starters": "Signals that can be raised with a current client.",
            "Pitchable Ideas": "Signals that can become proposal angles or service ideas.",
            "Case Inspiration": "Campaigns, formats, mechanics, or examples worth saving.",
            "Watchouts": "Risks, category changes, or competitor pressure.",
        },
        "dedupe_rules": [
            "Merge multiple reports about the same event into one signal.",
        ],
        "tone": "senior, concise, judgement-led",
        "citation_style": "inline",
        "quality_checks": [
            "Each item must include why it matters.",
            "Each item must include a suggested action.",
            "Each item must cite its source.",
        ],
    }
}


JUDGEMENT_LENSES = {
    "market_movement": {
        "id": "market_movement",
        "label": "Market Movement",
        "core_question": "What changed, and is the change meaningful?",
    },
    "client_relevance": {
        "id": "client_relevance",
        "label": "Client Relevance",
        "core_question": "Which current clients may care, and why?",
    },
    "pitch_potential": {
        "id": "pitch_potential",
        "label": "Pitch Potential",
        "core_question": "Can this become a proposal angle, service idea, or BD hook?",
    },
    "case_inspiration": {
        "id": "case_inspiration",
        "label": "Case Inspiration",
        "core_question": "Does this provide a useful case, format, mechanic, or proof point?",
    },
    "strategic_implication": {
        "id": "strategic_implication",
        "label": "Strategic Implication",
        "core_question": "What larger pattern or business implication does this suggest?",
    },
    "risk_watchout": {
        "id": "risk_watchout",
        "label": "Risk / Watchout",
        "core_question": "Does this create a risk, blind spot, or competitor pressure?",
    },
}


def get_use_case_template(template_id: str) -> dict:
    return deepcopy(USE_CASE_TEMPLATES[template_id])


def list_use_case_templates() -> list[dict]:
    return [deepcopy(item) for item in USE_CASE_TEMPLATES.values()]


def get_editorial_preset(preset_id: str) -> dict:
    return deepcopy(EDITORIAL_PRESETS[preset_id])


def list_editorial_presets() -> list[dict]:
    return [deepcopy(item) for item in EDITORIAL_PRESETS.values()]


def get_judgement_lens(lens_id: str) -> dict:
    return deepcopy(JUDGEMENT_LENSES[lens_id])


def get_judgement_lenses(lens_ids: list[str]) -> list[dict]:
    return [get_judgement_lens(lens_id) for lens_id in lens_ids]


def list_judgement_lenses() -> list[dict]:
    return [deepcopy(item) for item in JUDGEMENT_LENSES.values()]
```

- [ ] **Step 4: Implement source packs**

Create `insightbot/signal_desk/source_packs.py`:

```python
from __future__ import annotations

from copy import deepcopy


SOURCE_PACKS = {
    "marketing_comms_cn": {
        "id": "marketing_comms_cn",
        "name": "China Marketing Communications",
        "description": "Chinese marketing, brand, communication, and campaign sources.",
        "coverage": "Campaign cases, agency news, marketing industry opinions, brand communication examples.",
        "limitations": "May miss closed social platform content and client-specific category news.",
        "bias": ["China-heavy", "marketing-media-heavy", "case-heavy"],
        "freshness": "daily",
        "feeds": {
            "Marketing Communications": {
                "rss": [
                    "https://www.digitaling.com/rss # 数英网",
                    "https://www.meihua.info/feed # 梅花网",
                ],
                "keywords": ["营销", "品牌", "案例"],
                "prompt": "Keep client-relevant marketing communications cases and trends.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["中国 营销 案例 趋势", "品牌 营销 传播 案例"],
        },
    },
    "brand_marketing_global": {
        "id": "brand_marketing_global",
        "name": "Global Brand Marketing",
        "description": "Global brand, campaign, and marketing industry sources.",
        "coverage": "Global brand campaigns, marketing platform movement, and industry commentary.",
        "limitations": "May overrepresent English-language and US/Europe market examples.",
        "bias": ["global-heavy", "English-heavy", "campaign-heavy"],
        "freshness": "daily",
        "feeds": {
            "Global Brand Marketing": {
                "rss": [
                    "https://www.marketingdive.com/feeds/news/ # Marketing Dive",
                    "https://www.adweek.com/feed/ # Adweek",
                ],
                "keywords": ["brand", "campaign", "marketing"],
                "prompt": "Keep examples with clear relevance to brand, communication, content, or campaign work.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["brand campaign marketing case", "creative campaign brand marketing"],
        },
    },
    "ai_martech": {
        "id": "ai_martech",
        "name": "AI and Martech",
        "description": "AI, marketing technology, platform, and consumer-facing tool signals.",
        "coverage": "AI marketing applications, platform changes, martech products, and consumer-facing AI use cases.",
        "limitations": "May include technical AI news that needs editorial filtering for marketing relevance.",
        "bias": ["tech-heavy", "AI-heavy", "tool-heavy"],
        "freshness": "daily",
        "feeds": {
            "AI and Martech": {
                "rss": [
                    "https://blog.hubspot.com/marketing/rss.xml # HubSpot Marketing",
                    "https://technode.com/feed/ # TechNode",
                ],
                "keywords": ["AI", "martech", "platform"],
                "prompt": "Keep AI and platform changes only when they affect marketing, content, media, or client work.",
            }
        },
        "search": {
            "enabled": True,
            "queries": ["AI marketing trend case", "martech platform marketing update"],
        },
    },
}


def get_source_pack(pack_id: str) -> dict:
    return deepcopy(SOURCE_PACKS[pack_id])


def list_source_packs() -> list[dict]:
    return [deepcopy(item) for item in SOURCE_PACKS.values()]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def merge_source_packs(packs: list[dict]) -> dict:
    merged = {"feeds": {}, "search": {"enabled": False, "queries": []}, "trust": []}
    for pack in packs:
        merged["trust"].append({
            "id": pack["id"],
            "name": pack["name"],
            "coverage": pack.get("coverage", ""),
            "limitations": pack.get("limitations", ""),
            "bias": list(pack.get("bias", [])),
            "freshness": pack.get("freshness", ""),
        })
        for section, section_data in pack.get("feeds", {}).items():
            target = merged["feeds"].setdefault(section, {"rss": [], "keywords": [], "prompt": ""})
            target["rss"] = _dedupe(target["rss"] + list(section_data.get("rss", [])))
            target["keywords"] = _dedupe(target["keywords"] + list(section_data.get("keywords", [])))
            prompt = section_data.get("prompt", "")
            if prompt and prompt not in target["prompt"]:
                target["prompt"] = (target["prompt"] + "\n" + prompt).strip()
        search = pack.get("search", {})
        if search.get("enabled"):
            merged["search"]["enabled"] = True
        merged["search"]["queries"] = _dedupe(merged["search"]["queries"] + list(search.get("queries", [])))
    return merged
```

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_signal_desk_presets.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add insightbot/signal_desk/presets.py insightbot/signal_desk/source_packs.py tests/test_signal_desk_presets.py
git commit -m "feat: add signal desk presets and source packs"
```

---

### Task 4: Add Room-To-Task Compiler

**Files:**

- Create: `insightbot/signal_desk/compiler.py`
- Test: `tests/test_signal_desk_compiler.py`

- [ ] **Step 1: Write failing compiler tests**

Create `tests/test_signal_desk_compiler.py`:

```python
from insightbot.signal_desk.compiler import compile_room_to_task
from insightbot.signal_desk.models import BriefingRoom


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_signal_desk_compiler.py -v
```

Expected: FAIL with import error for `compiler`.

- [ ] **Step 3: Implement compiler**

Create `insightbot/signal_desk/compiler.py`:

```python
from __future__ import annotations

from copy import deepcopy

from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.presets import get_editorial_preset, get_judgement_lenses
from insightbot.signal_desk.source_packs import get_source_pack, merge_source_packs


def _build_pipeline_config(room: BriefingRoom) -> dict:
    preset = get_editorial_preset(room.editorial_preset_id)
    lenses = get_judgement_lenses(room.judgement_lens_ids)

    selection_rules = list(preset.get("selection_rules", []))
    selection_rules.append(f"Room topic: {room.topic}")
    if room.focus_areas:
        selection_rules.append("Room focus areas: " + ", ".join(room.focus_areas))
    for lens in lenses:
        selection_rules.append(f"{lens['label']}: {lens['core_question']}")

    return {
        "shortlist_size": int(preset.get("shortlist_size", 8)),
        "selection_rules": selection_rules,
        "section_rules": deepcopy(preset.get("section_rules", {})),
        "dedupe_rules": list(preset.get("dedupe_rules", [])),
        "tone": preset.get("tone", "senior, concise, judgement-led"),
        "citation_style": preset.get("citation_style", "inline"),
        "quality_checks": list(preset.get("quality_checks", [])),
        "judgement_lenses": lenses,
        "signal_output_contract": {
            "required_fields": [
                "what_happened",
                "why_it_matters",
                "client_relevance",
                "suggested_action",
                "source",
                "confidence",
            ]
        },
    }


def compile_room_to_task(room: BriefingRoom) -> tuple[str, dict]:
    packs = [get_source_pack(pack_id) for pack_id in room.source_pack_ids]
    merged_sources = merge_source_packs(packs)
    task_id = room.compiled_task_id

    task_def = {
        "name": room.name,
        "enabled": room.enabled,
        "feeds": merged_sources["feeds"],
        "pipeline": "editorial",
        "_editorial_pipeline_mode": "editorial-intelligence",
        "_signal_desk_room_id": room.id,
        "_signal_desk_compiled": True,
        "pipeline_config": _build_pipeline_config(room),
        "search": merged_sources["search"],
        "channels": list(room.channels),
        "schedule": dict(room.schedule),
        "source_pack_trust": merged_sources["trust"],
    }
    return task_id, task_def
```

- [ ] **Step 4: Run compiler tests**

Run:

```bash
pytest tests/test_signal_desk_compiler.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add insightbot/signal_desk/compiler.py tests/test_signal_desk_compiler.py
git commit -m "feat: compile signal desk rooms to tasks"
```

---

### Task 5: Add Signal Conversion From Run Results

**Files:**

- Create: `insightbot/signal_desk/signals.py`
- Test: `tests/test_signal_desk_signals.py`

- [ ] **Step 1: Write failing signal conversion tests**

Create `tests/test_signal_desk_signals.py`:

```python
from insightbot.signal_desk.signals import signal_items_from_run_result


def test_signal_items_from_structured_shortlist():
    run_result = {
        "task_id": "room_client_radar_beauty",
        "stage_results": {
            "shortlist": [
                {
                    "title": "Brand launches AI shopping assistant",
                    "summary": "A beauty brand launched an AI shopping assistant.",
                    "why_it_matters": "It shows AI moving into retail conversion.",
                    "url": "https://example.com/ai-shopping",
                    "published_at": "2026-05-04",
                    "judgement_lens": ["client_relevance"],
                    "confidence": "high",
                }
            ]
        },
    }

    items = signal_items_from_run_result(
        room_id="client_radar_beauty",
        run_id="run_001",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Brand launches AI shopping assistant"
    assert items[0].why_it_matters == "It shows AI moving into retail conversion."
    assert items[0].source["url"] == "https://example.com/ai-shopping"
    assert items[0].confidence == "high"


def test_signal_items_fallback_to_final_markdown():
    run_result = {
        "final_markdown": "### Platform changes social search\nThis may affect content discovery.",
        "stage_results": {},
    }

    items = signal_items_from_run_result(
        room_id="client_radar_social",
        run_id="run_002",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Platform changes social search"
    assert items[0].confidence == "low"
    assert items[0].source == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_signal_desk_signals.py -v
```

Expected: FAIL with import error for `signals`.

- [ ] **Step 3: Implement signal conversion**

Create `insightbot/signal_desk/signals.py`:

```python
from __future__ import annotations

import hashlib
import re
from typing import Any

from insightbot.signal_desk.models import SignalItem


def _make_signal_id(room_id: str, run_id: str, value: str) -> str:
    digest = hashlib.sha1(f"{room_id}|{run_id}|{value}".encode("utf-8")).hexdigest()[:10]
    return f"sig_{digest}"


def _candidate_to_signal(room_id: str, run_id: str, candidate: dict[str, Any]) -> SignalItem:
    title = str(candidate.get("title") or candidate.get("what_happened") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    why = str(candidate.get("why_it_matters") or candidate.get("reason") or summary).strip()
    url = str(candidate.get("url") or candidate.get("source_url") or "").strip()
    published_at = str(candidate.get("published_at") or "").strip()
    lens = candidate.get("judgement_lens") or candidate.get("judgement_lenses") or []
    if isinstance(lens, str):
        lens = [lens]

    return SignalItem(
        id=_make_signal_id(room_id, run_id, title or summary),
        room_id=room_id,
        run_id=run_id,
        what_happened=title or summary,
        why_it_matters=why,
        client_relevance=str(candidate.get("client_relevance") or "Review for client relevance.").strip(),
        suggested_action=str(candidate.get("suggested_action") or "Save or discuss with the relevant client team.").strip(),
        judgement_lens=list(lens),
        source={"title": title, "url": url, "published_at": published_at} if url else {},
        confidence=str(candidate.get("confidence") or "medium"),
        save_tags=list(candidate.get("save_tags", [])) if isinstance(candidate.get("save_tags", []), list) else [],
        raw_candidate_ref=str(candidate.get("id") or ""),
    )


def _markdown_to_signal(room_id: str, run_id: str, markdown: str) -> list[SignalItem]:
    match = re.search(r"^#{1,4}\s+(.+)$", markdown, flags=re.MULTILINE)
    if not match:
        return []
    title = match.group(1).strip()
    return [
        SignalItem(
            id=_make_signal_id(room_id, run_id, title),
            room_id=room_id,
            run_id=run_id,
            what_happened=title,
            why_it_matters="Review the generated brief for context.",
            client_relevance="Review for client relevance.",
            suggested_action="Open the full brief before using this signal.",
            judgement_lens=[],
            source={},
            confidence="low",
            save_tags=[],
        )
    ]


def signal_items_from_run_result(room_id: str, run_id: str, run_result: dict[str, Any]) -> list[SignalItem]:
    stage_results = run_result.get("stage_results", {}) if isinstance(run_result, dict) else {}
    shortlist = stage_results.get("shortlist") if isinstance(stage_results, dict) else None
    if isinstance(shortlist, list) and shortlist:
        return [
            _candidate_to_signal(room_id, run_id, item)
            for item in shortlist
            if isinstance(item, dict)
        ]
    markdown = str(run_result.get("final_markdown") or "")
    return _markdown_to_signal(room_id, run_id, markdown)
```

- [ ] **Step 4: Run signal tests**

Run:

```bash
pytest tests/test_signal_desk_signals.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add insightbot/signal_desk/signals.py tests/test_signal_desk_signals.py
git commit -m "feat: convert task runs to signal items"
```

---

### Task 6: Add Saved Signals And Feedback Storage

**Files:**

- Create: `insightbot/signal_desk/feedback.py`
- Test: `tests/test_signal_desk_feedback.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_signal_desk_feedback.py`:

```python
from insightbot.signal_desk.feedback import (
    append_feedback,
    list_feedback,
    list_saved_signals,
    save_signal,
    summarize_feedback,
)
from insightbot.signal_desk.models import SignalItem


def make_signal() -> SignalItem:
    return SignalItem(
        id="sig_001",
        room_id="client_radar_beauty",
        run_id="run_001",
        what_happened="Brand launches AI shopping assistant",
        why_it_matters="It affects retail conversion.",
        client_relevance="Beauty and retail clients.",
        suggested_action="Use as a client conversation starter.",
        judgement_lens=["client_relevance"],
        source={"title": "Example", "url": "https://example.com"},
        confidence="high",
        save_tags=["client-service"],
    )


def test_save_signal_and_list(tmp_path):
    saved = save_signal(make_signal(), tags=["pitch"], notes="Use next week", bot_dir=str(tmp_path))

    items = list_saved_signals(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert saved.id.startswith("saved_")
    assert len(items) == 1
    assert items[0]["room_id"] == "client_radar_beauty"
    assert items[0]["tags"] == ["pitch"]
    assert items[0]["notes"] == "Use next week"


def test_append_feedback_and_summarize(tmp_path):
    append_feedback("sig_001", "client_radar_beauty", "good_for_pitch", bot_dir=str(tmp_path))
    append_feedback("sig_002", "client_radar_beauty", "good_for_pitch", bot_dir=str(tmp_path))
    append_feedback("sig_003", "client_radar_beauty", "not_relevant", bot_dir=str(tmp_path))

    records = list_feedback(room_id="client_radar_beauty", bot_dir=str(tmp_path))
    summary = summarize_feedback(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert len(records) == 3
    assert summary == {"good_for_pitch": 2, "not_relevant": 1}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_signal_desk_feedback.py -v
```

Expected: FAIL with import error for `feedback`.

- [ ] **Step 3: Implement saved signals and feedback**

Create `insightbot/signal_desk/feedback.py`:

```python
from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from insightbot.paths import signal_desk_feedback_file_path, signal_desk_saved_signals_file_path
from insightbot.signal_desk.models import FeedbackRecord, SavedSignal, SignalItem


ALLOWED_FEEDBACK_ACTIONS = {
    "useful",
    "not_relevant",
    "too_shallow",
    "good_for_pitch",
    "good_for_client",
    "already_known",
    "need_more_like_this",
}


def _append_jsonl(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_jsonl(path: str) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def save_signal(signal: SignalItem, tags: list[str] | None = None, notes: str = "", bot_dir: str | None = None) -> SavedSignal:
    saved = SavedSignal(
        id=f"saved_{uuid.uuid4().hex[:12]}",
        signal=signal.to_dict(),
        room_id=signal.room_id,
        tags=list(tags or signal.save_tags),
        notes=notes,
    )
    _append_jsonl(signal_desk_saved_signals_file_path(bot_dir), saved.to_dict())
    return saved


def list_saved_signals(room_id: str | None = None, bot_dir: str | None = None) -> list[dict[str, Any]]:
    items = _read_jsonl(signal_desk_saved_signals_file_path(bot_dir))
    if room_id is None:
        return items
    return [item for item in items if item.get("room_id") == room_id]


def append_feedback(signal_id: str, room_id: str, action: str, note: str = "", bot_dir: str | None = None) -> FeedbackRecord:
    if action not in ALLOWED_FEEDBACK_ACTIONS:
        raise ValueError(f"Unsupported feedback action: {action}")
    record = FeedbackRecord(
        id=f"fb_{uuid.uuid4().hex[:12]}",
        signal_id=signal_id,
        room_id=room_id,
        action=action,
        note=note,
    )
    _append_jsonl(signal_desk_feedback_file_path(bot_dir), record.to_dict())
    return record


def list_feedback(room_id: str | None = None, bot_dir: str | None = None) -> list[dict[str, Any]]:
    items = _read_jsonl(signal_desk_feedback_file_path(bot_dir))
    if room_id is None:
        return items
    return [item for item in items if item.get("room_id") == room_id]


def summarize_feedback(room_id: str, bot_dir: str | None = None) -> dict[str, int]:
    counts = Counter(item.get("action") for item in list_feedback(room_id=room_id, bot_dir=bot_dir))
    return {key: value for key, value in counts.items() if isinstance(key, str)}
```

- [ ] **Step 4: Run feedback tests**

Run:

```bash
pytest tests/test_signal_desk_feedback.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add insightbot/signal_desk/feedback.py tests/test_signal_desk_feedback.py
git commit -m "feat: add signal desk saved signals and feedback"
```

---

### Task 7: Add Minimal Streamlit Signal Desk UI Wiring

**Files:**

- Create: `scripts/ui/signal_desk/__init__.py`
- Create: `scripts/ui/signal_desk/rooms.py`
- Create: `scripts/ui/signal_desk/room_detail.py`
- Create: `scripts/ui/signal_desk/saved_signals.py`
- Modify: `scripts/app.py`

- [ ] **Step 1: Create UI package files**

Create `scripts/ui/signal_desk/__init__.py`:

```python
"""Signal Desk Streamlit UI modules."""
```

Create `scripts/ui/signal_desk/rooms.py`:

```python
from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.compiler import compile_room_to_task
from insightbot.signal_desk.models import BriefingRoom
from insightbot.signal_desk.presets import get_use_case_template, list_judgement_lenses
from insightbot.signal_desk.source_packs import list_source_packs
from insightbot.signal_desk.storage import load_rooms, save_room


def render_rooms_tab(*, bot_dir: str, channels_data: dict, save_task_definition) -> None:
    st.subheader("Signal Desk")
    st.caption("Create and manage Client Opportunity Radar briefing rooms.")

    rooms = load_rooms(bot_dir=bot_dir)
    if rooms:
        st.markdown("#### Rooms")
        for room in rooms.values():
            st.write(f"**{room.name}**")
            st.caption(f"`{room.id}` -> task `{room.compiled_task_id}`")
    else:
        st.info("No briefing rooms yet. Create the first Client Opportunity Radar room below.")

    st.markdown("#### Create Client Opportunity Radar")
    template = get_use_case_template("client_opportunity_radar")
    source_packs = list_source_packs()
    lenses = list_judgement_lenses()
    channel_ids = list(channels_data.get("channels", {}).keys())

    with st.form("signal_desk_create_room"):
        room_id = st.text_input("Room ID", value="client_radar_beauty")
        name = st.text_input("Room name", value="Beauty Client Opportunity Radar")
        topic = st.text_area("Topic", value="Beauty and retail marketing signals in China")
        focus_text = st.text_input("Focus areas", value="brand campaigns, retail activation, social content")
        selected_pack_ids = st.multiselect(
            "Source packs",
            options=[pack["id"] for pack in source_packs],
            default=template["recommended_source_pack_ids"][:1],
        )
        selected_lens_ids = st.multiselect(
            "Judgement lenses",
            options=[lens["id"] for lens in lenses],
            default=template["default_judgement_lens_ids"][:3],
        )
        selected_channels = st.multiselect("Delivery channels", options=channel_ids, default=channel_ids[:1])
        hour = st.number_input("Hour", min_value=0, max_value=23, value=int(template["default_schedule"]["hour"]))
        minute = st.number_input("Minute", min_value=0, max_value=59, value=int(template["default_schedule"]["minute"]))
        submitted = st.form_submit_button("Create room and compile task")

    if submitted:
        room = BriefingRoom(
            id=room_id.strip(),
            name=name.strip(),
            topic=topic.strip(),
            source_pack_ids=selected_pack_ids,
            editorial_preset_id=template["default_editorial_preset_id"],
            judgement_lens_ids=selected_lens_ids,
            channels=selected_channels,
            schedule={"hour": int(hour), "minute": int(minute)},
            focus_areas=[item.strip() for item in focus_text.split(",") if item.strip()],
        )
        save_room(room, bot_dir=bot_dir)
        task_id, task_def = compile_room_to_task(room)
        save_task_definition(task_id, task_def)
        st.success(f"Created room `{room.id}` and compiled task `{task_id}`.")
        st.rerun()
```

Create `scripts/ui/signal_desk/room_detail.py`:

```python
from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.signals import signal_items_from_run_result
from insightbot.task_runner import run_task


def render_room_detail(*, room, bot_dir: str, load_task_config) -> None:
    st.markdown(f"#### {room.name}")
    st.caption(f"Room `{room.id}` / task `{room.compiled_task_id}`")

    if st.button("Dry run room", key=f"dry_run_room_{room.id}"):
        with st.spinner("Running room dry run..."):
            result = run_task(
                room.compiled_task_id,
                config_loader_fn=lambda: load_task_config(room.compiled_task_id),
                dry_run=True,
            )
        st.session_state[f"signal_desk_dry_run::{room.id}"] = result

    result = st.session_state.get(f"signal_desk_dry_run::{room.id}")
    if result:
        st.markdown("##### Signal preview")
        run_id = result.get("task_id", room.compiled_task_id)
        signals = signal_items_from_run_result(room.id, run_id, result)
        if not signals:
            st.warning("No structured signals found. Review the full generated brief in the task debug tab.")
        for signal in signals:
            st.markdown(f"**{signal.what_happened}**")
            st.write(signal.why_it_matters)
            st.caption(f"Confidence: {signal.confidence}")
```

Create `scripts/ui/signal_desk/saved_signals.py`:

```python
from __future__ import annotations

import streamlit as st

from insightbot.signal_desk.feedback import list_saved_signals


def render_saved_signals_tab(*, bot_dir: str) -> None:
    st.subheader("Saved Signals")
    items = list_saved_signals(bot_dir=bot_dir)
    if not items:
        st.info("No saved signals yet.")
        return
    for item in reversed(items):
        signal = item.get("signal", {})
        st.markdown(f"**{signal.get('what_happened', 'Untitled signal')}**")
        st.caption(f"Room: `{item.get('room_id')}` | Tags: {', '.join(item.get('tags', []))}")
        st.write(signal.get("why_it_matters", ""))
```

- [ ] **Step 2: Wire tabs into `scripts/app.py`**

In the import section near existing `scripts.ui` imports, add:

```python
try:
    from scripts.ui.signal_desk.rooms import render_rooms_tab
    from scripts.ui.signal_desk.saved_signals import render_saved_signals_tab
except ModuleNotFoundError:
    from ui.signal_desk.rooms import render_rooms_tab
    from ui.signal_desk.saved_signals import render_saved_signals_tab
```

Modify the current tab declaration from:

```python
tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏠 概览", "📋 任务管理", "📡 Channels",
    "🧪 验证与调试", "📝 运行日志",
    "⚙️ 推送版式定制", "🔬 任务调试",
])
```

to:

```python
tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "🏠 概览", "📋 任务管理", "Signal Desk", "Saved Signals", "📡 Channels",
    "🧪 验证与调试", "📝 运行日志",
    "⚙️ 推送版式定制", "🔬 任务调试",
])
```

Then insert after the task management tab block and before the Channels tab block:

```python
    with tab2:
        render_rooms_tab(
            bot_dir=bot_dir,
            channels_data=channels_data,
            save_task_definition=save_task_definition,
        )

    with tab3:
        render_saved_signals_tab(bot_dir=bot_dir)
```

Renumber the later tab variable uses so the old Channels tab uses `tab4`, validation/debug uses `tab5`, logs uses `tab6`, delivery format uses `tab7`, and task debug uses `tab8`.

- [ ] **Step 3: Run import smoke check**

Run:

```bash
python -m compileall insightbot scripts
```

Expected: command completes without syntax errors.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_signal_desk_storage.py tests/test_signal_desk_presets.py tests/test_signal_desk_compiler.py tests/test_signal_desk_signals.py tests/test_signal_desk_feedback.py -v
```

Expected: PASS.

- [ ] **Step 5: Optional local UI smoke**

Run:

```bash
streamlit run scripts/app.py --server.address 127.0.0.1 --server.port 8501
```

Expected:

- app starts
- `Signal Desk` tab appears
- creating a room creates an entry in `data/signal_desk/rooms.json`
- compiled task appears in `tasks.json` with `_signal_desk_room_id`

Stop the server after checking.

- [ ] **Step 6: Commit**

Run:

```bash
git add scripts/app.py scripts/ui/signal_desk
git commit -m "feat: add signal desk streamlit tabs"
```

---

## Final Verification

- [ ] **Step 1: Run all Signal Desk focused tests**

Run:

```bash
pytest tests/test_signal_desk_storage.py tests/test_signal_desk_presets.py tests/test_signal_desk_compiler.py tests/test_signal_desk_signals.py tests/test_signal_desk_feedback.py -v
```

Expected: PASS.

- [ ] **Step 2: Run existing task/runtime regression tests**

Run:

```bash
pytest tests/test_config_paths.py tests/test_task_runner.py tests/test_task_validation.py tests/test_run_history.py -v
```

Expected: PASS.

- [ ] **Step 3: Run syntax check**

Run:

```bash
python -m compileall insightbot scripts
```

Expected: no syntax errors.

- [ ] **Step 4: Review diff**

Run:

```bash
git diff --stat
git diff -- insightbot scripts tests README.md docs
```

Expected:

- changes are limited to Signal Desk package, UI wiring, tests, paths, docs
- unrelated untracked files remain untouched
- no secrets are added

---

## Implementation Notes

- Keep dry runs safe. Do not send channels from Signal Desk dry-run UI.
- Keep room storage local-first and readable.
- Do not introduce SQLite, auth, billing, or a new frontend framework in MVP.
- Do not mutate source packs or editorial presets automatically from feedback.
- Do not rename the repo.
- Do not delete or rename existing task UI; Signal Desk wraps it.

## Self-Review

Spec coverage:

- PRD pilot use case: covered by `Client Opportunity Radar` template and compiler.
- Core output contract: covered by `SignalItem` and signal conversion.
- Downstream workflow: covered by saved signals and feedback foundations.
- Trust model: covered by source pack trust metadata and UI inspector path.
- Architecture doc boundary: product layer lives in `insightbot/signal_desk/`; runtime remains unchanged.

Placeholder scan:

- The plan avoids placeholder markers and open-ended implementation instructions.
- Each task includes concrete files, test code, commands, expected results, and minimal implementation code.

Type consistency:

- `BriefingRoom.compiled_task_id` is used by compiler and UI.
- `SignalItem` is produced by `signals.py` and consumed by feedback/UI.
- room storage uses `BriefingRoom.from_dict()` and `to_dict()`.
