# InsightBot Project Rules

InsightBot is Mika's marketing intelligence bot. Use Chinese for working communication; keep code, commands, paths, variables, and filenames in English.

## Source of truth

- Product and usage entrypoint: `README.md`.
- Local verification: `LOCAL_TESTING_GUIDE.md`.
- Deployment operations: `DEPLOYMENT_GUIDE.md` and `docs/github_actions_production_deploy.md`.
- Editorial architecture and contracts: `docs/editorial_pipeline_design.md`, `docs/editorial_briefing_skill_contract.md`, and code/tests under `insightbot/` and `tests/`.
- Do not store dated incidents, source-health snapshots, recorded commit hashes, or changing task configuration in this file.

## Production boundary

- Production runs from `/home/ubuntu/marketing_bot` on branch `main`; verify the live branch, commit, working tree, services, and health before and after deployment.
- `tasks.json`, `channels.json`, `config.content.json`, `config.secrets.json`, and `data/` are environment-specific runtime state. Never overwrite them blindly from Git.
- Follow the existing deployment guide and workflow. A production deployment or external change requires Mika's explicit approval.
- Public product access should use the shared gateway on `80/443`; application services bind locally and support the configured path prefix. Direct Streamlit ports are not the finished product surface.
- Validate gateway routing, static assets, redirects, downloads, WebSockets, refresh, and exposed health/config endpoints before calling a gateway cutover complete.

## Durable implementation contracts

- In Streamlit UI code, initialize state and cross-section variables before any conditional branch that uses them; test the exact affected interaction, not page load alone.
- Budget WeCom Markdown chunks by UTF-8 bytes, including continuation markers. Tests must assert byte limits.
- AI owns Stage 2/3/4 editorial judgment: shortlist, section assignment, keep/drop, title, and summary.
- Code owns protocol validation, candidate-ID-to-source mapping, links, section headings, and final Markdown rendering.
- Do not hard-code editorial backfill, ranking, generic fallback insights, or silent title truncation after AI judgment. Repair invalid output; if repair fails, drop the item or section.
- Treat configured item counts as upper bounds. Editorial category policy belongs in task configuration and the editorial contract, not in this file.

## Local verification

Run the checks relevant to the changed path:

```bash
pytest -q tests/test_channel_rendering.py tests/test_channels.py tests/test_task_runner.py
python -m compileall insightbot scripts
PYTHONPATH=. streamlit run scripts/app.py --server.headless true --server.port 8502
python -m insightbot.cli --task Daily_brief --dry-run
```

Verify the active task id from `tasks.json`; do not rely on a recorded value in documentation.

## Git and secrets

- Preserve unrelated user changes in a dirty working tree.
- Use a separate worktree for merge work when the primary worktree is dirty.
- Never commit runtime configuration, credentials, or production data.
