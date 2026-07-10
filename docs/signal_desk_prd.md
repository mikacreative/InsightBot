# Signal Desk PRD

> Status: Draft  
> Date: 2026-05-04  
> Scope: Product direction for the current InsightBot repo  
> Product name: Signal Desk  
> Existing codebase name: InsightBot  
> Capability layer: Editorial Intelligence Skill System  

## 1. Decision

Signal Desk should be implemented in the current `InsightBot` repo for the next phase.

The current repo already contains the working product shell:

- multi-task configuration
- channels and delivery
- internal scheduler
- Streamlit operations console
- dry run and diagnostics surfaces
- current editorial pipeline
- the new `editorial-intelligence` capability package

Creating a new repo now would mostly duplicate the product shell and increase migration cost before the product shape is validated.

The recommended naming split is:

| Layer | Name | Responsibility |
| --- | --- | --- |
| Product name | Signal Desk | User-facing internal intelligence workspace |
| Current repo / legacy shell | InsightBot | Existing codebase, scheduler, channels, console, task runner |
| Capability layer | Editorial Intelligence Skill System | Source strategy, editorial policy, briefing workflow, diagnostics |
| Core skill | `editorial-briefing` | One complete intelligence brief production run |

The repo can be renamed later only after Signal Desk becomes the stable product direction.

## 2. Product Premise

Signal Desk is an internal live intelligence desk for marketing communications teams.

It helps a single user or small team continuously monitor industry signals, filter noise with editorial judgement, and turn selected signals into useful briefs for management, client service, pitch preparation, trend observation, and campaign inspiration.

It should not be positioned as a generic news bot.

It should also not require users to understand RSS, search syntax, prompt engineering, or policy JSON before receiving value.

The first internal use case should focus on helping senior marketing communications practitioners respond faster to client and market needs.

The product should help them see:

- industry trends and dynamic changes
- useful campaign and brand cases
- weak signals that may affect current clients
- ideas that can become client conversation starters
- angles that can be turned into proposals or sellable services

## 3. Target Users

### Primary Users

- Agency GM or business lead who needs a high-signal overview of market movement.
- Strategy lead who needs trend signals, campaign examples, and client-relevant interpretation.
- Account lead who needs client opportunity radar and timely conversation starters.
- BD or pitch team who needs inspiration, references, and market context.

### Secondary Users

- Internal editor or operator who maintains source packs and output standards.
- Technical owner who manages deployment, channels, and integrations.

## 4. Pilot Use Case

The first MVP pilot should be:

### Client Opportunity Radar

This name is acceptable if it is defined broadly enough.

It should not mean only sales leads or obvious new-business opportunities.

In Signal Desk, `Client Opportunity Radar` means:

> A briefing room that helps senior agency practitioners quickly identify market signals, trends, cases, and category movement that can be used in client service, strategic advice, proposal development, campaign ideation, or new service packaging.

### Primary Reader

Senior agency practitioners:

- GM
- strategy lead
- senior account lead
- BD / pitch lead
- senior consultant

### Primary Job

The reader wants to answer:

- What changed in the market that I should know?
- Which signals may matter to my current clients?
- Which cases or examples can help explain a point?
- Is there anything we can proactively suggest to a client?
- Can this become a pitch angle, proposal module, or sellable idea?

### Minimum Useful Output

A useful radar output should contain fewer but stronger items.

Each item should be able to support at least one of these actions:

- start a client conversation
- enrich a proposal
- inspire a campaign idea
- support a strategic point of view
- warn the team about category or competitor movement
- become a saved reference for future client work

## 5. Core Problem

The current product is useful but still feels like a configurable technical tool.

Users need to understand or maintain:

- RSS feeds
- search supplements
- task configuration
- prompt behavior
- editorial policy
- delivery channels
- dry run diagnostics

This creates a high setup burden for ordinary team users.

The product should move from:

```text
Task -> Feeds -> Pipeline -> Channels
```

to:

```text
Signal Desk -> Briefing Room -> Use Case Template -> Source Pack -> Editorial Preset -> Feedback Loop -> Delivery
```

The product experience should start from the user's job and intended use, not from data-source configuration.

## 6. Product Positioning

Signal Desk is a live intelligence desk, not a static notebook.

Notebook-style products help users understand a known set of materials.

Signal Desk helps users monitor a changing external environment and decide what matters.

| Dimension | Notebook-style research product | Signal Desk |
| --- | --- | --- |
| Input | User-provided documents | Live sources, search, platform signals, source packs |
| Material state | Mostly static | Continuously changing |
| Main action | Understand and summarize | Discover, filter, judge, brief, remember |
| User intent | Learn from a source set | Monitor and act on business-relevant signals |
| Output | Notes, answers, summaries | Daily briefs, weekly briefs, opportunity radar, pitch inspiration |
| Product unit | Notebook | Briefing room / signal desk |

## 7. Key Product Objects

### 7.1 Signal Desk

The top-level product workspace.

For the current internal phase, one company/team can operate one Signal Desk.

### 7.2 Briefing Room

A persistent intelligence space for one topic, client, category, or use case.

Examples:

- `AI Agent Product Watch`
- `Beauty Retail Weekly`
- `Nike Sports Marketing Radar`
- `Luxury Campaign Inspiration`
- `China Social Content Trends`

A briefing room owns:

- goal
- audience
- use case template
- source packs
- editorial preset
- delivery settings
- feedback profile
- saved signals
- run history

### 7.3 Use Case Template

A user-facing starting point that hides configuration complexity.

Initial templates:

| Template | Purpose |
| --- | --- |
| `Industry Daily Brief` | Daily high-signal industry scan |
| `Client Opportunity Radar` | Detect client-relevant market signals, trends, cases, and pitchable opportunities |
| `Competitor Watch` | Track competitor, peer, or category movement |
| `Pitch Inspiration Pack` | Collect campaign references and proposal material |
| `Trend Signal Weekly` | Weekly synthesis of weak signals and emerging patterns |

### 7.4 Source Pack

A curated source bundle.

Users should select interests and industries; the system should translate those choices into source packs.

Initial source pack categories:

- marketing communications
- brand marketing
- social and content trends
- AI and martech
- retail and consumer
- China business media
- global creative and campaign references
- category-specific packs such as beauty, sports, luxury, FMCG, F&B

Source packs may include:

- RSS feeds
- search queries
- fallback sources
- source weights
- exclusions
- language constraints

Source packs should also expose trust metadata:

- `coverage`: what this pack covers and what it does not cover
- `bias`: likely source bias, such as tech-heavy, award-heavy, business-media-heavy, China-heavy, or global-heavy
- `freshness`: whether the pack is suitable for daily, weekly, or occasional monitoring

This matters because hiding source setup should not hide source limitations.

### 7.5 Editorial Preset

A user-facing editing style mapped to an internal editorial policy.

Initial presets:

| Preset | Intent |
| --- | --- |
| `Executive Brief` | Few items, high judgement, management-level relevance |
| `Account Brief` | Client conversation starters and service opportunities |
| `Strategy Brief` | Trends, why-it-matters, category implications |
| `Creative Inspiration` | Campaign cases, content formats, creative references |
| `Pitch Radar` | Signals that can become proposal angles or BD hooks |

Internally, each preset maps to:

- shortlist size
- selection rules
- section rules
- dedupe rules
- tone
- citation style
- quality checks

### 7.6 Professional Judgement Lens

An editorial preset should not only define style.

It should also define the reasoning lens used to judge signals.

Initial judgement lenses:

| Lens | Core Question |
| --- | --- |
| `Market Movement` | What changed, and is the change meaningful? |
| `Client Relevance` | Which current clients may care, and why? |
| `Pitch Potential` | Can this become a proposal angle, service idea, or BD hook? |
| `Case Inspiration` | Does this provide a useful example, format, mechanic, or proof point? |
| `Strategic Implication` | What larger pattern or business implication does this suggest? |
| `Risk / Watchout` | Does this create a risk, blind spot, or competitor pressure? |

Each generated signal should be evaluated through one or more lenses.

### 7.7 Feedback Profile

The product should make editorial policy optimization feel like lightweight feedback, not configuration editing.

Initial feedback actions:

- `Useful`
- `Not relevant`
- `Too shallow`
- `Good for pitch`
- `Good for client`
- `Already known`
- `Need more like this`

The system should aggregate feedback into room-level and team-level preferences.

For the MVP, feedback should not be treated as fully automatic learning.

It should first produce human-readable tuning suggestions for the operator.

## 8. Core Output Contract

A Signal Desk item should not be a simple news summary.

Each selected signal should follow a standard structure:

| Field | Meaning |
| --- | --- |
| `what_happened` | The factual event, trend, case, or signal |
| `why_it_matters` | Why a senior marketing communications practitioner should care |
| `client_relevance` | Which client/category/business situation it may apply to |
| `suggested_action` | What the team can do with it next |
| `judgement_lens` | Which professional lens selected this item |
| `source` | Source title and URL or citation |
| `confidence` | High / medium / low confidence based on source quality and evidence density |
| `save_tags` | Suggested tags such as pitch, client-service, trend, case, competitor, category |

Recommended item format:

```text
What happened:
Why it matters:
Client relevance:
Suggested action:
Source:
Confidence:
```

The product should optimize for fewer, sharper, more usable signals rather than long lists.

## 9. Downstream Workflow

Signal Desk should connect brief items to real agency work.

Initial downstream actions:

- `Save to room library`
- `Mark for client follow-up`
- `Use for pitch`
- `Add to weekly report`
- `Track this topic`
- `Find more like this`
- `Dismiss topic/source`

Future export paths:

- Obsidian project note
- client memo
- pitch inspiration library
- weekly internal report
- slide outline
- Notion or Google Docs workspace

The MVP does not need to implement every export path.

But the product model should treat saved signals as reusable work assets, not disposable news items.

## 10. Trust Model

Professional users will not trust the output only because it is fluent.

Signal Desk needs visible trust signals:

- source citation for every selected item
- source pack coverage and limitations
- source pack bias notes
- freshness window
- confidence level
- evidence density, such as whether multiple sources mention the same signal
- rejection / filtering diagnostics where available

When a brief is weak, the system should explain the likely reason:

- source coverage is too narrow
- sources are stale
- the topic is too broad
- editorial preset is too strict
- too many items are duplicates
- search supplement is needed

Trust does not require showing every technical detail.

It requires showing enough evidence for a senior user to decide whether the signal is worth using.

## 11. MVP Scope

The MVP should focus on making one internal team able to create and use briefing rooms without touching low-level configuration.

### In Scope

- Product naming and IA update to Signal Desk.
- Briefing room creation flow.
- `Client Opportunity Radar` as the first pilot template.
- Source pack selection from predefined packs.
- Editorial preset selection.
- professional judgement lens selection or preset mapping.
- Mapping templates and presets into current task configuration.
- Dry run preview before enabling delivery.
- Basic feedback buttons on generated items.
- Room-level run history and saved outputs.
- standard signal output contract.
- basic trust metadata for source packs.

### Out of Scope

- Multi-tenant SaaS billing.
- Public user management.
- Complex team permission models.
- Fully autonomous source discovery.
- Social platform scraping beyond explicit adapters.
- Replacing the current scheduler and channel layer.
- Renaming the repository.

## 12. UX Principles

### 12.1 Preset First

Users should start with a template and a goal.

They should not start with feed URLs.

### 12.2 Configuration Is Progressive

The default path should work with 5 decisions:

1. Who is this for?
2. What topic or client does it monitor?
3. What use case is it for?
4. What industries or categories matter?
5. How often should it brief the team?

Advanced users can still inspect and adjust source packs and editorial policy later.

### 12.3 Feedback Beats Prompt Editing

Ordinary users should tune results by reacting to brief items.

Prompt or policy editing should remain an advanced operator function.

### 12.4 Explain Why

Each selected signal should explain why it matters.

When a room produces weak results, the system should explain whether the issue is source coverage, freshness, relevance, or editorial filtering.

## 13. Architecture Implications

### 13.1 Keep Current Repo

The current repo should remain the implementation home because it already contains the product shell.

The next implementation should add product-level abstractions above the current task model rather than replacing it immediately.

### 13.2 Add Product Models Above Tasks

Recommended mapping:

```text
BriefingRoom
  -> UseCaseTemplate
  -> SourcePack
  -> EditorialPreset
  -> FeedbackProfile
  -> Task runtime config
```

The current `tasks.json` can remain the execution model.

Briefing rooms can initially compile down into task definitions.

### 13.3 Preserve Capability Boundary

`editorial-intelligence` should remain the capability layer.

It should not own:

- scheduling
- channels
- long-term product history
- user-facing room management

It should own:

- source strategy interpretation
- candidate normalization
- editorial shortlist
- section assignment
- final brief generation
- diagnostics

## 14. Suggested Implementation Phases

### Phase 1: Product Definition And Presets

Goal: make the product direction explicit without changing runtime behavior too much.

Deliverables:

- Signal Desk PRD.
- `BriefingRoom` concept in docs.
- initial use case templates.
- initial editorial presets.
- professional judgement lenses.
- initial source pack schema.
- standard signal output contract.
- trust model.
- README product naming update.

### Phase 2: Room Creation MVP

Goal: let a non-technical user create one useful room.

Deliverables:

- Streamlit room creation flow for `Client Opportunity Radar`.
- source pack selector.
- editorial preset selector.
- judgement lens mapping.
- compile room to existing task config.
- dry run preview.
- standard signal preview format.

### Phase 3: Feedback Loop

Goal: make editorial policy tunable through usage.

Deliverables:

- item-level feedback UI.
- feedback storage.
- room-level feedback summary.
- manual policy suggestions based on feedback.

### Phase 4: Source Strategy Assistant

Goal: reduce manual source setup.

Deliverables:

- keyword and source recommendations from room goal.
- source coverage diagnostics.
- fallback source suggestions.
- operator approval before adding new sources.

### Phase 5: Deeper Editorial Intelligence Integration

Goal: migrate execution from fixed pipeline toward `editorial-briefing` skill contract.

Deliverables:

- structured candidate pool.
- shortlist and assignment output.
- diagnostics surfaced in room UI.
- adapter-based source strategy.

## 15. Success Metrics

For internal use, success should be measured by adoption and work impact, not generic engagement.

Initial metrics:

- time to create first useful briefing room
- number of manual configuration fields required before first dry run
- weekly active rooms
- feedback rate per brief
- percentage of brief items marked useful
- number of saved signals reused in client work or pitch work
- number of briefs forwarded to internal channels
- number of items marked for client follow-up
- number of items reused in proposal or internal report drafts

Qualitative checks:

- Can a non-technical team member create a useful room in under 10 minutes?
- Does the output create client conversation starters?
- Does the output reduce manual scanning time?
- Does the team trust why each item was selected?

## 16. Risks

### Risk 1: Product Becomes Another Config Console

If rooms expose too many low-level fields, Signal Desk will recreate the same adoption barrier.

Mitigation:

- keep setup template-driven
- hide technical fields by default
- make advanced configuration optional

### Risk 2: Presets Are Too Generic

Generic presets will produce generic briefs.

Mitigation:

- start with marketing communications use cases
- encode real internal judgement into presets
- use feedback to tune room-specific behavior

### Risk 3: Source Quality Limits Output Quality

Weak source packs will make the product feel shallow regardless of UI.

Mitigation:

- curate high-quality source packs
- surface source coverage diagnostics
- add source strategy assistant later

### Risk 4: Feedback Data Is Too Sparse

Small teams may not provide enough feedback to automate policy tuning.

Mitigation:

- start with simple feedback summaries
- let operators approve suggested policy updates
- do not overpromise automatic learning in MVP

### Risk 5: Radar Becomes Information Consumption Instead Of Work Production

If the product only creates readable briefs, senior users may skim it and then forget it.

Mitigation:

- require every selected signal to include a suggested action
- make saving and reuse first-class
- track whether signals enter client follow-up, pitch work, or reports

## 17. Open Questions

- Should `BriefingRoom` become the primary UI object immediately, or should it first wrap existing tasks invisibly?
- Should source packs live in JSON files, Python registry modules, or a lightweight local database?
- Should feedback be stored per room only, or also roll up into a team-level preference profile?
- Should saved signals become a first-class library in this repo, or be exported to Obsidian / Notion / Drive?
- Should the first pilot room be category-based, client-based, or a combined `client + category` radar?
- Which internal senior users should review the first 10 generated signals?

## 18. Current Recommendation

Implement Signal Desk in the current repo.

Do not rename the repo yet.

Use the next development cycle to add a product layer above the current task model:

```text
BriefingRoom -> Task
```

This allows the product to become easier for ordinary users while preserving the working scheduler, channel delivery, and editorial pipeline already built in `InsightBot`.
