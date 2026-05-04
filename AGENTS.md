# InsightBot / Signal Desk Agent Context

> Updated: 2026-05-04

## Current Product Direction

This repo is now the implementation base for **Signal Desk**, a marketing intelligence workspace built on top of the existing InsightBot runtime.

The product split is:

- `Signal Desk`: default user workspace. Users create rooms, invoke patterns, review signals, save useful material, and prepare briefs.
- `Control Center`: operator workspace. Internal users manage tasks, channels, validation, logs, delivery format, debugging, raw pipelines, and pattern operations.
- `Pattern Library`: product abstraction above source packs, editorial policy, judgement lenses, quality gates, and user intent.

The current strategic choice is **Human-first / Agent-ready / Autonomy-later**. Do not add autonomous agent behavior before the human workflow and contracts are stable.

## Current Branch And Scope

- Main working branch for this phase: `codex/signal-desk-prd-mvp`.
- Current MVP focus: product shell split, pattern contracts, room intent capture, feedback context, and clean documentation.
- Keep existing `tasks.json`, scheduler, channels, and task runner as the execution base unless a task explicitly asks to replace them.

## Important Files

- `scripts/app.py`: Streamlit app entry. Keep changes mostly to product-mode routing and wiring.
- `scripts/ui/signal_desk/product_shell.py`: product mode and tab definitions.
- `scripts/ui/signal_desk/rooms.py`: user-facing room creation and pattern invocation UI.
- `scripts/ui/signal_desk/room_detail.py`: room signal review, save, and feedback UI.
- `insightbot/signal_desk/patterns.py`: pattern, intent, and quality gate contracts.
- `insightbot/signal_desk/models.py`: room, saved signal, and feedback data models.
- `insightbot/signal_desk/storage.py`: local JSON / JSONL storage.
- `docs/signal_desk_prd.md`: product PRD.
- `docs/signal_desk_mvp_architecture.md`: MVP technical architecture.
- `docs/signal_desk_product_ia_pattern_architecture.md`: product IA and agent-ready architecture.
- `docs/superpowers/plans/2026-05-04-signal-desk-product-shell-pattern-contracts.md`: implementation plan for product shell and pattern contracts.

## Verification

Use focused checks before claiming completion:

```powershell
python -m compileall insightbot scripts
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
