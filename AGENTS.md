# InsightBot Agent Notes

This project is Mika's marketing intelligence bot. Default communication with the user is Chinese; code, commands, paths, variables, and file names stay in English.

## Current Production Shape

- Local repo: `/Users/mikawang/Documents/GitHub/InsightBot`
- Production host: `ubuntu@111.229.166.6`
- Production path: `/home/ubuntu/marketing_bot`
- Production branch: `main`
- Verify the latest production commit live before and after each deployment; do not rely on a stale recorded hash.
- Production services:
  - `insightbot-web.service` runs Streamlit on port `8501`
  - `insightbot-scheduler.service` runs the scheduler
- Production runtime files such as `tasks.json`, `channels.json`, `config.content.json`, `config.secrets.json`, and `data/` may differ from local Git state. Do not overwrite them blindly.

## Safe Deployment Pattern

Production can be deployed automatically through GitHub Actions:

- Workflow: `.github/workflows/deploy-production.yml`
- Docs: `docs/github_actions_production_deploy.md`
- The workflow must preserve runtime config files exactly like the manual deployment pattern below.
- If GitHub Environment `production` has no required reviewers, every push to `main` deploys automatically after tests pass.

Before updating Tencent Cloud production, always inspect the remote working tree:

```bash
ssh -i /Users/mikawang/.ssh/mika.pem ubuntu@111.229.166.6 \
  'sudo bash -lc "cd /home/ubuntu/marketing_bot && git branch --show-current && git rev-parse HEAD && git status --short"'
```

If production has runtime config changes, back up and restore those files around the Git update:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p /root/back-up/main-hotfix-$stamp
cd /home/ubuntu/marketing_bot
cp config.content.json /root/back-up/main-hotfix-$stamp/config.content.json
cp -f tasks.json /root/back-up/main-hotfix-$stamp/tasks.json 2>/dev/null || true
cp -f channels.json /root/back-up/main-hotfix-$stamp/channels.json 2>/dev/null || true
git fetch origin
git reset --hard origin/main
cp /root/back-up/main-hotfix-$stamp/config.content.json /home/ubuntu/marketing_bot/config.content.json
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

- Do not let AI own final Markdown, source links, source names, or section headings in `insightbot/editorial_pipeline.py`.
- Do let AI own Stage 2/3/4 editorial judgment: global shortlist, section assignment, final keep/drop, final title, and final summary.
- Stage 2 global screening should ask AI only for minimal score lines:

```text
C001 | 0.90 | reason
```

- Treat low-score lines as rejected. The production path should ignore Stage 2 items below the configured minimum score, default `0.50`.
- Stage 3 section assignment should call AI first. Use `source_section_hints` / `source_category_hint` only as fallback when AI output is missing, unparsable, or names an invalid section. AI assignment output should stay minimal:

```text
C001 | section name | reason
```

- Stage 4 should let AI decide final keep/drop and generate final title + final summary. Code should not rank, hard-gate, truncate, or backfill editorial content after AI has made the final decision:

```text
C001 | KEEP | final title | final summary | reason
C002 | DROP | - | - | reason
```

- Code must map final links from original candidate IDs, never from AI text.
- Code must render Markdown via `_render_markdown()`.
- Code must reject invalid final protocol, empty fields, overlong fields, clearly truncated titles, and generic code-fallback-like summaries. If AI repair fails, drop the item or section rather than generating fallback copy.
- Keep JSON parsers only for compatibility tests or old utilities. New production editorial pipeline paths should not depend on AI returning valid JSON.

## Editorial Validation Rules

- Treat `max_selected_items` as an upper bound only. Do not backfill a section to 5 items if AI does not keep enough candidates.
- Stage 4 code validation is a protocol and safety gate, not an editorial gate. It should not use hard-coded topic rules to override AI's final content selection.
- Do not generate fallback insights such as `title + 需关注其对...影响`. That pattern caused production summaries to repeat clipped titles and produce meaningless analysis.
- Do not truncate titles before Stage 4 final AI editing. If the final title is too long or visibly clipped, ask AI to repair; if repair fails, drop it.
- `🤖 数智前沿` should keep AI, ecommerce search, platform product changes, content platform mechanisms, and practical marketing-facing AI use cases.
- `🤖 数智前沿` should reject generic platform/business-model essays such as "users are the product" unless they include a concrete product, algorithm, search, ecommerce, or platform mechanism change.
- `🤖 数智前沿` should reject hard-tech or infrastructure-only items such as chips, quantum, trusted communication, compute, and foundational security unless they clearly land in marketing, ecommerce, content, search, or platform usage.
- `📢 政策导向` requires both a policy/action signal and business relevance. Official-source items are not enough by themselves.
- `📢 政策导向` should keep rules that affect enterprises, brands, advertising, public relations, consumer rights, data security, AI tools, platform operations, city/commercial space, or brand reputation.
- `💡 营销行业` should reject pure tech expo, robotics, hard AI infrastructure, and broad governance items unless there is an explicit marketing, brand, consumer, ecommerce, content, campaign, or platform angle.

## Known Source Health Issues

The latest production dry-runs on 2026-05-29 still showed source-layer warnings that are independent from editorial filtering:

- `https://madbrief.com/feed` fails SSL verification because of a self-signed certificate.
- Some local aggregation endpoints under `http://localhost:1200`, including `mittrchina/index` and `gov/zhengce/zuixin`, may timeout or return `503`.

Do not treat these warnings as editorial pipeline failures. Track them separately as source-health work.

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
python -m insightbot.cli --task Daily_brief --dry-run
```

Production dry run currently uses the production task id:

```bash
cd /home/ubuntu/marketing_bot
./.venv/bin/python -m insightbot.cli --task Daily_brief --dry-run
```

Both local and production currently use task id `Daily_brief`. If a task id changes, verify it from `tasks.json` before running CLI commands.

## Git Hygiene

- The working tree may contain user edits. Do not revert unrelated changes.
- Prefer a temporary worktree when merging to `main` or `dev-editorial` while the main local worktree is dirty.
- Do not commit secrets. `channels.json`, `tasks.json`, `config.secrets.json`, and production runtime data are environment-specific.
