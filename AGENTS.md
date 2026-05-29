# InsightBot Agent Notes

This project is Mika's marketing intelligence bot. Default communication with the user is Chinese; code, commands, paths, variables, and file names stay in English.

## Current Production Shape

- Local repo: `/Users/mikawang/Documents/GitHub/InsightBot`
- Production host: `ubuntu@111.229.166.6`
- Production path: `/root/marketing_bot`
- Production branch: `main`
- Production services:
  - `insightbot-web.service` runs Streamlit on port `8501`
  - `insightbot-scheduler.service` runs the scheduler
- Production runtime files such as `tasks.json`, `channels.json`, `config.content.json`, `config.secrets.json`, and `data/` may differ from local Git state. Do not overwrite them blindly.

## Safe Deployment Pattern

Before updating Tencent Cloud production, always inspect the remote working tree:

```bash
ssh -i /Users/mikawang/.ssh/mika.pem ubuntu@111.229.166.6 \
  'sudo bash -lc "cd /root/marketing_bot && git branch --show-current && git rev-parse HEAD && git status --short"'
```

If production has runtime config changes, back up and restore those files around the Git update:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p /root/back-up/main-hotfix-$stamp
cd /root/marketing_bot
cp config.content.json /root/back-up/main-hotfix-$stamp/config.content.json
cp -f tasks.json /root/back-up/main-hotfix-$stamp/tasks.json 2>/dev/null || true
cp -f channels.json /root/back-up/main-hotfix-$stamp/channels.json 2>/dev/null || true
git fetch origin
git reset --hard origin/main
cp /root/back-up/main-hotfix-$stamp/config.content.json /root/marketing_bot/config.content.json
systemctl restart insightbot-web.service
systemctl restart insightbot-scheduler.service
```

After deployment, verify:

```bash
systemctl is-active insightbot-web.service
systemctl is-active insightbot-scheduler.service
curl -I -s http://127.0.0.1:8501 | head -n 5
```

## Frontend Incident: 2026-05-19

### What Happened

The production Streamlit console failed when running RSS health checks:

```text
UnboundLocalError: cannot access local variable 'active_task_name' where it is not associated with a value
```

The code referenced `active_task_name` in the No Push Diagnosis block before assigning it later in the same tab body. It only surfaced on the RSS health path because that branch executed the diagnosis block before the later assignment.

### How To Avoid It

- In `scripts/app.py`, define cross-section display variables immediately after task selection/state loading, before any conditional tab branches use them.
- Do not introduce variables inside a lower UI block if an earlier conditional block may also need them.
- For Streamlit tabs, test the exact affected workflow, not just page load. For this incident, page load was not enough; the path was `验证与调试 -> 立即刷新健康度 -> No Push Diagnosis`.
- After frontend changes, run at least:

```bash
PYTHONPATH=. streamlit run scripts/app.py --server.headless true --server.port 8502
```

Then use browser automation or the in-app browser to check the relevant tab and button path.

## Channel Delivery Incident: 2026-05-19

### What Happened

The WeCom production push still showed clipped content after channel-aware rendering was added. The task configuration was not the primary cause. The real issue was that `wecom` chunking used Python character length, while Chinese Markdown delivery is constrained closer to UTF-8 byte size. A message that looked safe by character count could exceed the WeCom payload budget and get truncated by the channel.

### How To Avoid It

- For WeCom Markdown, budget chunks by `len(content.encode("utf-8"))`, not `len(content)`.
- Reserve bytes for continuation hints such as `(2/2)` before packing chunks.
- Keep tests that assert byte size, not only character count:

```python
assert len(message.content.encode("utf-8")) <= WECOM_SOFT_LIMIT_BYTES
```

- When validating a real Chinese brief, inspect both character length and byte length. A 1,700 character Chinese brief can already be around 3,600 bytes before headers.
- If a production push is clipped mid-sentence, check delivery rendering first, then task config. Do not assume the pipeline generated a broken final brief until the sent payload sizes are known.

## Editorial AI Output Contract

- Do not let AI own final Markdown, source links, source names, section headings, or candidate titles in `insightbot/editorial_pipeline.py`.
- Stage 2 global screening should ask AI only for minimal score lines:

```text
C001 | 0.90 | reason
```

- Stage 3 section assignment should first use `source_section_hints` / `source_category_hint`; call AI only for candidates without a reliable source hint. AI assignment output should stay minimal:

```text
C001 | section name | reason
```

- Stage 4 should rank candidates in code and generate Markdown via `_render_markdown()`. AI may only rewrite summaries:

```text
C001 | rewritten summary
```

- Keep JSON parsers only for compatibility tests or old utilities. New production editorial pipeline paths should not depend on AI returning valid JSON.

## Local Verification Commands

Focused tests for channel delivery and task runner:

```bash
pytest -q tests/test_channel_rendering.py tests/test_channels.py tests/test_task_runner.py
```

Compile check after touching app or core modules:

```bash
python -m compileall insightbot scripts
```

Local console:

```bash
PYTHONPATH=. streamlit run scripts/app.py --server.headless true --server.port 8502
```

Local dry run:

```bash
python -m insightbot.cli --task daily_brief --dry-run
```

Production dry run currently uses the production task id:

```bash
cd /root/marketing_bot
./.venv/bin/python -m insightbot.cli --task Daily_brief --dry-run
```

The local task id is usually `daily_brief`; production still has `Daily_brief`. This naming drift is not currently fatal, but it is a cleanup candidate.

## Git Hygiene

- The working tree may contain user edits. Do not revert unrelated changes.
- Prefer a temporary worktree when merging to `main` or `dev-editorial` while the main local worktree is dirty.
- Do not commit secrets. `channels.json`, `tasks.json`, `config.secrets.json`, and production runtime data are environment-specific.
