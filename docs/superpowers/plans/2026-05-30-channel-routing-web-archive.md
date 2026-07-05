# Channel Routing and Web Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade InsightBot so each task can precisely define which channel route receives which delivery, while every task result can also be stored and browsed through a subscriber-facing web archive.

**Architecture:** Keep the existing `channels: ["id"]` task format working, and add a normalized route layer that also accepts rich channel route objects. Add a `web_archive` channel type that behaves like a channel in configuration but persists task reports into a local JSONL archive for online browsing and rollback.

**Tech Stack:** Python, pytest, Streamlit, JSON/JSONL local persistence.

---

### Task 1: Normalize Task Channel Routes

**Files:**
- Create: `insightbot/channel_routes.py`
- Modify: `insightbot/config.py`
- Modify: `insightbot/task_validation.py`
- Test: `tests/test_channel_routes.py`

- [ ] **Step 1: Write tests for backward-compatible route parsing**

```python
from insightbot.channel_routes import normalize_channel_routes


def test_normalize_legacy_channel_ids():
    routes = normalize_channel_routes(["wecom_main", "archive"], {"channels": {}})
    assert routes == [
        {"channel_id": "wecom_main", "enabled": True, "audience": "", "purpose": "default"},
        {"channel_id": "archive", "enabled": True, "audience": "", "purpose": "default"},
    ]
```

- [ ] **Step 2: Write tests for rich route objects**

```python
def test_normalize_rich_routes_skips_disabled_entries():
    routes = normalize_channel_routes([
        {"channel_id": "exec_chat", "audience": "management", "purpose": "summary"},
        {"channel_id": "noise", "enabled": False},
    ], {"channels": {}})
    assert routes == [
        {"channel_id": "exec_chat", "enabled": True, "audience": "management", "purpose": "summary"},
    ]
```

- [ ] **Step 3: Implement `normalize_channel_routes`**

```python
def normalize_channel_routes(raw_routes, channels_data=None):
    routes = []
    for item in raw_routes or []:
        if isinstance(item, str):
            channel_id = item.strip()
            if channel_id:
                routes.append({"channel_id": channel_id, "enabled": True, "audience": "", "purpose": "default"})
        elif isinstance(item, dict):
            channel_id = str(item.get("channel_id") or item.get("id") or "").strip()
            if channel_id and bool(item.get("enabled", True)):
                routes.append({
                    "channel_id": channel_id,
                    "enabled": True,
                    "audience": str(item.get("audience", "")).strip(),
                    "purpose": str(item.get("purpose", "default")).strip() or "default",
                })
    return routes
```

- [ ] **Step 4: Inject `_task_channel_routes` from `load_tasks_config`**

```python
routes = normalize_channel_routes(task_def.get("channels", []), load_channels(bot_dir))
config["_task_channel_routes"] = routes
config["_task_channels"] = [route["channel_id"] for route in routes]
```

- [ ] **Step 5: Validate missing channels from normalized routes**

```python
routes = normalize_channel_routes(channels, channels_data)
for route in routes:
    if route["channel_id"] not in known_channels:
        issues.append(_issue(...))
```

- [ ] **Step 6: Run route tests**

Run: `pytest tests/test_channel_routes.py tests/test_task_validation.py -q`
Expected: all tests pass.

### Task 2: Add Web Archive Persistence

**Files:**
- Modify: `insightbot/paths.py`
- Create: `insightbot/web_archive.py`
- Test: `tests/test_web_archive.py`

- [ ] **Step 1: Add archive path helper**

```python
def web_archive_file_path(bot_dir: str | None = None) -> str:
    bot_dir = bot_dir or default_bot_dir()
    return os.getenv("WEB_ARCHIVE_FILE", os.path.join(data_dir(bot_dir), "web_archive.jsonl"))
```

- [ ] **Step 2: Implement append/list/get helpers**

```python
append_archive_record(bot_dir, record)
list_archive_records(bot_dir=bot_dir, task_id="daily_brief", limit=20)
get_archive_record("record-id", bot_dir=bot_dir)
```

- [ ] **Step 3: Run archive tests**

Run: `pytest tests/test_web_archive.py tests/test_config_paths.py -q`
Expected: all tests pass.

### Task 3: Make Web Archive a Channel Type

**Files:**
- Modify: `insightbot/channels.py`
- Modify: `insightbot/task_runner.py`
- Test: `tests/test_channels.py`
- Test: `tests/test_task_runner.py`

- [ ] **Step 1: Add `WebArchiveChannel`**

```python
class WebArchiveChannel:
    def send(self, content: str) -> bool:
        return bool(content)
```

- [ ] **Step 2: Validate and build `web_archive` channel definitions**

```json
{
  "type": "web_archive",
  "name": "订阅者在线浏览",
  "public_name": "InsightBot Briefing"
}
```

- [ ] **Step 3: Persist one full archive record per task run**

```python
if channel_def["type"] == "web_archive":
    append_archive_record(None, {
        "task_id": task_id,
        "task_name": config["_task_name"],
        "channel_id": route["channel_id"],
        "audience": route["audience"],
        "purpose": route["purpose"],
        "title": title,
        "markdown": final_markdown,
        "created_at": ended_at.isoformat(),
    })
```

- [ ] **Step 4: Run channel/task-runner tests**

Run: `pytest tests/test_channels.py tests/test_task_runner.py -q`
Expected: all tests pass.

### Task 4: Add Subscriber Archive Page in Streamlit

**Files:**
- Create: `scripts/ui/web_archive.py`
- Modify: `scripts/app.py`

- [ ] **Step 1: Add an archive tab**

```python
tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([... , "🌐 订阅者页面"])
```

- [ ] **Step 2: Render archive records with task/channel filters**

```python
records = list_archive_records(bot_dir=bot_dir, limit=100)
task_filter = st.selectbox("任务", ["全部"] + sorted(task_ids))
st.markdown(record["markdown"])
```

- [ ] **Step 3: Keep operational logs separate**

The archive page shows report content and route metadata only; operational diagnosis remains in existing tabs.

### Task 5: Add Channel Route Editing UI

**Files:**
- Modify: `scripts/app.py`
- Modify: `scripts/ui/task_config.py`

- [ ] **Step 1: Replace plain multiselect with route rows**

Each row includes channel, enabled state, audience label, and purpose.

- [ ] **Step 2: Save legacy-compatible data**

If every row has default purpose and empty audience, save as `["channel_id"]`; otherwise save as rich route objects.

- [ ] **Step 3: Show a route matrix preview**

Render task → channel → audience → purpose so the operator can audit “什么任务通过什么渠道发送给谁”.

### Task 6: Documentation and Migration Notes

**Files:**
- Modify: `README.md`
- Modify: `DEPLOYMENT_GUIDE.md`
- Modify: `.env.example`

- [ ] **Step 1: Document the rich route format**

```json
"channels": [
  {"channel_id": "feishu_exec", "audience": "管理层", "purpose": "summary"},
  {"channel_id": "web_archive", "audience": "订阅者", "purpose": "archive"}
]
```

- [ ] **Step 2: Document archive storage**

Archive records are stored in `data/web_archive.jsonl` by default and can be overridden with `WEB_ARCHIVE_FILE`.

- [ ] **Step 3: Run final verification**

Run: `pytest tests/test_channel_routes.py tests/test_web_archive.py tests/test_channels.py tests/test_task_runner.py tests/test_task_validation.py -q`
Expected: all tests pass.
