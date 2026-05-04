# Signal Desk MVP Architecture

> Status: Draft  
> Date: 2026-05-04  
> Scope: MVP technical architecture for `Client Opportunity Radar`  
> Related PRD: `docs/signal_desk_prd.md`

## 1. Architecture Decision

Signal Desk MVP should be implemented as a product layer above the current `InsightBot` task system.

Do not replace `tasks.json`, `task_runner`, the scheduler, or the channel layer in the MVP.

The first implementation should introduce `BriefingRoom` as a higher-level product object that compiles down into an existing task definition.

Recommended first slice:

```text
BriefingRoom
  -> room config and presets
  -> compiled task definition
  -> existing task_runner
  -> editorial-intelligence pipeline bridge
  -> standard signal output
  -> saved signals and feedback
```

This keeps the working execution path intact while making the user-facing product easier to use.

## 2. Existing Runtime Baseline

The current repo already has these stable pieces:

| Layer | Current File / Object | Notes |
| --- | --- | --- |
| Task storage | `tasks.json` | Execution-level task definitions |
| Task config loader | `insightbot/config.py` | `load_tasks_config()` assembles runtime config |
| Task runner | `insightbot/task_runner.py` | Owns pipeline dispatch and channel sending |
| Run history | `insightbot/run_history.py` | JSONL run records in `data/task_runs.jsonl` |
| Paths | `insightbot/paths.py` | Centralized local file paths |
| UI shell | `scripts/app.py`, `scripts/ui/signal_desk/product_shell.py` | Streamlit product shell with `Signal Desk` and `Control Center` modes |
| Pattern contracts | `insightbot/signal_desk/patterns.py` | `PatternContract`, `IntentContract`, `QualityGateContract`, first built-in `Client Opportunity Radar` |
| Capability contracts | `editorial-intelligence/editorial_intelligence/contracts/` | Existing `BriefingGoal`, `SourceStrategy`, `EditorialPolicy`, `BriefingResult` |

There is already a bridge path for `tasks.json` tasks using `_editorial_pipeline_mode: editorial-intelligence`.

The MVP should reuse that path rather than creating a parallel execution engine.

## 3. Target Module Boundary

### 3.1 `insightbot` Product Layer Owns

- briefing room management
- use case templates
- source pack registry
- editorial preset registry
- judgement lens registry
- pattern contracts
- intent capture
- quality gate contracts
- compiling a room into a task definition
- saved signals
- feedback records
- room-level run history views
- delivery configuration
- Streamlit UI

### 3.2 `editorial-intelligence` Capability Layer Owns

- source strategy interpretation
- candidate normalization
- dedupe
- editorial shortlist
- section assignment
- final brief composition
- diagnostics

### 3.3 Do Not Move In MVP

Do not move these concerns into `editorial-intelligence`:

- scheduler
- channel delivery
- long-term room storage
- feedback storage
- Streamlit UI
- user-facing product objects

## 4. New Product Objects

### 4.1 `BriefingRoom`

Primary user-facing object for Signal Desk.

Recommended first-version fields:

```json
{
  "id": "client_radar_beauty",
  "name": "Beauty Client Opportunity Radar",
  "enabled": true,
  "use_case_template_id": "client_opportunity_radar",
  "audience": "senior account and strategy team",
  "topic": "Beauty and retail marketing signals in China",
  "focus_areas": ["brand campaigns", "retail activation", "social content", "AI marketing"],
  "client_context": {
    "clients": [],
    "categories": ["beauty", "retail"],
    "markets": ["China"]
  },
  "source_pack_ids": ["marketing_comms_cn", "beauty_retail_cn"],
  "editorial_preset_id": "client_opportunity_radar",
  "judgement_lens_ids": ["client_relevance", "pitch_potential", "case_inspiration"],
  "delivery": {
    "channels": ["wecom_main"],
    "schedule": {"hour": 8, "minute": 0}
  },
  "compiled_task_id": "room_client_radar_beauty",
  "created_at": "2026-05-04T00:00:00",
  "updated_at": "2026-05-04T00:00:00"
}
```

MVP rule:

- `BriefingRoom.id` is product-facing.
- `compiled_task_id` is execution-facing.
- one room compiles to one task.
- task edits can remain supported, but room-owned tasks should display a warning before advanced manual changes.

### 4.2 `UseCaseTemplate`

Defines setup defaults for a room.

MVP only needs one active template:

```json
{
  "id": "client_opportunity_radar",
  "name": "Client Opportunity Radar",
  "description": "Find client-relevant market signals, cases, trends, and pitchable ideas.",
  "default_editorial_preset_id": "client_opportunity_radar",
  "default_judgement_lens_ids": [
    "client_relevance",
    "pitch_potential",
    "case_inspiration",
    "strategic_implication"
  ],
  "recommended_source_pack_ids": [
    "marketing_comms_cn",
    "brand_marketing_global",
    "ai_martech"
  ],
  "default_schedule": {"hour": 8, "minute": 0}
}
```

Future templates can be added after the first pilot works.

### 4.2.1 Implemented Pattern Contracts

The current code introduces `PatternContract` as the product-level contract above source packs, editorial presets, judgement lenses, and quality gates.

Implemented contract objects:

- `PatternContract`: callable product pattern, currently seeded with `client_opportunity_radar`.
- `IntentContract`: room-level user intent captured from client, category, focus topics, downstream output intent, and time window.
- `QualityGateContract`: minimum signal standard used by the product layer before deeper agent automation exists.

Current implementation detail:

- room creation stores the intent contract under `BriefingRoom.client_context["intent"]`;
- feedback records can carry `pattern_id` and `context`;
- this gives later agent workflows enough structured context without making autonomous tuning part of MVP.

### 4.3 `SourcePack`

Curated source bundle with trust metadata.

Recommended fields:

```json
{
  "id": "marketing_comms_cn",
  "name": "China Marketing Communications",
  "description": "Chinese marketing, brand, communication, and campaign sources.",
  "coverage": "Campaign cases, agency news, marketing industry opinions, brand communication examples.",
  "limitations": "May miss closed social platform content and client-specific category news.",
  "bias": ["China-heavy", "marketing-media-heavy", "case-heavy"],
  "freshness": "daily",
  "feeds": {
    "Marketing Communications": {
      "rss": ["https://www.digitaling.com/rss # 数英网"],
      "keywords": ["营销", "品牌", "案例"],
      "prompt": "Keep client-relevant marketing communications cases and trends."
    }
  },
  "search": {
    "enabled": true,
    "queries": ["中国 营销 案例 趋势", "品牌 营销 传播 案例"]
  }
}
```

Source packs should be inspectable in the UI, but users should not need to edit them during room creation.

### 4.4 `EditorialPreset`

Maps user-facing intent into `EditorialPolicy`.

Recommended fields:

```json
{
  "id": "client_opportunity_radar",
  "name": "Client Opportunity Radar",
  "shortlist_size": 8,
  "selection_rules": [
    "Prefer signals that can support client service, proposal development, or strategic advice.",
    "Reject generic news without a clear marketing communications implication.",
    "Prefer cases, category movement, platform changes, consumer behavior shifts, and brand actions."
  ],
  "section_rules": {
    "Client Conversation Starters": "Signals that can be raised with a current client.",
    "Pitchable Ideas": "Signals that can become proposal angles or service ideas.",
    "Case Inspiration": "Campaigns, formats, mechanics, or examples worth saving.",
    "Watchouts": "Risks, category changes, or competitor pressure."
  },
  "dedupe_rules": [
    "Merge multiple reports about the same event into one signal."
  ],
  "tone": "senior, concise, judgement-led",
  "citation_style": "inline",
  "quality_checks": [
    "Each item must include why it matters.",
    "Each item must include a suggested action.",
    "Each item must cite its source."
  ]
}
```

MVP implementation can store this as product-layer preset data and compile it into `pipeline_config` / `editorial_policy`.

### 4.5 `JudgementLens`

Professional reasoning lens used to classify and explain why a signal was selected.

Recommended initial registry:

| ID | Label | Core Question |
| --- | --- | --- |
| `market_movement` | Market Movement | What changed, and is the change meaningful? |
| `client_relevance` | Client Relevance | Which current clients may care, and why? |
| `pitch_potential` | Pitch Potential | Can this become a proposal angle, service idea, or BD hook? |
| `case_inspiration` | Case Inspiration | Does this provide a useful case, format, mechanic, or proof point? |
| `strategic_implication` | Strategic Implication | What larger pattern or business implication does this suggest? |
| `risk_watchout` | Risk / Watchout | Does this create a risk, blind spot, or competitor pressure? |

In MVP, lenses can be compiled into editorial policy prompts and section rules.

They do not need a separate model in `editorial-intelligence` yet.

### 4.6 `SignalItem`

Standard output object for a selected signal.

Recommended shape:

```json
{
  "id": "sig_20260504_001",
  "room_id": "client_radar_beauty",
  "run_id": "2026-05-04T08:00:00",
  "what_happened": "",
  "why_it_matters": "",
  "client_relevance": "",
  "suggested_action": "",
  "judgement_lens": ["client_relevance", "pitch_potential"],
  "source": {
    "title": "",
    "url": "",
    "published_at": ""
  },
  "confidence": "medium",
  "save_tags": ["pitch", "client-service", "case"],
  "raw_candidate_ref": ""
}
```

MVP can derive signal items from `BriefingResult.shortlist`, `section_assignments`, or structured stage results.

If the pipeline cannot yet return fully structured fields, the first implementation can parse or compose a structured display layer from known result fields, but the architecture target should be structured `SignalItem` output.

### 4.7 `SavedSignal`

Represents a reusable work asset.

Recommended fields:

```json
{
  "id": "saved_20260504_001",
  "signal_id": "sig_20260504_001",
  "room_id": "client_radar_beauty",
  "status": "saved",
  "tags": ["pitch", "beauty", "client-service"],
  "notes": "",
  "created_at": "2026-05-04T08:30:00"
}
```

### 4.8 `FeedbackRecord`

Lightweight user reaction.

Recommended fields:

```json
{
  "id": "fb_20260504_001",
  "signal_id": "sig_20260504_001",
  "room_id": "client_radar_beauty",
  "action": "good_for_pitch",
  "note": "",
  "created_at": "2026-05-04T08:31:00"
}
```

Allowed MVP actions:

- `useful`
- `not_relevant`
- `too_shallow`
- `good_for_pitch`
- `good_for_client`
- `already_known`
- `need_more_like_this`

## 5. Storage Design

### 5.1 MVP Storage Choice

Use local JSON / JSONL files under `data/`.

Do not introduce a database in the first MVP.

Reason:

- current repo already uses JSON and JSONL storage
- single-team internal usage does not require multi-user transactions
- simpler migration from current config model
- easier to inspect and recover manually

### 5.2 Recommended Paths

Add path helpers in `insightbot/paths.py` later:

| Object | Path |
| --- | --- |
| Rooms | `data/signal_desk/rooms.json` |
| Source packs | `data/signal_desk/source_packs.json` or bundled defaults in code |
| Editorial presets | `data/signal_desk/editorial_presets.json` or bundled defaults in code |
| Saved signals | `data/signal_desk/saved_signals.jsonl` |
| Feedback | `data/signal_desk/feedback.jsonl` |

Recommended split:

- bundled defaults in code for source packs and presets
- local JSON overrides later if needed
- user-created rooms in `data/signal_desk/rooms.json`
- append-only JSONL for saved signals and feedback

### 5.3 Why Not Store Rooms Only In `tasks.json`

`tasks.json` is an execution config.

It does not express:

- user-facing room intent
- source pack IDs
- editorial preset ID
- judgement lenses
- saved signal behavior
- trust metadata

Rooms should compile into tasks, but should not be reduced to tasks as the source of truth.

## 6. Compilation Model

### 6.1 Room To Task

`BriefingRoom` compiles into a task definition compatible with existing `load_tasks_config()`.

Example compiled task:

```json
{
  "name": "Beauty Client Opportunity Radar",
  "enabled": true,
  "pipeline": "editorial",
  "_editorial_pipeline_mode": "editorial-intelligence",
  "_signal_desk_room_id": "client_radar_beauty",
  "feeds": {},
  "search": {},
  "pipeline_config": {},
  "channels": ["wecom_main"],
  "schedule": {"hour": 8, "minute": 0}
}
```

Compilation steps:

1. Load room.
2. Load selected source packs.
3. Merge source pack feeds by section/category.
4. Merge source pack search queries.
5. Load editorial preset.
6. Add judgement lens instructions to editorial policy.
7. Write or update `tasks.json[compiled_task_id]`.
8. Mark task changed so dry run is recommended.

### 6.2 Merge Rules

Source pack merge rules:

- sections with the same name are merged
- RSS entries are deduped by URL before comment text
- keywords are deduped case-insensitively
- prompts are concatenated only if they differ
- search queries are deduped case-insensitively
- room-level exclusions override source pack defaults

Editorial preset merge rules:

- use one preset as base
- append judgement lens rules
- append room focus areas and exclusions
- room-level overrides win over preset defaults

### 6.3 Advanced Task Edits

If a compiled task is manually edited in the existing task UI, there are two options:

1. MVP conservative option: warn that manual task edits may be overwritten when the room is recompiled.
2. Later option: detect task drift and offer to sync changes back into the room.

Use option 1 for MVP.

## 7. Execution Flow

### 7.1 Room Creation Flow

```text
User opens Signal Desk
  -> Create Briefing Room
  -> choose Client Opportunity Radar
  -> enter topic / category / client context
  -> choose source packs
  -> choose editorial preset and lenses
  -> choose delivery channel and schedule
  -> preview compiled task
  -> run dry run
  -> enable room
```

### 7.2 Dry Run Flow

```text
Room dry run
  -> ensure compiled task exists
  -> call run_task(task_id, dry_run=True)
  -> receive final_markdown and stage_results
  -> render standard signal preview
  -> show source and trust metadata
  -> allow save / feedback actions locally
```

### 7.3 Scheduled Run Flow

```text
Scheduler triggers compiled task
  -> task_runner runs editorial pipeline
  -> task_runner records run history
  -> task_runner sends brief to configured channels
  -> Signal Desk UI reads task run history by compiled_task_id
```

### 7.4 Saved Signal Flow

```text
User clicks Save
  -> create SavedSignal JSONL record
  -> preserve source, room_id, run_id, tags, notes
  -> show in room library
```

### 7.5 Feedback Flow

```text
User clicks feedback action
  -> append FeedbackRecord JSONL
  -> aggregate by room and action
  -> show operator-facing tuning hints
```

MVP should not automatically mutate source packs or editorial presets from feedback.

## 8. UI Architecture

### 8.1 Product Shape

MVP should remain a Web app inside the current Streamlit shell.

Enterprise WeChat / Feishu should remain delivery and reminder channels.

Do not build mini program or native app for MVP.

### 8.2 Recommended Streamlit IA

Add a new top-level tab or page group:

```text
Signal Desk
  - Rooms
  - Signals
  - Saved
  - Briefs

Control Center
  - Overview
  - Signal Desk
  - Saved Signals
  - Task Management
  - Channels
  - Validation & Debug
  - Logs
  - Delivery Format
  - Task Debug
```

Because `scripts/app.py` is already large, implementation should prefer new UI modules:

```text
scripts/ui/signal_desk/
  product_shell.py
  rooms.py
  room_detail.py
  saved_signals.py
  source_packs.py
```

Keep `scripts/app.py` changes limited to imports, tab creation, and wiring.

### 8.3 MVP Screens

Required MVP screens:

1. Room list
2. Create room form
3. Room detail
4. Dry run preview with standard signal cards
5. Saved signals list
6. Source pack / preset read-only inspector

Advanced task configuration can remain in the existing task management tab.

## 9. Code Module Plan

Recommended new modules:

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
```

Responsibilities:

| Module | Responsibility |
| --- | --- |
| `models.py` | Dataclasses / typed dicts for room, saved signal, feedback |
| `storage.py` | JSON / JSONL load-save helpers |
| `presets.py` | Bundled use case templates, editorial presets, judgement lenses |
| `source_packs.py` | Bundled source packs and merge helpers |
| `compiler.py` | Room to task compilation |
| `signals.py` | Convert run result into `SignalItem` display objects |
| `feedback.py` | Append and aggregate feedback records |

Keep all new product-layer logic under `insightbot/signal_desk/`.

Do not spread room logic into `task_runner.py` or `editorial-intelligence`.

## 10. Data Contracts

### 10.1 Room File

`data/signal_desk/rooms.json`

```json
{
  "rooms": {
    "client_radar_beauty": {
      "id": "client_radar_beauty",
      "name": "Beauty Client Opportunity Radar",
      "enabled": true,
      "use_case_template_id": "client_opportunity_radar",
      "compiled_task_id": "room_client_radar_beauty"
    }
  }
}
```

### 10.2 Saved Signals File

`data/signal_desk/saved_signals.jsonl`

One JSON object per line.

### 10.3 Feedback File

`data/signal_desk/feedback.jsonl`

One JSON object per line.

### 10.4 Task Metadata

Compiled task should include:

```json
{
  "_signal_desk_room_id": "client_radar_beauty",
  "_signal_desk_compiled": true,
  "_editorial_pipeline_mode": "editorial-intelligence"
}
```

This lets existing task views identify room-owned tasks.

## 11. Trust And Diagnostics

MVP should show trust at three levels:

### 11.1 Source Pack Trust

Show:

- coverage
- limitations
- bias
- freshness

### 11.2 Signal Trust

Show:

- source title and URL
- confidence
- evidence note if available
- judgement lens

### 11.3 Run Diagnostics

Reuse existing `stage_results` and `diagnostics` where available.

At minimum, show:

- candidate count
- selected count
- source failures if available
- whether search supplement was used
- weak result warning if selected count is low

## 12. Implementation Slices

### Slice 1: Product-Layer Foundations

Goal: create room/preset/source pack objects without UI complexity.

Deliverables:

- `insightbot/signal_desk/` package
- room storage helpers
- bundled `Client Opportunity Radar` template
- bundled editorial preset and judgement lenses
- bundled source pack examples
- room-to-task compiler
- unit tests for compilation

### Slice 2: Streamlit Room Creation

Goal: create a room and compile it into a runnable task.

Deliverables:

- room list
- create room form
- source pack selector
- preset / lens selector
- compile-to-task action
- room-owned task warning in task UI if needed

### Slice 3: Dry Run Signal Preview

Goal: run a room and view output in Signal Desk terms.

Deliverables:

- dry run button from room detail
- conversion from run result to signal cards
- trust metadata display
- weak-result diagnostics

### Slice 4: Saved Signals And Feedback

Goal: turn brief items into reusable assets.

Deliverables:

- save signal action
- feedback action buttons
- saved signal list
- feedback summary by room

### Slice 5: Output Contract Hardening

Goal: reduce reliance on parsing final markdown.

Deliverables:

- structured `SignalItem` output from pipeline where possible
- map `BriefingResult.shortlist` and `section_assignments` into signal cards
- tests for standard output fields

## 13. Verification Plan

Doc-only verification:

- Markdown file exists and is linked from README.
- headings are coherent.

Implementation verification later:

- unit tests for room storage
- unit tests for source pack merge rules
- unit tests for room-to-task compilation
- dry run from compiled room task
- Streamlit smoke test for room creation
- no real channel send during dry run

## 14. Open Technical Questions

- Should bundled source packs live in Python modules first, or JSON defaults under `insightbot/signal_desk/defaults/`?
- Should saved signals store a copy of the full signal item, or only a reference to run output plus user metadata?
- How much structure can the current editorial pipeline return without changing prompt behavior?
- Should room-owned task edits be blocked, warned, or allowed with drift detection?
- Should room history read from `task_runs.jsonl` only, or maintain a room-level summary cache?

## 15. Current Recommendation

Start implementation with Slice 1.

Do not change the execution engine first.

The safest first technical move is:

```text
insightbot/signal_desk compiler + defaults + storage
```

Then wire a small Streamlit room creation UI on top.

This gives Signal Desk a real product model while preserving the current working `InsightBot` runtime.
