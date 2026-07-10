# Signal Desk Output Contract And Brief Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Signal Desk Alpha output path so room refreshes produce reliable structured signal cards and saved signals generate work-ready briefs instead of lightweight stubs.

**Architecture:** Keep `tasks.json`, `task_runner`, channels, and scheduler as the execution base. Add product-layer normalization and quality helpers under `insightbot/signal_desk/`, then wire compact review surfaces into the existing Streamlit Signal Desk tabs. Do not add autonomous agent behavior or a new database.

**Tech Stack:** Python dataclasses/helpers, local JSONL storage, Streamlit UI modules, pytest.

---

## Product Direction Lock

Signal Desk is a live intelligence desk for marketing communications teams. The next work should improve the usefulness of the current room workflow:

```text
Room refresh
  -> structured signal cards
  -> saved work assets
  -> work-ready brief
  -> pattern health / quality review
```

Do not expand low-level task configuration in this phase. User-facing language should stay around rooms, signals, saved assets, briefs, relevance, suggested action, and source trust.

## File Structure

- Modify `insightbot/signal_desk/signals.py`: normalize structured outputs from `shortlist`, `section_assignments`, and candidate-like shapes into stable `SignalItem` cards; add output quality summary.
- Modify `tests/test_signal_desk_signals.py`: cover output shapes and fallback/quality behavior.
- Modify `insightbot/signal_desk/briefs.py`: render intent-aware work briefs from saved signals.
- Modify `tests/test_signal_desk_briefs.py`: cover brief intent sections and source evidence.
- Modify `scripts/ui/signal_desk/room_detail.py`: show structured output quality without exposing raw pipeline internals by default.
- Modify `scripts/ui/signal_desk/briefs.py`: label brief intent in work language and preview generated briefs clearly.
- Modify `docs/signal_desk_mvp_architecture.md`: mark Slice 5 as the next implementation direction once complete.

---

### Task 1: Signal Output Contract Normalization

**Files:**
- Modify: `insightbot/signal_desk/signals.py`
- Modify: `tests/test_signal_desk_signals.py`

- [ ] **Step 1: Write failing tests for section assignment output**

Add these tests to `tests/test_signal_desk_signals.py`:

```python
def test_signal_items_from_section_assignments_when_shortlist_missing():
    run_result = {
        "stage_results": {
            "section_assignments": {
                "Client Conversation Starters": [
                    {
                        "title": "Retailer launches AI shelf assistant",
                        "summary": "A retailer is using AI to support in-store recommendations.",
                        "why_it_matters": "It changes retail experience expectations.",
                        "url": "https://example.com/retail-ai",
                        "source_title": "Retail AI Report",
                    }
                ]
            }
        }
    }

    items = signal_items_from_run_result(
        room_id="client_radar_retail",
        run_id="run_assignments",
        run_result=run_result,
    )

    assert len(items) == 1
    assert items[0].what_happened == "Retailer launches AI shelf assistant"
    assert items[0].judgement_lens == ["Client Conversation Starters"]
    assert items[0].source == {
        "title": "Retail AI Report",
        "url": "https://example.com/retail-ai",
    }
```

Add this source preservation test:

```python
def test_signal_items_preserve_nested_source_metadata():
    run_result = {
        "stage_results": {
            "shortlist": [
                {
                    "title": "Brand pilots creator commerce",
                    "summary": "The campaign combines creators and store conversion.",
                    "source": {
                        "title": "Campaign Source",
                        "url": "https://example.com/creator-commerce",
                        "published_at": "2026-05-20",
                    },
                }
            ]
        }
    }

    items = signal_items_from_run_result("client_radar_brand", "run_source", run_result)

    assert items[0].source["title"] == "Campaign Source"
    assert items[0].source["url"] == "https://example.com/creator-commerce"
    assert items[0].source["published_at"] == "2026-05-20"
```

- [ ] **Step 2: Run tests to verify current gaps**

Run:

```powershell
python -m pytest tests/test_signal_desk_signals.py::test_signal_items_from_section_assignments_when_shortlist_missing tests/test_signal_desk_signals.py::test_signal_items_preserve_nested_source_metadata -q
```

Expected: fail before implementation because `section_assignments` is ignored and nested `source.title` is not normalized.

- [ ] **Step 3: Implement source metadata extraction**

In `insightbot/signal_desk/signals.py`, add:

```python
def _extract_source(candidate: dict[str, Any]) -> dict[str, str]:
    raw_source = candidate.get("source")
    source: dict[str, str] = {}
    if isinstance(raw_source, dict):
        for key in ("title", "url", "published_at"):
            value = str(raw_source.get(key) or "").strip()
            if value:
                source[key] = value

    for candidate_key, source_key in (
        ("source_title", "title"),
        ("url", "url"),
        ("source_url", "url"),
        ("published_at", "published_at"),
    ):
        value = str(candidate.get(candidate_key) or "").strip()
        if value and source_key not in source:
            source[source_key] = value
    return source
```

Then replace the inline `source` construction inside `_candidate_to_signal()` with:

```python
    source = _extract_source(candidate)
```

- [ ] **Step 4: Implement section assignment fallback before markdown fallback**

In `insightbot/signal_desk/signals.py`, add:

```python
def _signals_from_candidates(
    room_id: str,
    run_id: str,
    candidates: list[Any],
    judgement_lens: str = "",
) -> list[SignalItem]:
    structured_signals: list[SignalItem] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        normalized_candidate = dict(candidate)
        if judgement_lens and not normalized_candidate.get("judgement_lens"):
            normalized_candidate["judgement_lens"] = [judgement_lens]
        signal = _candidate_to_signal(room_id, run_id, normalized_candidate)
        if signal is not None:
            structured_signals.append(signal)
    return structured_signals
```

Update `signal_items_from_run_result()` so it tries output sources in this order:

```python
    if isinstance(shortlist, list):
        structured_signals = _signals_from_candidates(room_id, run_id, shortlist)
        if structured_signals:
            return structured_signals

    section_assignments = (
        stage_results.get("section_assignments") if isinstance(stage_results, dict) else {}
    )
    if isinstance(section_assignments, dict):
        assignment_signals: list[SignalItem] = []
        for section_name, candidates in section_assignments.items():
            if isinstance(candidates, list):
                assignment_signals.extend(
                    _signals_from_candidates(room_id, run_id, candidates, judgement_lens=str(section_name))
                )
        if assignment_signals:
            return assignment_signals
```

- [ ] **Step 5: Verify Task 1**

Run:

```powershell
python -m pytest tests/test_signal_desk_signals.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add insightbot/signal_desk/signals.py tests/test_signal_desk_signals.py
git commit -m "feat: harden signal desk output normalization"
```

---

### Task 2: Output Quality Summary

**Files:**
- Modify: `insightbot/signal_desk/signals.py`
- Modify: `tests/test_signal_desk_signals.py`
- Modify: `scripts/ui/signal_desk/room_detail.py`

- [ ] **Step 1: Write failing tests for output quality**

Add to `tests/test_signal_desk_signals.py`:

```python
def test_summarize_signal_output_quality_counts_fallback_and_missing_sources():
    structured = signal_items_from_run_result(
        "room_quality",
        "run_quality",
        {
            "stage_results": {
                "shortlist": [
                    {"title": "Signal with source", "url": "https://example.com/source"},
                    {"title": "Signal without source"},
                ]
            }
        },
    )
    fallback = signal_items_from_run_result(
        "room_quality",
        "run_fallback",
        {"stage_results": {}, "final_markdown": "## Fallback signal"},
    )

    summary = summarize_signal_output_quality(structured + fallback)

    assert summary == {
        "signal_count": 3,
        "fallback_count": 1,
        "missing_source_count": 2,
        "structured_count": 2,
        "status": "needs_attention",
        "recommendations": [
            "Review fallback cards before saving; structured shortlist was incomplete.",
            "Add or repair source metadata for signals without source URLs.",
        ],
    }
```

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
python -m pytest tests/test_signal_desk_signals.py::test_summarize_signal_output_quality_counts_fallback_and_missing_sources -q
```

Expected: fail because `summarize_signal_output_quality` does not exist.

- [ ] **Step 3: Implement quality summary helper**

Add to `insightbot/signal_desk/signals.py`:

```python
def summarize_signal_output_quality(signals: list[SignalItem]) -> dict[str, Any]:
    fallback_count = sum(
        1
        for signal in signals
        if signal.confidence.lower() == "low"
        and ("fallback" in signal.save_tags or "manual_review" in signal.judgement_lens)
    )
    missing_source_count = sum(1 for signal in signals if not signal.source.get("url"))
    structured_count = max(len(signals) - fallback_count, 0)
    recommendations: list[str] = []
    if fallback_count:
        recommendations.append("Review fallback cards before saving; structured shortlist was incomplete.")
    if missing_source_count:
        recommendations.append("Add or repair source metadata for signals without source URLs.")
    if not signals:
        recommendations.append("Refresh the room or inspect Control Center diagnostics; no signal cards were produced.")

    if not signals:
        status = "no_data"
    elif fallback_count or missing_source_count:
        status = "needs_attention"
    else:
        status = "healthy"

    return {
        "signal_count": len(signals),
        "fallback_count": fallback_count,
        "missing_source_count": missing_source_count,
        "structured_count": structured_count,
        "status": status,
        "recommendations": recommendations,
    }
```

- [ ] **Step 4: Wire compact quality copy into room detail**

In `scripts/ui/signal_desk/room_detail.py`, import the helper:

```python
from insightbot.signal_desk.signals import signal_items_from_run_result, summarize_signal_output_quality
```

After `signals = signal_items_from_run_result(...)`, add:

```python
    output_quality = summarize_signal_output_quality(signals)
    st.caption(
        f"Output quality: {output_quality['status']} | "
        f"Structured: {output_quality['structured_count']} | "
        f"Fallback: {output_quality['fallback_count']} | "
        f"Missing source: {output_quality['missing_source_count']}"
    )
```

Inside the existing `Pattern health` expander, append:

```python
        for recommendation in output_quality["recommendations"]:
            st.markdown(f"- {recommendation}")
```

- [ ] **Step 5: Verify Task 2**

Run:

```powershell
python -m pytest tests/test_signal_desk_signals.py tests/test_signal_desk_workspace_ui.py -q
python -m compileall scripts insightbot
```

Expected: all tests pass and compile succeeds.

- [ ] **Step 6: Commit**

```powershell
git add insightbot/signal_desk/signals.py tests/test_signal_desk_signals.py scripts/ui/signal_desk/room_detail.py
git commit -m "feat: show signal desk output quality"
```

---

### Task 3: Work-Ready Brief Rendering

**Files:**
- Modify: `insightbot/signal_desk/briefs.py`
- Modify: `tests/test_signal_desk_briefs.py`

- [ ] **Step 1: Write failing tests for intent-aware briefs**

Add to `tests/test_signal_desk_briefs.py`:

```python
def test_client_conversation_brief_uses_work_ready_sections(tmp_path):
    artifact = create_brief_from_saved_signals(
        make_room(),
        [make_saved_signal()],
        output_intent="client_conversation",
        bot_dir=str(tmp_path),
    )

    assert "# Beauty Client Radar - Client Conversation Brief" in artifact.markdown
    assert "## Executive takeaways" in artifact.markdown
    assert "## Client conversation starters" in artifact.markdown
    assert "## Source signals" in artifact.markdown
    assert "It affects retail conversion." in artifact.markdown
```

Add:

```python
def test_proposal_angle_brief_uses_pitch_sections(tmp_path):
    artifact = create_brief_from_saved_signals(
        make_room(),
        [make_saved_signal()],
        output_intent="proposal_angle",
        bot_dir=str(tmp_path),
    )

    assert "# Beauty Client Radar - Proposal Angle Brief" in artifact.markdown
    assert "## Pitch angles" in artifact.markdown
    assert "## Proof points" in artifact.markdown
```

- [ ] **Step 2: Run tests to verify current stub is insufficient**

Run:

```powershell
python -m pytest tests/test_signal_desk_briefs.py::test_client_conversation_brief_uses_work_ready_sections tests/test_signal_desk_briefs.py::test_proposal_angle_brief_uses_pitch_sections -q
```

Expected: fail before implementation because current brief markdown is a generic stub.

- [ ] **Step 3: Add intent labels and section map**

In `insightbot/signal_desk/briefs.py`, add:

```python
BRIEF_INTENT_LABELS = {
    "client_conversation": "Client Conversation Brief",
    "proposal_angle": "Proposal Angle Brief",
    "internal_inspiration": "Internal Inspiration Brief",
    "trend_observation": "Trend Observation Brief",
}

BRIEF_INTENT_SECTIONS = {
    "client_conversation": ["Executive takeaways", "Client conversation starters", "Recommended next actions", "Source signals"],
    "proposal_angle": ["Executive takeaways", "Pitch angles", "Proof points", "Recommended next actions", "Source signals"],
    "internal_inspiration": ["Executive takeaways", "Inspiration hooks", "Reusable references", "Source signals"],
    "trend_observation": ["Executive takeaways", "Trend observations", "Implications", "Source signals"],
}
```

- [ ] **Step 4: Render saved signals into work sections**

Replace `_render_brief_markdown(title, saved_signals)` with:

```python
def _signal_payload(item: dict) -> dict:
    signal = item.get("signal", {})
    return signal if isinstance(signal, dict) else {}


def _render_brief_markdown(title: str, saved_signals: list[dict], output_intent: str) -> str:
    intent_label = BRIEF_INTENT_LABELS.get(output_intent, "Signal Desk Brief")
    sections = BRIEF_INTENT_SECTIONS.get(output_intent, BRIEF_INTENT_SECTIONS["client_conversation"])
    heading = f"{title} - {intent_label}"
    signals = [_signal_payload(item) for item in saved_signals]

    lines = [
        f"# {heading}",
        "",
        f"Source signals: {len(signals)}",
        "",
        f"## {sections[0]}",
    ]
    for signal in signals:
        lines.append(f"- {signal.get('what_happened', '')}: {signal.get('why_it_matters', '')}")

    for section in sections[1:-1]:
        lines.extend(["", f"## {section}"])
        for signal in signals:
            action = signal.get("suggested_action") or "Review with the account or strategy lead."
            relevance = signal.get("client_relevance") or signal.get("why_it_matters", "")
            lines.append(f"- {action} {relevance}".strip())

    lines.extend(["", f"## {sections[-1]}"])
    for index, signal in enumerate(signals, start=1):
        source = signal.get("source", {})
        if not isinstance(source, dict):
            source = {}
        source_label = source.get("title") or source.get("url") or "Source not recorded"
        lines.extend(
            [
                "",
                f"### {index}. {signal.get('what_happened', '')}",
                f"- Why it matters: {signal.get('why_it_matters', '')}",
                f"- Client relevance: {signal.get('client_relevance', '')}",
                f"- Suggested action: {signal.get('suggested_action', '')}",
                f"- Source: {source_label}",
                f"- URL: {source.get('url', '')}",
            ]
        )
    return "\n".join(lines).strip() + "\n"
```

Update `create_brief_from_saved_signals()`:

```python
        markdown=_render_brief_markdown(title, room_signals, output_intent),
```

- [ ] **Step 5: Verify Task 3**

Run:

```powershell
python -m pytest tests/test_signal_desk_briefs.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add insightbot/signal_desk/briefs.py tests/test_signal_desk_briefs.py
git commit -m "feat: render work-ready signal desk briefs"
```

---

### Task 4: Briefs UI Copy And Preview

**Files:**
- Modify: `scripts/ui/signal_desk/briefs.py`
- Modify: `tests/test_signal_desk_workspace_ui.py`

- [ ] **Step 1: Write failing test for intent option labels**

Add to `tests/test_signal_desk_workspace_ui.py`:

```python
from scripts.ui.signal_desk.briefs import build_brief_intent_options


def test_build_brief_intent_options_uses_work_language():
    assert build_brief_intent_options() == [
        ("client_conversation", "Client conversation brief"),
        ("proposal_angle", "Proposal angle brief"),
        ("internal_inspiration", "Internal inspiration brief"),
        ("trend_observation", "Trend observation brief"),
    ]
```

- [ ] **Step 2: Implement intent options helper**

Add to `scripts/ui/signal_desk/briefs.py`:

```python
def build_brief_intent_options() -> list[tuple[str, str]]:
    return [
        ("client_conversation", "Client conversation brief"),
        ("proposal_angle", "Proposal angle brief"),
        ("internal_inspiration", "Internal inspiration brief"),
        ("trend_observation", "Trend observation brief"),
    ]
```

Update `render_briefs_tab()` selectbox:

```python
        intent_options = build_brief_intent_options()
        output_intent = st.selectbox(
            "Brief type",
            options=[item[0] for item in intent_options],
            format_func=dict(intent_options).get,
        )
```

- [ ] **Step 3: Improve generated brief preview labels**

In `render_briefs_tab()`, change the generated list caption to show work language:

```python
            intent_labels = dict(build_brief_intent_options())
            st.caption(
                f"Brief: `{item.get('id', '')}` | Room: `{item.get('room_id', '')}` | "
                f"Type: {intent_labels.get(item.get('output_intent', ''), item.get('output_intent', ''))} | "
                f"Created: {item.get('created_at', '')}"
            )
```

- [ ] **Step 4: Verify Task 4**

Run:

```powershell
python -m pytest tests/test_signal_desk_workspace_ui.py -q
python -m compileall scripts
```

Expected: all tests pass and compile succeeds.

- [ ] **Step 5: Commit**

```powershell
git add scripts/ui/signal_desk/briefs.py tests/test_signal_desk_workspace_ui.py
git commit -m "feat: improve signal desk brief workspace copy"
```

---

### Task 5: Documentation Closeout

**Files:**
- Modify: `docs/signal_desk_mvp_architecture.md`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update MVP architecture Slice 5**

In `docs/signal_desk_mvp_architecture.md`, under `### Slice 5: Output Contract Hardening`, add an implemented note after the deliverables once Tasks 1-4 are complete:

````markdown
Implemented Slice 5 path:

```text
Run result
  -> shortlist / section assignment normalization
  -> stable signal card contract
  -> output quality summary
  -> work-ready brief markdown
```

The product layer now prefers structured output and only falls back to markdown extraction when structured cards are unavailable.
````

- [ ] **Step 2: Update README current capability list**

Add under `### 当前新能力`:

```markdown
- **输出合同强化**：Signal cards 优先来自 structured shortlist / section assignments，并显示 fallback 与 source metadata 质量。
- **Work-ready briefs**：Saved signals 可生成按 client conversation / proposal angle / inspiration / trend observation 区分的 brief markdown。
```

- [ ] **Step 3: Update AGENTS current focus**

Change `Current MVP focus` to:

```markdown
- Current MVP focus: Signal Desk Alpha output hardening: structured signal card contract, work-ready briefs, output quality review, and clean handoff from room refresh to saved work assets.
```

- [ ] **Step 4: Final verification**

Run:

```powershell
python -m compileall insightbot scripts
python -m pytest tests/test_signal_desk_signals.py tests/test_signal_desk_briefs.py tests/test_signal_desk_workspace_ui.py -q
python -m pytest tests/test_signal_desk_routing.py tests/test_signal_desk_patterns.py tests/test_signal_desk_health.py tests/test_signal_desk_product_shell.py tests/test_signal_desk_storage.py tests/test_signal_desk_feedback.py -q
python -m pytest tests/test_channel_rendering.py tests/test_channels.py tests/test_scheduler.py tests/test_task_runner.py tests/test_run_history.py tests/test_task_validation.py -q
git diff --check
```

Expected: all commands pass.

- [ ] **Step 5: Commit**

```powershell
git add docs/signal_desk_mvp_architecture.md README.md AGENTS.md
git commit -m "docs: sync signal desk output contract state"
```

---

## Execution Order

1. Task 1 stabilizes where signal cards come from.
2. Task 2 makes output quality visible before users save weak cards.
3. Task 3 upgrades brief markdown from stub to usable internal work artifact.
4. Task 4 makes the UI language match the product job.
5. Task 5 records the new state and verification.

## Not In This Phase

- No autonomous pattern editing.
- No automatic source-pack mutation from feedback.
- No database migration.
- No new frontend framework.
- No production deployment changes.

## Plan Self-Review

- Spec coverage: covers PRD Slice 5, Product IA's user-workspace-first direction, and Agent Access default of selected structured signals.
- Red-flag scan: every task has exact tests, implementation snippets, commands, and expected outputs.
- Type consistency: uses existing `SignalItem`, `BriefArtifact`, room UI modules, and current test naming.
