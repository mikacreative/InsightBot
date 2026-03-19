import os

from insightbot.paths import default_bot_dir


def main() -> None:
    bot_dir = default_bot_dir()
    daily_path = os.path.join(bot_dir, "daily_brief.py")

    if os.path.abspath(__file__) == os.path.abspath(daily_path):
        raise SystemExit("scripts/daily_brief.py should not shadow daily_brief.py")

    # Keep backward compatibility: run root daily_brief.py
    with open(daily_path, "r", encoding="utf-8") as f:
        code = compile(f.read(), daily_path, "exec")
    exec(code, {"__name__": "__main__"})


if __name__ == "__main__":
    main()

