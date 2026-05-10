# Signal Desk Alpha Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Client Opportunity Radar` usable as one complete Signal Desk path: create a room, refresh selected signals, save useful signals, generate a brief stub, and inspect pattern health.

**Architecture:** Keep the slice local-first and human-first. Reuse existing dry-run execution and JSONL storage; add small product-layer helpers for briefs and health rather than changing `task_runner` or the editorial pipeline. The UI should expose work-language surfaces (`Signals`, `Saved`, `Briefs`) while Control Center remains the operator surface.

**Tech Stack:** Python dataclasses/helpers, local JSONL storage, Streamlit UI modules, pytest.

---

### Task 1: Brief Artifact Contract

**Files:**
- Modify: `insightbot/paths.py`
- Modify: `insightbot/signal_desk/models.py`
- Create: `insightbot/signal_desk/briefs.py`
- Create: `tests/test_signal_desk_briefs.py`

- [x] **Step 1: Add brief storage path**

Add `signal_desk_briefs_file_path(bot_dir=None)` returning `data/signal_desk/briefs.jsonl`, with env override `SIGNAL_DESK_BRIEFS_FILE`.

- [x] **Step 2: Add `BriefArtifact` model**

Fields:

```python
id: str
room_id: str
title: str
output_intent: str
source_signal_ids: list[str]
markdown: str
created_at: str = field(default_factory=_utc_now_iso)
```

Include `to_dict()`.

- [x] **Step 3: Implement brief generation**

Create `create_brief_from_saved_signals(room, saved_signals, output_intent="client_conversation", bot_dir=None)`.

Rules:

- only use saved signals for the given room;
- include title, source count, signal bullets, why it matters, suggested action, and source links when present;
- append to `briefs.jsonl`;
- return `BriefArtifact`;
- raise `ValueError` when no saved signals exist for the room.

- [x] **Step 4: Implement listing**

Create `list_briefs(room_id=None, bot_dir=None)` and skip malformed JSONL lines.

- [x] **Step 5: Verify**

Run:

```powershell
python -m pytest tests/test_signal_desk_briefs.py tests/test_signal_desk_feedback.py -q
```

### Task 2: Pattern Health Summary

**Files:**
- Create: `insightbot/signal_desk/health.py`
- Create: `tests/test_signal_desk_health.py`

- [x] **Step 1: Define summary helper**

Create `build_pattern_health_summary(room, saved_signals, feedback_records, latest_signals=None) -> dict`.

Return:

```python
{
  "room_id": room.id,
  "pattern_id": room.use_case_template_id,
  "status": "healthy|needs_attention|no_data",
  "saved_count": int,
  "feedback_count": int,
  "latest_signal_count": int,
  "fallback_signal_count": int,
  "negative_feedback_count": int,
  "positive_feedback_count": int,
  "recommendations": list[str],
}
```

- [x] **Step 2: Rules**

Rules:

- no saved, feedback, or latest signals -> `no_data`;
- any fallback signals or negative feedback -> `needs_attention`;
- at least one saved signal and no negative/fallback warning -> `healthy`;
- recommendations should be deterministic and actionable.

- [x] **Step 3: Verify**

Run:

```powershell
python -m pytest tests/test_signal_desk_health.py -q
```

### Task 3: User Workspace Wiring

**Files:**
- Modify: `scripts/ui/signal_desk/room_detail.py`
- Create: `scripts/ui/signal_desk/signals.py`
- Create: `scripts/ui/signal_desk/briefs.py`
- Modify: `scripts/ui/signal_desk/saved_signals.py`
- Modify: `scripts/app.py`
- Create: `tests/test_signal_desk_workspace_ui.py`

- [x] **Step 1: Rename dry-run language**

In the user workspace, change primary action copy from `Dry run room` to `Refresh selected signals`. Keep the underlying `run_task(..., dry_run=True)` behavior.

- [x] **Step 2: Add `Signals` tab renderer**

Create a user-facing `render_signals_tab(bot_dir)` that summarizes rooms, saved counts, feedback counts, and pattern health. It should avoid task/channel/debug language.

- [x] **Step 3: Add `Briefs` tab renderer**

Create `render_briefs_tab(bot_dir)` that lists brief artifacts and allows creating a brief from saved signals for a selected room.

- [x] **Step 4: Improve `Saved` tab**

Keep existing saved signal list, but show it as reusable work assets and preserve room filtering.

- [x] **Step 5: Wire app tabs**

In `scripts/app.py`, route:

```text
Signal Desk tabs:
Rooms -> render_rooms_tab
Signals -> render_signals_tab
Saved -> render_saved_signals_tab
Briefs -> render_briefs_tab
```

- [x] **Step 6: Verify**

Run focused tests and Streamlit smoke:

```powershell
python -m pytest tests/test_signal_desk_workspace_ui.py tests/test_signal_desk_briefs.py tests/test_signal_desk_health.py -q
python -m compileall insightbot scripts
```

### Task 4: Documentation And Closeout

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/signal_desk_mvp_architecture.md`
- Modify: Obsidian project notes

- [x] **Step 1: Document Alpha path**

Update docs to say Alpha supports a full local path:

```text
Room -> selected signals -> saved assets -> brief stub -> pattern health summary
```

- [ ] **Step 2: Verify**

Run:

```powershell
python -m pytest tests/test_signal_desk_routing.py tests/test_signal_desk_patterns.py tests/test_signal_desk_product_shell.py tests/test_signal_desk_storage.py tests/test_signal_desk_feedback.py tests/test_signal_desk_signals.py tests/test_signal_desk_compiler.py tests/test_signal_desk_presets.py tests/test_signal_desk_briefs.py tests/test_signal_desk_health.py tests/test_signal_desk_workspace_ui.py -q
python -m compileall insightbot scripts
git diff --check
```

- [ ] **Step 3: Commit and push**

Use small commits:

```powershell
git commit -m "feat: add signal desk brief artifacts"
git commit -m "feat: add signal desk pattern health summary"
git commit -m "feat: complete signal desk alpha workspace path"
git commit -m "docs: sync signal desk alpha state"
git push
```
