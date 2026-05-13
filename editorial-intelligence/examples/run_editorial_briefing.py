from editorial_intelligence.contracts.editorial_policy import EditorialPolicy
from editorial_intelligence.contracts.goal import BriefingGoal
from editorial_intelligence.contracts.source_strategy import SourceStrategy
from editorial_intelligence.skills.editorial_briefing import run_editorial_briefing


def main() -> None:
    result = run_editorial_briefing(
        goal=BriefingGoal(topic="AI productivity tools"),
        source_strategy=SourceStrategy(primary_sources=["rss://example"]),
        editorial_policy=EditorialPolicy(),
    )
    print(result)


if __name__ == "__main__":
    main()
