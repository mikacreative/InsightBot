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

- RSS collection
- search collection
- future platform collection

## Contract Layer

Responsible for the stable inputs and outputs that allow products like `InsightBot` to call this runtime cleanly.
