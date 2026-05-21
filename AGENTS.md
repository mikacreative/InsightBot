# InsightBot / Signal Desk Agent Context

> Updated: 2026-05-21

## Current Product Direction

This repo is now the implementation base for **Signal Desk**, a marketing intelligence workspace built on top of the existing InsightBot runtime.

The product split is:

- `Signal Desk`: default user workspace. Users create rooms, invoke patterns, review signals, save useful material, and prepare briefs.
- `Control Center`: operator workspace. Internal users manage tasks, channels, validation, logs, delivery format, debugging, raw pipelines, and pattern operations.
- `Pattern Library`: product abstraction above source packs, editorial policy, judgement lenses, quality gates, and user intent.

The current strategic choice is **Human-first / Agent-ready / Autonomy-later**. Do not add autonomous agent behavior before the human workflow and contracts are stable.

## Current Branch And Scope

- Main working branch for this phase: `codex/signal-desk-main-sync`, syncing `codex/signal-desk-prd-mvp` with latest `origin/main`.
- Current MVP focus: Signal Desk Alpha vertical slice: room refresh, selected signals, saved work assets, brief stub, pattern health, Agent Access routing, and clean documentation.
- Keep existing `tasks.json`, scheduler, channels, and task runner as the execution base unless a task explicitly asks to replace them.

## Current Production Shape

- Production branch: `main`.
- Production host: `ubuntu@111.229.166.6`.
- Production path: `/root/marketing_bot`.
- Production services:
  - `insightbot-web.service` runs Streamlit on port `8501`.
  - `insightbot-scheduler.service` runs the scheduler.
- Production runtime files such as `tasks.json`, `channels.json`, `config.content.json`, `config.secrets.json`, and `data/` may differ from local Git state. Do not overwrite them blindly.

## Important Files

- `scripts/app.py`: Streamlit app entry. Keep changes mostly to product-mode routing and wiring.
- `scripts/ui/signal_desk/product_shell.py`: product mode and tab definitions.
- `scripts/ui/signal_desk/rooms.py`: user-facing room creation and pattern invocation UI.
- `scripts/ui/signal_desk/room_detail.py`: room signal review, save, and feedback UI.
- `insightbot/signal_desk/patterns.py`: pattern, intent, and quality gate contracts.
- `insightbot/signal_desk/routing.py`: rule-based Agent Access request routing for future Skill/API/UI entrypoints.
- `insightbot/signal_desk/briefs.py`: brief artifact generation and local JSONL persistence.
- `insightbot/signal_desk/health.py`: pattern health summary from saved signals, feedback, and latest signal cards.
- `insightbot/signal_desk/models.py`: room, saved signal, and feedback data models.
- `insightbot/signal_desk/storage.py`: local JSON / JSONL storage.
- `docs/signal_desk_prd.md`: product PRD.
- `docs/signal_desk_mvp_architecture.md`: MVP technical architecture.
- `docs/signal_desk_product_ia_pattern_architecture.md`: product IA and agent-ready architecture.
- `docs/signal_desk_agent_access_routing.md`: routing semantics for future Skill/API/Web entrypoints.
- `docs/superpowers/plans/2026-05-04-signal-desk-product-shell-pattern-contracts.md`: implementation plan for product shell and pattern contracts.
- `docs/superpowers/plans/2026-05-11-signal-desk-agent-access-routing.md`: implementation plan for Agent Access routing.
- `docs/superpowers/plans/2026-05-11-signal-desk-alpha-vertical-slice.md`: implementation plan for the Alpha end-to-end path.

## Verification

Use focused checks before claiming completion:

```powershell
python -m compileall insightbot scripts
python -m pytest tests/test_signal_desk_routing.py tests/test_signal_desk_patterns.py -q
python -m pytest tests/test_signal_desk_briefs.py tests/test_signal_desk_health.py tests/test_signal_desk_workspace_ui.py -q
python -m pytest tests/test_signal_desk_patterns.py tests/test_signal_desk_product_shell.py tests/test_signal_desk_storage.py tests/test_signal_desk_feedback.py
python -m pytest tests/test_task_config_schema.py tests/test_task_state.py tests/test_task_runner.py tests/test_run_history.py tests/test_signal_desk_storage.py tests/test_signal_desk_feedback.py
git diff --check
```

Streamlit smoke can be done with `streamlit.testing.v1.AppTest` or by opening the local app when a server is running.

## Local Hygiene

- Do not touch or delete pre-existing untracked duplicate files unless explicitly asked:
  - `AGENTS 2.md`
  - `editorial-intelligence/editorial_intelligence/contracts/source_strategy 2.py`
  - `editorial-intelligence/examples/insightbot_integration 2.py`
  - `editorial-intelligence/tests/test_insightbot_bridge 2.py`
  - `insightbot/wecom_callback 2.py`
- Do not send real channel messages during tests. Use dry-run paths.
- Treat `tasks.json`, `channels.json`, `.env.local`, and secret config files as local runtime state.

## Production Incident Learnings

- In `scripts/app.py`, define cross-section display variables immediately after task selection/state loading, before any conditional tab branches use them. A production Streamlit RSS health path failed on 2026-05-19 because `active_task_name` was referenced before assignment.
- For WeCom Markdown, budget chunks by `len(content.encode("utf-8"))`, not `len(content)`. Chinese Markdown can exceed the WeCom payload budget by byte size even when character count looks safe.
- When validating channel delivery, inspect the rendered payload before assuming the pipeline generated a broken final brief.
