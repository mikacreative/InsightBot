from enum import StrEnum


class ExecutionMode(StrEnum):
    FAST_RUN = "fast_run"
    PRODUCTION_RUN = "production_run"
    EXPLORE_HEAVY = "explore_heavy"
    SOURCE_CONSTRAINED = "source_constrained"
    DIAGNOSTIC_RUN = "diagnostic_run"
