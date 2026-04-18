# `editorial-briefing` Skill Contract

## Purpose

`editorial-briefing` produces a structured intelligence brief from a briefing goal, a source strategy, and an editorial policy.

It is the first core skill in `editorial-intelligence`.

## Responsibilities

- interpret the briefing goal
- collect signals from configured sources
- detect coverage gaps
- supplement sources when needed
- normalize and dedupe candidates
- run editorial shortlist
- assign selected items to sections
- refine section output
- assemble the final brief
- emit diagnostics

## Inputs

### `goal`

Defines what should be produced.

Suggested fields:

- `topic`
- `audience`
- `brief_type`
- `focus_areas`
- `exclusions`
- `time_window`
- `quality_bar`

### `source_strategy`

Defines where to search and how to fall back.

Suggested fields:

- `primary_sources`
- `fallback_sources`
- `search_enabled`
- `platform_enabled`
- `max_explore_rounds`
- `coverage_threshold`
- `freshness_threshold`
- `source_constraints`

### `editorial_policy`

Defines how to shortlist, assign, and write.

Suggested fields:

- `shortlist_size`
- `selection_rules`
- `section_rules`
- `dedupe_rules`
- `tone`
- `citation_style`
- `quality_checks`

### `execution_mode`

Controls runtime behavior.

Supported modes:

- `fast_run`
- `production_run`
- `explore_heavy`
- `source_constrained`
- `diagnostic_run`

## Output

The skill must return structured output, not just final markdown.

Suggested result shape:

```json
{
  "ok": true,
  "source_summary": {},
  "candidate_pool": [],
  "shortlist": [],
  "section_assignments": {},
  "final_brief": {
    "markdown": "..."
  },
  "diagnostics": {
    "coverage_gaps": [],
    "source_failures": [],
    "needs_more_exploration": false
  }
}
```

## Execution Flow

1. Interpret goal
2. Build source strategy for this run
3. Collect primary signals
4. Check coverage and freshness
5. Supplement sources if needed
6. Normalize and dedupe
7. Run shortlist
8. Assign items to sections
9. Refine section output
10. Assemble final brief
11. Emit diagnostics

## Integration Boundary

The skill should not:

- schedule recurring tasks
- own long-term run history
- send to channels directly
- provide an operations console

Those concerns belong to the product layer, such as `InsightBot`.
