from editorial_intelligence.contracts.briefing_result import BriefingResult
from editorial_intelligence.contracts.editorial_policy import EditorialPolicy
from editorial_intelligence.contracts.execution_mode import ExecutionMode
from editorial_intelligence.contracts.goal import BriefingGoal
from editorial_intelligence.contracts.source_strategy import SourceStrategy
from editorial_intelligence.skills.editorial_briefing.skill import EditorialBriefingSkill


class RuntimeEngine:
    """Minimal runtime entrypoint for executing registered skills."""

    def run_editorial_briefing(
        self,
        *,
        goal: BriefingGoal,
        source_strategy: SourceStrategy,
        editorial_policy: EditorialPolicy,
        execution_mode: ExecutionMode = ExecutionMode.PRODUCTION_RUN,
    ) -> BriefingResult:
        skill = EditorialBriefingSkill()
        return skill.run(
            goal=goal,
            source_strategy=source_strategy,
            editorial_policy=editorial_policy,
            execution_mode=execution_mode,
        )
