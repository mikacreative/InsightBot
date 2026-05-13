from editorial_intelligence.contracts.execution_mode import ExecutionMode
from editorial_intelligence.skills.editorial_briefing import (
    run_editorial_briefing_from_insightbot_config,
)


def main() -> None:
    config = {
        "feeds": {},
        "ai": {
            "api_url": "https://example.invalid",
            "api_key": "demo",
            "model": "demo",
            "editorial_pipeline": {"enabled": True},
        },
    }
    result = run_editorial_briefing_from_insightbot_config(
        config=config,
        execution_mode=ExecutionMode.DIAGNOSTIC_RUN,
    )
    print(result)


if __name__ == "__main__":
    main()
