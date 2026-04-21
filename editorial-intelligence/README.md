# editorial-intelligence

Editorial intelligence runtime for multi-source briefing workflows.

`editorial-intelligence` is a skill-oriented execution core for producing structured intelligence briefs. It is designed to power products like `InsightBot`, while also remaining reusable for agents, automations, and internal research workflows.

## What It Does

The system is built around an editorial workflow instead of a fixed RSS script.

It supports:

- multi-source collection
- source strategy and fallback logic
- normalized candidate pools
- editorial shortlist and assignment
- section-level refinement
- final brief generation
- diagnostic output

## What It Is Not

This project is not:

- a control console
- a scheduler
- a channel delivery system
- a multi-task operations backend

Those concerns should stay in product layers such as `InsightBot`.

## Core Concepts

### Skill

A reusable execution contract for a class of work.

The first core skill is:

- `editorial-briefing`

### Runtime

The runtime coordinates execution steps, source adapters, fallback paths, and diagnostics.

### Source Strategy

A structured policy for deciding where to gather signals from:

- RSS
- Search
- Platform adapters
- Future APIs or internal data sources

### Editorial Workflow

The canonical workflow is:

1. interpret goal
2. collect signals
3. fill coverage gaps
4. normalize and dedupe
5. shortlist
6. assign to sections
7. refine and compose
8. emit diagnostics and final brief

## Package Layout

```text
editorial_intelligence/
  runtime/
  skills/
  adapters/
  contracts/
  workflows/
  diagnostics/
  policies/
  storage/
  utils/
```

## Public API

```python
from editorial_intelligence.skills.editorial_briefing import run_editorial_briefing

result = run_editorial_briefing(
    goal=...,
    source_strategy=...,
    editorial_policy=...,
    execution_mode="production_run",
)
```

The result should include:

- source summary
- candidate pool
- shortlist
- section assignments
- final brief
- diagnostics

## Migration Bridge

The bootstrap stage also includes a temporary bridge for running the current
`InsightBot` `editorial_pipeline` through the new result contract:

```python
from editorial_intelligence.skills.editorial_briefing import (
    run_editorial_briefing_from_insightbot_config,
)
```

This allows gradual migration without forcing a full rewrite of the current
production flow.

## Relationship to InsightBot

Recommended split:

- `InsightBot`: tasks, channels, scheduling, operations console, run history
- `editorial-intelligence`: source collection, editorial reasoning, brief generation

## Development Stages

### Phase 1

Wrap the current editorial pipeline in a skill contract.

### Phase 2

Introduce structured source strategies and adapter-based source expansion.

### Phase 3

Add a lightweight agent runtime for exploration, fallback, and execution modes.
