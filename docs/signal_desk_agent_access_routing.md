# Signal Desk Agent Access Routing

> Status: Draft  
> Date: 2026-05-11  
> Scope: Contract for future Skill, API, and UI entrypoints

## 1. Decision

Signal Desk should expose an agent-ready routing contract before it exposes an autonomous agent.

The immediate goal is not:

- autonomous monitoring
- automatic pattern editing
- automatic publishing
- a full REST API surface

The immediate goal is:

```text
natural language or structured request
  -> Signal Desk route
  -> pattern_id + time_window + output_intent + result_mode
  -> existing room / pattern / task execution path
```

This follows the AIHOT lesson: make the agent entrypoint a deterministic product router, not a vague summarization prompt.

## 2. Default Routing Principle

Default route:

```text
selected signals
```

Raw information and finished briefs are opt-in.

| User intent | Result mode |
| --- | --- |
| Broad request: "what should I know for this client?" | `selected_signals` |
| Explicit raw/full request: "show all raw signals" | `raw_feed` |
| Explicit brief request: "make a client brief" | `brief_output` |

This keeps the user workspace focused on curated signal value, while leaving full operational detail in Control Center.

## 3. Route Contract

The route object should resolve these fields:

```json
{
  "pattern_id": "client_opportunity_radar",
  "time_window": "last_7_days",
  "output_intent": "client_conversation",
  "result_mode": "selected_signals",
  "room_id": "",
  "confidence": "rule_based",
  "warnings": []
}
```

Default values:

| Field | Default |
| --- | --- |
| `pattern_id` | `client_opportunity_radar` |
| `time_window` | `last_7_days` |
| `output_intent` | `client_conversation` |
| `result_mode` | `selected_signals` |

Structured parameters take priority over natural language. Natural language only fills missing fields.

## 4. Result Modes

### 4.1 `selected_signals`

Default mode.

Use when the user asks broad questions such as:

- "what should I know for this client?"
- "recent category opportunities"
- "anything worth raising with the account team?"

This should map to Signal Desk signal cards, not raw run output.

### 4.2 `raw_feed`

Use only when the user explicitly asks for:

- all
- full
- raw
- source feed
- 全部
- 全量
- 原始

In the current MVP, `raw_feed` should mean available run-stage material such as candidates, source payloads, diagnostics, or `stage_results`. It should not promise a complete original RSS archive unless that storage exists.

### 4.3 `brief_output`

Use only when the user explicitly asks for:

- brief
- client brief
- proposal brief
- 简报
- 日报

This should map to a downstream brief surface, not to the raw signal stream.

## 5. Output Intents

| User language | `output_intent` |
| --- | --- |
| client conversation, talk to client, 客户沟通 | `client_conversation` |
| proposal, pitch, 提案, 销售角度 | `proposal_angle` |
| inspiration, case, 案例, 灵感 | `internal_inspiration` |
| trend, 趋势, 观察 | `trend_observation` |

## 6. Time Windows

| User language | `time_window` |
| --- | --- |
| week, 7 days, 一周, 7天 | `last_7_days` |
| 14 days, two weeks, 两周, 14天 | `last_14_days` |
| 30 days, past month, last month, 30天 | `last_30_days` |

The routing layer should stay deterministic in MVP. LLM-based pattern selection can be added later after the contract is stable.

## 7. Relationship To `IntentContract`

`IntentContract` remains the persisted room invocation intent.

`SignalDeskRoute` is an access-request route.

Do not store `result_mode` inside `IntentContract` in the MVP. A room can have a stable intent, while a single access request can ask for selected signals, raw material, or a brief.

## 8. Future Skill Shape

A future `signal-desk` skill should call the routing contract before it calls any execution surface.

Examples:

```text
"Look for recent pitch ideas for a beauty retail client"
-> pattern_id=client_opportunity_radar
-> result_mode=selected_signals
-> output_intent=proposal_angle
```

```text
"Show me all raw signals from the last month"
-> result_mode=raw_feed
-> time_window=last_30_days
```

```text
"Make a client brief for this room"
-> result_mode=brief_output
```

This keeps Skill behavior explainable and testable.
