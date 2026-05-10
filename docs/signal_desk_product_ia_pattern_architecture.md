# Signal Desk Product IA And Pattern Architecture

> Status: Draft  
> Date: 2026-05-04  
> Scope: Product information architecture and capability model  
> Related docs:
> - `docs/signal_desk_prd.md`
> - `docs/signal_desk_mvp_architecture.md`
> - `docs/signal_desk_agent_access_routing.md`

## 1. Decision

Signal Desk should be split into two product-facing surfaces:

| Surface | Audience | Core job |
| --- | --- | --- |
| User Workspace | Agency practitioners, consultants, account leads, strategy leads | Invoke intelligence patterns, review signals, save useful materials, generate work-ready outputs |
| Control Center | Operators, editors, product owners, technical maintainers | Manage patterns, source packs, pipelines, quality gates, runs, channels, and diagnostics |

The current Streamlit app is closer to a Control Center.

It should not be treated as the final user-facing Signal Desk experience.

The next product step should be an IA refactor:

```text
Current state:
User sees tasks, channels, validation, logs, delivery, debug, and Signal Desk together.

Target state:
User sees Signal Desk workspace by default.
Operators can enter Control Center when they need to manage the machinery.
```

## 2. Product Logic

Signal Desk should not ask users to configure intelligence machinery.

The user should call a professional capability.

The operator should manage the machinery that makes the capability reliable.

```text
User asks:
"What should I know for this client / category / pitch?"

System invokes:
Pattern -> source pack -> pipeline -> editorial policy -> quality gate -> output contract

User receives:
signals, saved references, briefing notes, proposal angles, client conversation starters
```

This separates user intent from operational configuration.

## 3. Core Abstraction: Pattern

`Pattern` is the decisive product abstraction.

A pattern is a productized unit of professional judgement.

It is not only a prompt.
It is not only a task.
It is not only a pipeline.

It packages a repeatable agency intelligence job:

| Pattern element | Meaning |
| --- | --- |
| User job | What the practitioner wants to accomplish |
| Input context | What the user must provide |
| Source strategy | Where the system should look |
| Editorial policy | What counts as signal vs noise |
| Judgement lenses | How the system interprets relevance |
| Pipeline contract | How raw information becomes output |
| Output contract | What the user receives |
| Quality gate | What makes the result trustworthy |
| Feedback loop | How the pattern improves over time |

Example:

```text
Pattern: Client Opportunity Radar

User job:
Find client-relevant market signals, cases, trends, and pitchable ideas.

User input:
client / category / focus topics / output intent

System-owned machinery:
marketing source packs, search queries, editorial shortlist, client relevance lens,
pitch potential lens, case inspiration lens, signal-card output, feedback tracking

User output:
ranked signal cards, saved references, client conversation starters, pitch angles
```

## 4. Three-Layer Architecture

### 4.1 User Workspace

User Workspace is the default product surface.

It should expose only user-relevant objects:

- rooms
- patterns
- signals
- saved signals
- briefs
- exports
- light feedback

It should avoid exposing:

- raw `tasks.json`
- channel implementation
- RSS editing
- validation diagnostics
- pipeline config
- debug logs
- run internals

Recommended IA:

```text
Signal Desk
├─ Rooms
│  ├─ room overview
│  ├─ run now / refresh
│  └─ subscription status
├─ Signals
│  ├─ latest signals
│  ├─ filters by room / pattern / client / topic
│  └─ feedback actions
├─ Saved
│  ├─ saved signals
│  ├─ saved cases
│  └─ saved pitch angles
└─ Briefs
   ├─ client conversation brief
   ├─ proposal angle brief
   └─ internal share brief
```

User-facing language should be work-language, not system-language.

| System word | User-facing word |
| --- | --- |
| task | room / subscription / run |
| dry run | refresh / run now / preview |
| query | focus topic |
| RSS | source coverage |
| editorial policy | judgement standard |
| pipeline validation | readiness |
| debug log | issue detail |
| channel | delivery destination |

### 4.2 Pattern Library

Pattern Library is the bridge between product and capability.

It contains reusable intelligence jobs.

Initial pattern candidates:

| Pattern | User job |
| --- | --- |
| Client Opportunity Radar | Find signals that can support current clients, pitches, and service ideas |
| Competitor Movement Watch | Track competitor or peer brand movement |
| Category Trend Scan | Understand what is changing in a category |
| Campaign Case Finder | Collect campaign, activation, content, and retail examples |
| Pitch Angle Generator | Turn signals into proposal-ready angles |
| Risk / Watchout Monitor | Detect category pressure, platform shifts, or reputation risks |

Each pattern should define:

- required user inputs
- optional user inputs
- default source packs
- default editorial preset
- default judgement lenses
- output types
- quality gate
- operator owner

Patterns should be callable by users but maintained by operators.

### 4.3 Control Center

Control Center is the operational surface.

It should manage the capability supply chain:

```text
Control Center
├─ Pattern Manager
│  ├─ pattern definitions
│  ├─ default source packs
│  ├─ default judgement lenses
│  └─ output contracts
├─ Source Pack Manager
│  ├─ RSS / search / manual sources
│  ├─ source coverage
│  ├─ limitations and bias
│  └─ freshness checks
├─ Pipeline Manager
│  ├─ pipeline health
│  ├─ run history
│  ├─ validation
│  └─ fallback behavior
├─ Delivery Manager
│  ├─ channels
│  ├─ schedules
│  └─ permissions
└─ Diagnostics
   ├─ logs
   ├─ failed runs
   ├─ source failures
   └─ quality warnings
```

The current `tasks`, `channels`, `validation`, `logs`, and `debug` surfaces belong here.

They should remain available, but not as the default user product.

## 5. Agent-Ready Product Architecture

Signal Desk does not need a strong autonomous agent in the first product phase.

But it should be designed as an agent-ready system from the beginning.

The key principle:

> AI can be implemented later, but the contracts that make AI possible should not be delayed.

If agent responsibilities are ignored in early design, the human-facing layers will absorb too much complexity.

Common failure pattern:

```text
No agent-ready contracts
-> users/operators must manually understand pattern, source, policy, validation, logs, and feedback
-> UI grows more forms, tabs, filters, and diagnostics
-> later agent can only sit on top as a fragile assistant
```

Target pattern:

```text
Human UI stays thin.
Structured contracts carry product logic.
Agent can later read, evaluate, draft, and propose changes.
```

### 5.1 Human Layers vs Agent Automation Layers

The three human product layers remain:

```text
User Workspace
Pattern Library
Control Center
```

Agent automation should be modeled as another set of internal layers:

```text
Context Layer
Memory Layer
Evaluation Layer
Orchestration Layer
Permission Layer
Learning Layer
```

| Agent layer | What it owns | Early implementation requirement |
| --- | --- | --- |
| Context Layer | User intent, client, category, pattern, time window, output intent | Store structured intent when a pattern is invoked |
| Memory Layer | Saved signals, repeated interests, client/category history, source usefulness | Keep saved signals and feedback event data structured |
| Evaluation Layer | Quality checks, missing fields, stale sources, fallback ratio, relevance signals | Define machine-readable quality gates |
| Orchestration Layer | Pattern selection, source pack selection, pipeline selection, retries, fallback path | Keep pattern definitions separate from UI state |
| Permission Layer | What can be automated vs what needs approval | Use draft -> validate -> approve -> publish boundaries |
| Learning Layer | Pattern/source/output improvement suggestions from feedback and usage | Log feedback as semantic events, not only button counts |

These layers do not all need UI in the first version.

They should shape the object model and data contracts.

### 5.2 AI-Later, Agent-Ready

The recommended near-term stance is:

```text
Do not build an autonomous agent now.
Build objects and workflows that an agent can safely operate later.
```

The first implementation of this stance is the Agent Access routing contract:

```text
natural language or structured request
  -> SignalDeskRoute
  -> pattern_id + time_window + output_intent + result_mode
```

Default routing should return curated `selected_signals`. `raw_feed` and `brief_output` require explicit user intent. This keeps the user workspace simple while allowing future Skill/API entrypoints to share the same product semantics.

This means early implementation can still be human-first:

- users invoke rooms and patterns manually
- operators manage sources and patterns manually
- admins inspect run health manually

But these actions should create structured objects that an agent can later read.

Minimum agent-ready contracts:

| Contract | Why it matters |
| --- | --- |
| Intent Contract | Captures why a user invoked a pattern |
| Pattern Contract | Defines a reusable professional judgement unit |
| Quality Gate Contract | Lets system or agent evaluate whether output is acceptable |
| Feedback Event Contract | Turns user reaction into learning data |
| Draft / Publish Contract | Lets agent propose changes without mutating live product |

### 5.3 Intent Contract

Every user invocation should persist a structured intent.

Example:

```json
{
  "pattern_id": "client_opportunity_radar",
  "room_id": "beauty_client_radar",
  "client": "Sephora",
  "category": "beauty retail",
  "focus_topics": ["AI retail", "social commerce", "campaign cases"],
  "output_intent": "client_conversation",
  "time_window": "last_7_days"
}
```

Without this, future agents cannot know why a result was generated or how to evaluate relevance.

### 5.4 Pattern Contract

Patterns should be stored as versioned contracts, not only rendered UI forms.

Example:

```json
{
  "id": "client_opportunity_radar",
  "version": "0.1.0",
  "user_job": "Find client-relevant market signals, cases, trends, and pitchable ideas.",
  "required_context": ["client", "category", "focus_topics", "output_intent"],
  "default_source_pack_ids": ["marketing_comms_cn", "brand_marketing_global"],
  "default_judgement_lens_ids": ["client_relevance", "pitch_potential", "case_inspiration"],
  "default_output_contract_ids": ["signal_cards", "client_conversation_brief"],
  "quality_gate_id": "client_opportunity_radar_basic_quality",
  "status": "published"
}
```

This lets a future agent:

- review whether a pattern is underspecified
- propose a new version
- compare pattern performance across versions
- draft changes without editing the live pattern

### 5.5 Quality Gate Contract

Quality gates should be machine-readable.

Example:

```json
{
  "id": "client_opportunity_radar_basic_quality",
  "requires_source": true,
  "requires_why_it_matters": true,
  "requires_suggested_action": true,
  "requires_client_relevance": true,
  "max_fallback_ratio": 0.2,
  "min_signal_count": 3,
  "max_duplicate_ratio": 0.25
}
```

This prevents quality from becoming only a visual warning in Control Center.

It also allows an agent to later say:

```text
This run failed quality because 60% of cards were markdown fallback and 3 cards lacked suggested action.
```

### 5.6 Feedback Event Contract

Feedback should be recorded as semantic events.

Example:

```json
{
  "signal_id": "sig_123",
  "room_id": "beauty_client_radar",
  "pattern_id": "client_opportunity_radar",
  "action": "too_shallow",
  "context": {
    "client": "Sephora",
    "category": "beauty retail",
    "output_intent": "client_conversation"
  }
}
```

This supports future pattern health review:

```text
Client Opportunity Radar for beauty retail is repeatedly marked too_shallow.
Suggested fix: tighten client relevance lens and add category-specific source packs.
```

### 5.7 Draft / Publish Contract

High-impact system changes should not directly edit live objects.

Recommended lifecycle:

```text
draft -> validate -> approve -> publish
```

This is important even before an agent exists.

It keeps human operation disciplined and gives future agents a safe action model:

```text
Agent can draft.
System can validate.
Human approves publish.
```

Agent should not directly publish:

- new patterns
- core editorial policy changes
- source pack deletion
- channel or delivery changes
- major output contract changes

## 6. Agent Stewardship Model

The long-term agent role should be a Pattern Steward Assistant.

It should not start as a fully autonomous system.

Recommended maturity stages:

| Stage | Agent role | Allowed behavior |
| --- | --- | --- |
| L1 Agent Assist | Suggest and explain | Read system state, summarize health, diagnose issues, draft recommendations |
| L2 Agent Steward | Monitor and draft | Periodically review patterns/sources/runs, draft changes, request approval |
| L3 Semi-Automation | Apply approved low-risk changes | Apply approved drafts, run validation, keep audit trail |
| L4 Autonomous Operations | Manage selected low-risk loops | Only for narrow, reversible maintenance tasks |

Near-term target:

```text
L1.5 Pattern Steward Assistant
```

It can:

- review pattern health
- summarize user feedback
- detect stale or noisy source packs
- identify missing output fields
- explain failed runs
- propose source/policy/pattern changes
- draft a new pattern from repeated user needs

It cannot:

- publish new patterns without approval
- delete sources
- change delivery channels
- overwrite editorial policy
- send outputs to users or teams without the configured permission model

### 6.1 Pattern Health Review

Recommended first agent-assisted feature:

```text
Pattern Health Review
```

Inputs:

- pattern contract
- recent run history
- recent signal cards
- saved signals
- feedback events
- source pack health
- validation results

Output:

```text
Pattern: Client Opportunity Radar
Status: Needs attention

Evidence:
- 5 recent runs
- 42 generated signals
- 3 saved
- 11 marked too_shallow
- 2 source packs stale

Diagnosis:
- source coverage is too generic
- client relevance lens is under-specified
- too many fallback cards

Suggested draft changes:
1. Add beauty retail source pack
2. Tighten pitch_potential lens
3. Require suggested_action and client_relevance in every card
```

This delivers immediate value without requiring autonomous control.

### 6.2 Product Risk If AI Is Deferred Without Contracts

If AI is weakened in early implementation and no agent-ready contracts are built, these risks increase:

| Risk | Symptom |
| --- | --- |
| UI bloat | More tabs, filters, forms, diagnostics, and explainers appear in human-facing layers |
| Operator burden | Operators must manually inspect every source, pattern, run, and feedback trend |
| Weak future agent integration | Agent can only read screens or markdown instead of structured objects |
| Harder refactor | Later automation requires extracting contracts from UI state and legacy config |
| Poor learning loop | Saved signals and feedback cannot be mapped back to pattern/context/source decisions |

Therefore:

> AI capability can be postponed. Agent interfaces should not be postponed.

## 7. User Flow

Target user flow:

```text
1. Choose a pattern
2. Add context
3. Run now or subscribe
4. Review signal cards
5. Save useful signals
6. Generate a work-ready output
```

Example:

```text
Pattern:
Client Opportunity Radar

Context:
Client = Sephora
Category = beauty retail
Focus = AI retail, social commerce, campaign cases
Output intent = client conversation

Result:
- 8 signal cards
- 3 client conversation starters
- 2 pitchable angles
- 5 saved case references
```

The user should not need to know which RSS feed, search provider, query schema, or pipeline config made this happen.

## 8. Operator Flow

Target operator flow:

```text
1. Create or edit a pattern
2. Attach source packs
3. Attach editorial preset
4. Define output contract
5. Run validation
6. Publish pattern to user workspace
7. Monitor health and feedback
```

Example:

```text
Operator updates Client Opportunity Radar:
- adds a beauty retail source pack
- changes shortlist size from 8 to 10
- adds "retail conversion impact" as a judgement lens
- validates source freshness
- republishes the pattern
```

Users only see the improved pattern.

## 9. Ownership Model

| Object | Owner | Decision maker | Failure metric |
| --- | --- | --- | --- |
| Pattern | Product / strategy owner | Product owner | Users cannot understand when to use it |
| Source pack | Editor / operator | Editor lead | Signals are stale, noisy, or biased |
| Editorial preset | Senior practitioner / editor | Product owner + domain owner | Output lacks judgement or misses relevance |
| Pipeline | Technical owner | Technical owner | Runs fail or produce unusable structure |
| Output contract | Product owner | Product owner | Results are not useful in downstream work |
| User workspace | Product owner | Product owner | Users avoid the product or ask for manual help |
| Control Center | Operator / technical owner | Technical owner | Operators cannot diagnose or maintain the system |
| Agent-ready contracts | Product / technical owner | Product owner | Future automation requires expensive refactor |
| Pattern Steward Assistant | Product / operator owner | Product owner | Agent suggestions are noisy, risky, or unactionable |

The most important ownership rule:

> Users own intent and feedback. Operators own machinery and reliability.

The additional agent rule:

> Agent can propose, diagnose, draft, and validate. Humans own standards, publish decisions, and business accountability.

## 10. Product Implications

### 10.1 Do Not Remove Admin Capabilities

The current task, channel, validation, logs, and debug surfaces are valuable.

The problem is not that they exist.

The problem is that they are currently exposed at the same level as the user workspace.

They should move behind an operator mode.

### 10.2 Do Not Make Users Edit Raw Policies

Users can adjust:

- client
- category
- topic
- output intent
- frequency
- saved items
- feedback

Users should not adjust:

- raw RSS
- prompt internals
- pipeline config
- validation schema
- channel credentials

If advanced customization is needed, expose it as a request:

```text
"This room needs more China beauty retail sources."
```

Then an operator updates the underlying source pack.

### 10.3 Pattern Quality Is Product Quality

If a pattern is weak, users will blame Signal Desk, not the underlying pipeline.

Therefore each pattern needs visible and operational quality checks:

- Does it run?
- Does it produce enough candidates?
- Does it avoid stale sources?
- Does it produce cards with why-it-matters and suggested action?
- Does user feedback indicate relevance?
- Does it generate useful downstream outputs?

### 10.4 Do Not Let Human UI Absorb Agent Responsibilities

If early implementation weakens AI, the product should still avoid making users or operators manually perform agent-like work.

Do not add human UI for every internal reasoning step.

Prefer structured contracts plus compact review surfaces.

Bad pattern:

```text
Add more forms so users can configure every source, query, lens, and rule.
```

Better pattern:

```text
Keep source, lens, and policy as structured contracts.
Expose only high-level choices to users.
Expose compact validation and review to operators.
Let future agent read the same contracts.
```

## 11. Recommended Next Implementation Direction

The next implementation should not add more task configuration.

It should create a clearer product split:

```text
Phase 1:
Add product mode switch:
- Signal Desk
- Control Center

Phase 2:
Make Signal Desk the default landing page.

Phase 3:
Move current operational tabs under Control Center.

Phase 4:
Add Pattern Library as a product object above BriefingRoom.

Phase 5:
Replace room creation form with pattern invocation wizard.

Phase 6:
Add agent-ready contracts for intent, pattern versioning, quality gates, feedback events, and draft/publish.

Phase 7:
Add Pattern Health Review as the first Pattern Steward Assistant feature.
```

Recommended first UI target:

```text
Default landing:
Signal Desk / Rooms

Primary CTA:
New intelligence room

Creation flow:
Choose pattern -> add context -> confirm -> create

Secondary access:
Control Center
```

## 12. Open Questions

These should be resolved before UI implementation:

1. Should Control Center be visible as a tab, a sidebar section, or a separate route?
2. Should Pattern Library be visible to users, or only surfaced through "New room"?
3. Should users be able to request new source coverage from the UI?
4. Should pattern edits require a publish step before users can use them?
5. Should saved signals be global, room-specific, client-specific, or all three?
6. What is the minimum intent contract for a room invocation?
7. Which quality gates should be mandatory for every pattern?
8. Which operator actions can an agent draft but not publish?
9. Should Pattern Health Review run manually, on a schedule, or both?
10. How should agent recommendations be audited and accepted/rejected?

## 13. Current Recommendation

Use a two-mode product shell:

```text
Default:
Signal Desk user workspace

Secondary:
Control Center for operators
```

Do not delete the existing admin capabilities.

Move them into the right layer.

Then make `Pattern` the primary bridge between user intent and operational pipeline.

Build the next UI and object model as:

```text
Human-first
Agent-ready
Autonomy-later
```

Do not overbuild autonomous agents now.

Do not build UI in a way that makes future agents impossible.
