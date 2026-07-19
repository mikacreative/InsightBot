"""TV big-screen page rendering for brief outputs.

P0 slice of the TV dashboard direction: parse a task's ``final_markdown``
into a section/item model, render a self-contained dark 16:9 HTML page
(section rotation + auto refresh), and atomically write it into the
Streamlit static dir so it is served at ``/app/static/screen/<task_id>.html``.

The markdown format is repo-controlled (``smart_brief_runner._render_markdown``):
``## section`` headings, ``### [title](url)`` items and ``> 💡 *summary*``
lines. Tests lock this contract.
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlsplit

from .ids import require_safe_id
from .paths import screen_output_dir
from .run_history import list_task_runs

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_SECONDS = 300
DEFAULT_ROTATE_SECONDS = 15
DEFAULT_IMAGE_ROTATE_SECONDS = 10
EMPTY_MESSAGE = "暂无最新内容，等待下一次任务更新。"

_SECTION_RE = re.compile(r"^##(?!#)\s+(.+?)\s*$")
_ITEM_RE = re.compile(r"^###\s+\[([^\]]*)\]\(([^)]*)\)\s*$")
_SUMMARY_RE = re.compile(r"^>\s*💡?\s*\*(.+?)\*?\s*$")


def parse_brief_markdown(markdown: str) -> list[dict[str, Any]]:
    """Parse brief final_markdown into [{"section": str, "items": [...]}].

    Tolerant of malformed lines: anything unrecognized is skipped. Sections
    without any valid item are dropped (a bare heading is noise on a TV).
    """
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_item: dict[str, str] | None = None

    def flush_item() -> None:
        nonlocal pending_item
        if current is not None and pending_item is not None and pending_item.get("title"):
            current["items"].append(pending_item)
        pending_item = None

    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section_match = _SECTION_RE.match(line)
        if section_match:
            flush_item()
            current = {"section": section_match.group(1), "items": []}
            sections.append(current)
            continue
        item_match = _ITEM_RE.match(line)
        if item_match and current is not None:
            flush_item()
            pending_item = {
                "title": item_match.group(1).strip(),
                "url": item_match.group(2).strip(),
                "summary": "",
            }
            continue
        summary_match = _SUMMARY_RE.match(line)
        if summary_match and pending_item is not None:
            pending_item["summary"] = summary_match.group(1).strip()
    flush_item()
    return [section for section in sections if section["items"]]


def _positive_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _source_label(url: str) -> str:
    """Derive a short source label (domain) from an item URL for on-screen display."""
    try:
        host = urlsplit(str(url or "")).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF\uFE0F\u200D]+")
_THEMES = {"auto", "dark", "light"}


def _clean_display_text(value: str) -> str:
    """Strip emoji and collapse whitespace so the page keeps its editorial tone."""
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", str(value or ""))).strip()


def _normalize_theme(value: Any) -> str:
    return value if isinstance(value, str) and value in _THEMES else "auto"


def _initial_theme_class(theme: str, now: datetime) -> str:
    """Server-side first paint theme; the page's JS re-checks with the TV's clock."""
    if theme == "auto":
        return "theme-light" if 7 <= now.hour < 19 else "theme-dark"
    return f"theme-{theme}"


_PAGE_TEMPLATE = Template("""      <h2 class="section-title">$section_name</h2>
      <div class="items">
$item_blocks
      </div>
      <div class="pager"><span>$task_name</span><span>$page_index / $page_count</span></div>""")

_ITEM_TEMPLATE = Template("""        <div class="item">
          <div class="rank">$rank</div>
          <div class="item-body">
            <h3>$title</h3>
            <p>$summary</p>
            <div class="src">$source</div>
          </div>
        </div>""")

_HTML_TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="$refresh_seconds">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$report_title · $task_name</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; }
body {
  --bg: #0b4022; --ink: #f2ecd4;
  --ink-soft: rgba(242,236,212,.72); --ink-faint: rgba(242,236,212,.5);
  --rule: rgba(242,236,212,.32); --rule-soft: rgba(242,236,212,.16);
  background: var(--bg); color: var(--ink); overflow: hidden;
  font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
}
body.theme-dark {
  --bg: #0b4022; --ink: #f2ecd4;
  --ink-soft: rgba(242,236,212,.72); --ink-faint: rgba(242,236,212,.5);
  --rule: rgba(242,236,212,.32); --rule-soft: rgba(242,236,212,.16);
}
body.theme-light {
  --bg: #f2ecd4; --ink: #0b4022;
  --ink-soft: rgba(11,64,34,.74); --ink-faint: rgba(11,64,34,.52);
  --rule: rgba(11,64,34,.34); --rule-soft: rgba(11,64,34,.18);
}
.serif, .brand-title, .section-title, .item h3 {
  font-family: "Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", Georgia, "Times New Roman", serif;
}
#progress { position: fixed; top: 0; left: 0; height: .4vh; width: 0; z-index: 10; background: var(--ink); opacity: .7; }
body { display: flex; }
.news-pane {
  width: 36vw; height: 100vh; display: flex; flex-direction: column;
  border-right: 1px solid var(--rule);
}
.news-pane header { padding: 1.8vh 2vw 0; border-bottom: .45vh double var(--ink); }
.masthead-top {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: .78vw; letter-spacing: .2em; text-transform: uppercase; color: var(--ink-faint);
}
.brand-title {
  margin: 1.2vh 0 1.6vh; text-align: center;
  font-size: 2vw; font-weight: 800; letter-spacing: .05em; line-height: 1.05;
}
main { flex: 1; position: relative; }
.page {
  position: absolute; inset: 0; display: flex; flex-direction: column; padding: 2.5vh 2vw 2vh;
  opacity: 0; visibility: hidden; transform: translateY(1.5vh);
  transition: opacity .6s ease, transform .6s ease, visibility 0s linear .6s;
}
.page.active {
  opacity: 1; visibility: visible; transform: none;
  transition: opacity .6s ease, transform .6s ease;
}
.section-title {
  display: flex; align-items: center; gap: 1.2vw; margin-bottom: 1vh;
  font-size: 1.6vw; font-weight: 700; letter-spacing: .14em; white-space: nowrap;
}
.section-title::before, .section-title::after {
  content: ""; flex: 1; border-top: 1px solid var(--rule);
}
.items { flex: 1; display: flex; flex-direction: column; overflow: hidden; padding-top: .6vh; }
.item {
  display: flex; gap: 1vw; align-items: baseline;
  padding: 2vh 0; border-bottom: 1px solid var(--rule-soft);
}
.rank {
  font-size: .9vw; font-weight: 500; letter-spacing: .08em; min-width: 1.8vw;
  color: var(--ink-faint); font-variant-numeric: tabular-nums;
}
.item-body { flex: 1; }
.item h3 { font-size: 1.25vw; font-weight: 700; line-height: 1.38; letter-spacing: .02em; margin-bottom: .8vh; }
.item p { font-size: .95vw; font-weight: 300; color: var(--ink-soft); line-height: 1.6; }
.src {
  margin-top: .9vh; font-size: .72vw; letter-spacing: .12em; text-transform: uppercase;
  color: var(--ink-faint);
}
.pager {
  margin-top: 1.4vh; padding-top: 1.2vh; border-top: 1px solid var(--rule);
  font-size: .8vw; letter-spacing: .16em; color: var(--ink-faint);
  display: flex; justify-content: space-between;
}
.empty { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 1.3vw; letter-spacing: .12em; color: var(--ink-faint); }
.photo-pane { position: relative; flex: 1; height: 100vh; overflow: hidden; background: var(--bg); }
.slide {
  position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
  opacity: 0; transition: opacity 1.2s ease;
}
.slide.active { opacity: 1; }
.scrim {
  position: absolute; left: 0; right: 0; bottom: 0; height: 22vh;
  background: linear-gradient(transparent, rgba(0,0,0,.55));
}
.photo-clock {
  position: absolute; right: 2vw; bottom: 3vh; text-align: right;
  color: #f2ecd4; font-variant-numeric: tabular-nums;
  text-shadow: 0 .2vh 1.2vh rgba(0,0,0,.6);
}
.photo-clock .time { font-size: 2.4vw; font-weight: 600; }
.photo-clock .date { font-size: 1vw; opacity: .85; }
.photo-fallback {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 1.1vw; letter-spacing: .3em; text-transform: uppercase; color: var(--ink-faint);
}
</style>
</head>
<body class="$theme_class">
<div id="progress"></div>
<div class="news-pane">
  <header>
    <div class="masthead-top"><span>Signal Desk · $task_name</span><span>更新于 $generated_at</span></div>
    <div class="brand-title">$report_title</div>
  </header>
  <main>
$pages
  </main>
</div>
<div class="photo-pane">
$photo_content
  <div class="scrim"></div>
  <div class="photo-clock"><div class="time" id="clock-time">--:--:--</div><div class="date" id="clock-date"></div></div>
</div>
<script>
(function () {
  var THEME_MODE = "$theme";
  function applyTheme() {
    var mode = THEME_MODE;
    if (mode === "auto") {
      var h = new Date().getHours();
      mode = (h >= 7 && h < 19) ? "light" : "dark";
    }
    document.body.className = "theme-" + mode;
  }
  applyTheme();
  setInterval(applyTheme, 60000);

  function tick() {
    var now = new Date();
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    document.getElementById("clock-time").textContent =
      pad(now.getHours()) + ":" + pad(now.getMinutes()) + ":" + pad(now.getSeconds());
    document.getElementById("clock-date").textContent =
      now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
  }
  tick();
  setInterval(tick, 1000);

  var pages = document.querySelectorAll(".page");
  var progress = document.getElementById("progress");
  var index = 0;
  function restartProgress() {
    if (!progress) { return; }
    progress.style.transition = "none";
    progress.style.width = "0";
    void progress.offsetWidth;
    progress.style.transition = "width " + ($rotate_ms) + "ms linear";
    progress.style.width = "100%";
  }
  function show(i) {
    for (var j = 0; j < pages.length; j += 1) { pages[j].classList.toggle("active", j === i); }
    restartProgress();
  }
  show(0);
  if (pages.length > 1) {
    setInterval(function () { index = (index + 1) % pages.length; show(index); }, $rotate_ms);
  }

  var slides = document.querySelectorAll(".slide");
  var slideIndex = 0;
  function showSlide(i) {
    for (var j = 0; j < slides.length; j += 1) { slides[j].classList.toggle("active", j === i); }
  }
  if (slides.length > 0) {
    showSlide(0);
    if (slides.length > 1) {
      setInterval(function () { slideIndex = (slideIndex + 1) % slides.length; showSlide(slideIndex); }, $image_rotate_ms);
    }
  }
})();
</script>
</body>
</html>
""")


def render_screen_html(
    *,
    report_title: str,
    task_name: str,
    sections: list[dict[str, Any]],
    generated_at: datetime,
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
    rotate_seconds: int = DEFAULT_ROTATE_SECONDS,
    theme: str = "auto",
    images: list[str] | None = None,
    image_rotate_seconds: int = DEFAULT_IMAGE_ROTATE_SECONDS,
) -> str:
    """Render the self-contained TV page. All text is HTML-escaped and emoji-free."""
    refresh_seconds = _positive_int(refresh_seconds, DEFAULT_REFRESH_SECONDS)
    rotate_seconds = _positive_int(rotate_seconds, DEFAULT_ROTATE_SECONDS)
    image_rotate_seconds = _positive_int(image_rotate_seconds, DEFAULT_IMAGE_ROTATE_SECONDS)
    theme = _normalize_theme(theme)

    esc_task_name = html.escape(_clean_display_text(task_name), quote=True)
    pages: list[str] = []
    page_count = len(sections)
    for index, section in enumerate(sections, start=1):
        item_blocks = []
        for rank, item in enumerate(section["items"], start=1):
            item_blocks.append(
                _ITEM_TEMPLATE.substitute(
                    rank=f"{rank:02d}",
                    title=html.escape(_clean_display_text(item["title"]), quote=True),
                    summary=html.escape(_clean_display_text(item.get("summary", "")), quote=True),
                    source=html.escape(_source_label(item.get("url", "")), quote=True),
                )
            )
        pages.append(
            '<div class="page">\n'
            + _PAGE_TEMPLATE.substitute(
                section_name=html.escape(_clean_display_text(section["section"]), quote=True),
                item_blocks="\n".join(item_blocks),
                task_name=esc_task_name,
                page_index=index,
                page_count=page_count,
            )
            + "\n</div>"
        )
    if not pages:
        pages.append(
            '<div class="page active">\n'
            f'      <div class="empty">{html.escape(EMPTY_MESSAGE)}</div>\n'
            "</div>"
        )

    image_list = [str(src).strip() for src in (images or []) if str(src).strip()]
    if image_list:
        photo_content = "\n".join(
            f'  <img class="slide" src="{html.escape(src, quote=True)}" alt="">' for src in image_list
        )
    else:
        photo_content = '  <div class="photo-fallback">Signal Desk</div>'

    return _HTML_TEMPLATE.substitute(
        refresh_seconds=refresh_seconds,
        rotate_ms=rotate_seconds * 1000,
        report_title=html.escape(_clean_display_text(report_title), quote=True),
        task_name=esc_task_name,
        generated_at=html.escape(generated_at.strftime("%Y-%m-%d %H:%M"), quote=True),
        pages="\n".join(pages),
        theme=theme,
        theme_class=_initial_theme_class(theme, generated_at),
        photo_content=photo_content,
        image_rotate_ms=image_rotate_seconds * 1000,
    )


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def list_screen_images(bot_dir: str | None = None) -> list[str]:
    """Relative ``img/`` paths of the photos shown in the right-hand pane.

    Images are read from <screen_output_dir>/img; drop files in that folder
    and they join the rotation on the next render. Missing folder → no images.
    """
    img_dir = Path(screen_output_dir(bot_dir)) / "img"
    try:
        names = sorted(p.name for p in img_dir.iterdir() if p.suffix.lower() in _IMAGE_EXTS)
    except OSError:
        return []
    return [f"img/{name}" for name in names]


def write_screen_html(task_id: str, html_text: str, bot_dir: str | None = None) -> Path:
    """Atomically write the page to <screen_output_dir>/<task_id>.html."""
    safe_task_id = require_safe_id(task_id, label="task_id")
    out_dir = Path(screen_output_dir(bot_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{safe_task_id}.html"
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, prefix=safe_task_id + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(html_text)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


def build_screen_html(
    task_id: str,
    config: dict[str, Any],
    markdown: str,
    *,
    images: list[str] | None = None,
) -> str:
    """Build the page for one task from its runtime config and final_markdown."""
    screen_cfg = config.get("_task_screen") or {}
    settings = config.get("settings") or {}
    task_name = str(config.get("_task_name") or task_id)
    now = datetime.now()
    # Same {date} substitution convention as channel_rendering.build_delivery_plan.
    title_template = str(settings.get("report_title") or "📅 营销情报早报 | {date}")
    report_title = title_template.replace("{date}", now.strftime("%m-%d")).strip()
    sections = parse_brief_markdown(markdown)
    return render_screen_html(
        report_title=report_title,
        task_name=task_name,
        sections=sections,
        generated_at=now,
        refresh_seconds=_positive_int(screen_cfg.get("refresh_seconds"), DEFAULT_REFRESH_SECONDS),
        rotate_seconds=_positive_int(screen_cfg.get("rotate_seconds"), DEFAULT_ROTATE_SECONDS),
        theme=_normalize_theme(screen_cfg.get("theme")),
        images=images,
        image_rotate_seconds=_positive_int(
            screen_cfg.get("image_rotate_seconds"), DEFAULT_IMAGE_ROTATE_SECONDS
        ),
    )


def generate_screen_for_task(
    task_id: str,
    config: dict[str, Any],
    markdown: str,
    *,
    bot_dir: str | None = None,
) -> Path:
    """Render and write the TV page for a task run that just produced markdown."""
    page = build_screen_html(task_id, config, markdown, images=list_screen_images(bot_dir))
    return write_screen_html(task_id, page, bot_dir=bot_dir)


def generate_screen_from_latest_run(task_id: str, *, bot_dir: str | None = None) -> Path | None:
    """Render the page from the latest run record that kept final_markdown.

    Returns None when no usable run record exists (never raises on missing
    history) so manual/local verification does not need a fresh AI run.
    """
    markdown = ""
    for record in list_task_runs(task_id, bot_dir=bot_dir, limit=0):
        trace = record.get("run_trace") or {}
        candidate = str(trace.get("final_markdown") or "")
        if candidate.strip():
            markdown = candidate
            break
    if not markdown:
        return None
    try:
        from .config import load_tasks_config

        config = load_tasks_config(task_id, bot_dir=bot_dir)
    except Exception as exc:  # fall back to minimal config; page content matters more
        logger.warning("screen: failed to load task config for %s: %s", task_id, exc)
        config = {}
    return generate_screen_for_task(task_id, config, markdown, bot_dir=bot_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the TV screen page for a task from its latest run record.")
    parser.add_argument("task_id", help="Task identifier in tasks.json, e.g. Daily_brief")
    parser.add_argument("--bot-dir", default=None, help="Override the bot directory (defaults to MARKETING_BOT_DIR or repo root).")
    args = parser.parse_args(argv)
    path = generate_screen_from_latest_run(args.task_id, bot_dir=args.bot_dir)
    if path is None:
        print(f"No run record with final_markdown found for task '{args.task_id}'.")
        return 1
    print(f"Screen page written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
