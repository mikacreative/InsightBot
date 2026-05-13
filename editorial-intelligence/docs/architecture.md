# Architecture

`editorial-intelligence` is split into three layers:

## Runtime Layer

Responsible for:

- execution context
- execution modes
- tool and adapter orchestration
- error and budget handling

## Skill Layer

Responsible for:

- skill contracts
- skill-specific validation
- skill-specific workflows

The first core skill is `editorial-briefing`.

## Workflow Layer

Responsible for:

- shortlist
- assignment
- refinement
- final assembly

## Adapter Layer

Responsible for:

- RSS collection (official direct feeds via feedparser)
- search collection (multi-provider: DuckDuckGo, Brave, 博查等)
- future platform adapters

### Source Priority

Sources are weighted by reliability, highest first:

| Source Type | Weight | Example |
|---|---|---|
| OFFICIAL | 1.0 | Direct RSS/Atom feed |
| RSSHUB | 0.7 | RSSHub proxy feed |
| AGENT_SEARCH | 0.4 | DuckDuckGo / Brave / 博查 |

Within AGENT_SEARCH, individual provider weights can be configured via `SearchProvider` entries.

## Contract Layer

Responsible for the stable inputs and outputs that allow products like `InsightBot` to call this runtime cleanly.
