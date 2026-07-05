from __future__ import annotations

import streamlit as st

from insightbot.paths import default_bot_dir

try:
    from scripts.ui.web_archive import render_web_archive_page
except ModuleNotFoundError:
    from ui.web_archive import render_web_archive_page


def main() -> None:
    st.set_page_config(
        page_title="InsightBot Briefing",
        page_icon="🌐",
        layout="wide",
    )
    render_web_archive_page(bot_dir=default_bot_dir(), public_mode=True)


if __name__ == "__main__":
    main()
