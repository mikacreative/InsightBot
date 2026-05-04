# Signal Desk Product IA And Pattern Architecture

> Status: Draft  
> Date: 2026-05-04  
> Scope: Product information architecture and capability model  
> Related docs:
> - `docs/signal_desk_prd.md`
> - `docs/signal_desk_mvp_architecture.md`

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

## 5. User Flow

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

## 6. Operator Flow

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

## 7. Ownership Model

| Object | Owner | Decision maker | Failure metric |
| --- | --- | --- | --- |
| Pattern | Product / strategy owner | Product owner | Users cannot understand when to use it |
| Source pack | Editor / operator | Editor lead | Signals are stale, noisy, or biased |
| Editorial preset | Senior practitioner / editor | Product owner + domain owner | Output lacks judgement or misses relevance |
| Pipeline | Technical owner | Technical owner | Runs fail or produce unusable structure |
| Output contract | Product owner | Product owner | Results are not useful in downstream work |
| User workspace | Product owner | Product owner | Users avoid the product or ask for manual help |
| Control Center | Operator / technical owner | Technical owner | Operators cannot diagnose or maintain the system |

The most important ownership rule:

> Users own intent and feedback. Operators own machinery and reliability.

## 8. Product Implications

### 8.1 Do Not Remove Admin Capabilities

The current task, channel, validation, logs, and debug surfaces are valuable.

The problem is not that they exist.

The problem is that they are currently exposed at the same level as the user workspace.

They should move behind an operator mode.

### 8.2 Do Not Make Users Edit Raw Policies

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

### 8.3 Pattern Quality Is Product Quality

If a pattern is weak, users will blame Signal Desk, not the underlying pipeline.

Therefore each pattern needs visible and operational quality checks:

- Does it run?
- Does it produce enough candidates?
- Does it avoid stale sources?
- Does it produce cards with why-it-matters and suggested action?
- Does user feedback indicate relevance?
- Does it generate useful downstream outputs?

## 9. Recommended Next Implementation Direction

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

## 10. Open Questions

These should be resolved before UI implementation:

1. Should Control Center be visible as a tab, a sidebar section, or a separate route?
2. Should Pattern Library be visible to users, or only surfaced through "New room"?
3. Should users be able to request new source coverage from the UI?
4. Should pattern edits require a publish step before users can use them?
5. Should saved signals be global, room-specific, client-specific, or all three?

## 11. Current Recommendation

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

