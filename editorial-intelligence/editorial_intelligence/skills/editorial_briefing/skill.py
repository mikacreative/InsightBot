from editorial_intelligence.contracts.briefing_result import BriefingResult
from editorial_intelligence.contracts.editorial_policy import EditorialPolicy
from editorial_intelligence.contracts.execution_mode import ExecutionMode
from editorial_intelligence.contracts.goal import BriefingGoal
from editorial_intelligence.contracts.source_strategy import SourceStrategy
from editorial_intelligence.workflows.editorial_pipeline import run_editorial_pipeline


class EditorialBriefingSkill:
    """Bootstrap implementation of the core editorial briefing skill."""

    name = "editorial-briefing"

    def run(
        self,
        *,
        goal: BriefingGoal,
        source_strategy: SourceStrategy,
        editorial_policy: EditorialPolicy,
        execution_mode: ExecutionMode = ExecutionMode.PRODUCTION_RUN,
    ) -> BriefingResult:
        return run_editorial_pipeline(
            context={
                "goal": goal,
                "source_strategy": source_strategy,
                "editorial_policy": editorial_policy,
                "execution_mode": execution_mode,
            }
        )


def run_editorial_briefing(
    *,
    goal: BriefingGoal,
    source_strategy: SourceStrategy,
    editorial_policy: EditorialPolicy,
    execution_mode: ExecutionMode = ExecutionMode.PRODUCTION_RUN,
) -> BriefingResult:
    return EditorialBriefingSkill().run(
        goal=goal,
        source_strategy=source_strategy,
        editorial_policy=editorial_policy,
        execution_mode=execution_mode,
    )
