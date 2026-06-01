# Runtime Config Inventory

Status: dev planning inventory  
Date: 2026-06-01  
Scope: local `dev` after syncing Tencent Cloud trusted production configs

This document records the current runtime configuration shape before restructuring. It is an inventory and cleanup plan only; it does not change runtime behavior.

## Current Runtime Files

| File | Git status | Current role | Notes |
| --- | --- | --- | --- |
| `tasks.json` | ignored | Task definitions and per-task source/section/pipeline settings | Current production truth for `Daily_brief`. |
| `channels.json` | ignored | Channel registry and delivery bindings | Current production channel points to `wecom_main`. |
| `config.content.json` | tracked today | Base runtime content config, including AI/settings and legacy source config | In practice this is environment-specific. It should become runtime-only or be replaced by a tracked example in a later cleanup. |
| `config.secrets.json` | ignored | Secrets and credentials | Must never be committed. |
| `config.local.content.json` | ignored | Local-only content override | Overlaps with runtime config and should be deprecated or archived after examples are in place. |
| `config.local.secrets.json` | ignored | Local-only secrets override | Keep local-only if still needed. |
| `config.local.example.json` | tracked | Legacy local example | Candidate to move into a clearer `config/examples/` layout. |
| `config.secrets.example.json` | tracked | Secret skeleton | Keep, but align naming with the target config layout. |
| `.env.local` | ignored | Local environment overrides | Keep local-only. |
| `.env.example` / `.env.local.example` | tracked | Environment examples | Keep, but ensure they do not duplicate JSON examples unnecessarily. |

Local production config backup before sync:

- `back-up/local-config-before-prod-sync-20260601-132827/`

Tencent Cloud trusted config source:

- `/root/back-up/insightbot-trusted-configs/latest/`

## Current Trusted Production Task

The production runtime currently uses the root-level `tasks.json` task:

| Field | Value |
| --- | --- |
| Task id | `Daily_brief` |
| Name | `营销日报` |
| Enabled | `true` |
| Schedule | `10:00` |
| Channel | `wecom_main` |
| RSS sources | `29` |
| Search provider | `baidu` |
| Search queries | `2` |
| Sections | `💡 营销行业`, `🤖 数智前沿`, `📢 政策导向` |

This production `tasks.json` is newer and more complete than the older local sample shape, so it should be treated as the current canonical runtime task config.

## How Config Is Read Today

Current entrypoints:

- `insightbot/paths.py` defines default paths for `config.content.json`, `config.secrets.json`, `tasks.json`, and `channels.json`.
- `MARKETING_BOT_DIR` can override the runtime directory.
- If `MARKETING_BOT_DIR` is unset, `default_bot_dir()` prefers `/root/marketing_bot` when it exists; otherwise it uses the repo root.
- `insightbot/config.py::load_runtime_config()` loads runtime config in this order: `CONFIG_FILE`, split content/secrets files, legacy `config.json`, then environment overrides.
- `insightbot/config.py::load_tasks()` reads `tasks.json`.
- `insightbot/config.py::load_channels()` reads `channels.json`.
- `insightbot/config.py::load_tasks_config(task_id)` merges base runtime config with a normalized task definition.
- `insightbot/scheduler.py` loads tasks from `tasks.json`; if missing, it can migrate from old single-config mode.
- `insightbot/task_runner.py` and `insightbot/editorial_pipeline.py` prefer `sources` / `sections`, with compatibility fallbacks to `feeds`.
- `scripts/app.py` reads and writes task/channel settings through the same task config layer, but some variable names and UI labels still use old `feeds` terminology.

## Canonical vs Compatibility Paths

Canonical runtime shape:

- `tasks.json.tasks.<task_id>.sources.rss`
- `tasks.json.tasks.<task_id>.sources.search`
- `tasks.json.tasks.<task_id>.sections`
- `tasks.json.tasks.<task_id>.pipeline_config`
- `channels.json.channels`
- `config.content.json.ai`
- `config.content.json.settings`
- `config.secrets.json` for credentials

Compatibility paths still present:

- `feeds` is still generated as a temporary compatibility structure.
- `config.content.json.feeds` and `config.content.json.search` still exist as legacy/base config paths.
- `CONFIG_FILE` and legacy `config.json` are still supported.
- The scheduler migration path still exists for first boot when `tasks.json` is absent.

Current risks:

- `config.content.json` is tracked, but current production content differs from Git and behaves like runtime state.
- `config.local.*` and root runtime JSON files duplicate some concerns.
- Documentation still contains mixed old/new config language.
- UI/debug code still exposes some `feeds` terminology even though `sources` / `sections` are canonical.
- Task id casing is inconsistent across old local examples and production (`daily_brief` vs `Daily_brief`).

## Recommended Target Layout

Keep root runtime paths for now, because production and code already expect them:

```text
tasks.json
channels.json
config.content.json
config.secrets.json
```

Introduce a clearer tracked example area:

```text
config/
  examples/
    tasks.example.json
    channels.example.json
    config.content.example.json
    config.secrets.example.json
  README.md
```

Target responsibilities:

- Root JSON files are runtime-only and environment-specific.
- `config/examples/` contains safe, tracked examples.
- `docs/` explains the runtime model, not environment-specific values.
- Cloud trusted snapshots remain under `/root/back-up/insightbot-trusted-configs/`.
- Local backup snapshots remain under ignored `back-up/`.

## Cleanup Phases

1. Inventory only: document the current state and avoid changing behavior.
2. Add examples: move or copy safe sample configs into `config/examples/` and update docs.
3. Make `config.content.json` runtime-only: add it to `.gitignore`, preserve a safe example, and remove tracked runtime drift.
4. Normalize task id policy: decide whether production remains `Daily_brief` or migrates to `daily_brief`, then document or implement aliases.
5. Retire legacy wording: migrate UI/debug/docs from `feeds` terminology to `sources` / `sections`.
6. Reduce compatibility paths only after production and local dev both run cleanly on canonical config.
7. Consider cloud path migration from `/root/marketing_bot` to `/home/ubuntu/...` as a separate deployment hygiene task.

## Guardrails

- Do not commit `config.secrets.json`, `.env.local`, or backup snapshots.
- Do not overwrite production runtime configs from local files without first backing up `/root/back-up/insightbot-trusted-configs/latest/`.
- Do not reset the cloud worktree without restoring trusted runtime configs afterward.
- Treat `config.content.json` as sensitive runtime drift until it is intentionally converted to an ignored runtime file with a tracked example.
- Keep formal product docs clean; cleanup logs and migration notes belong in docs like this one or in worklogs.
