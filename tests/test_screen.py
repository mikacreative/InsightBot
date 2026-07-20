"""
test_screen.py — insightbot.screen 电视大屏 P0 测试

测试范围：
  - parse_brief_markdown: 标准 brief markdown → 板块/条目模型，畸形行容错
  - render_screen_html: 深色主题、自动刷新、板块轮播、HTML 转义、空板块兜底
  - write_screen_html: 原子写入、目录创建、SCREEN_OUTPUT_DIR 覆盖
  - generate_screen_from_latest_run: 从 run 记录渲染
  - task_runner hook: screen.enabled 时生成页面，失败不影响 run 结果
"""

import json
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Mock feedparser and requests before importing task_runner (module-level deps)
sys.modules.setdefault("feedparser", MagicMock())
sys.modules.setdefault("requests", MagicMock())

from insightbot.screen import (  # noqa: E402
    EMPTY_MESSAGE,
    build_screen_html,
    build_screen_index_html,
    collect_selected_image_map,
    generate_screen_from_latest_run,
    list_screen_images,
    parse_brief_markdown,
    prepare_section_images,
    render_screen_html,
    write_screen_html,
    write_screen_index,
)

SAMPLE_MARKDOWN = """## 💡 营销行业

### [某品牌 campaign 案例](https://example.com/a)
> 💡 *核心锚点是情绪共鸣，背后是社交裂变策略。*

### [另一案例](https://example.com/b)
> 💡 *第二条摘要。*

## 🤖 数智前沿

### [AI 工具更新](https://example.com/c)
> 💡 *平台机制变化影响内容分发。*
"""


class TestParseBriefMarkdown:
    def test_parses_sections_and_items(self):
        sections = parse_brief_markdown(SAMPLE_MARKDOWN)
        assert [s["section"] for s in sections] == ["💡 营销行业", "🤖 数智前沿"]
        assert sections[0]["items"] == [
            {
                "title": "某品牌 campaign 案例",
                "url": "https://example.com/a",
                "summary": "核心锚点是情绪共鸣，背后是社交裂变策略。",
            },
            {"title": "另一案例", "url": "https://example.com/b", "summary": "第二条摘要。"},
        ]
        assert len(sections[1]["items"]) == 1

    def test_empty_input_returns_empty_list(self):
        assert parse_brief_markdown("") == []
        assert parse_brief_markdown(None) == []

    def test_malformed_lines_are_skipped(self):
        markdown = (
            "## 板块一\n"
            "\n"
            "### 没有链接的标题行\n"
            "### [有链接](https://example.com/x)\n"
            "随机一行噪声\n"
            "> 💡 *摘要内容*\n"
            "## 空板块\n"
            "## 板块二\n"
            "### [条目](https://example.com/y)\n"
        )
        sections = parse_brief_markdown(markdown)
        assert [s["section"] for s in sections] == ["板块一", "板块二"]
        assert sections[0]["items"] == [
            {"title": "有链接", "url": "https://example.com/x", "summary": "摘要内容"}
        ]
        assert sections[1]["items"] == [{"title": "条目", "url": "https://example.com/y", "summary": ""}]


class TestRenderScreenHtml:
    def _render(self, sections=None, **overrides):
        kwargs = {
            "report_title": "营销情报站",
            "task_name": "营销日报",
            "sections": sections if sections is not None else parse_brief_markdown(SAMPLE_MARKDOWN),
            "generated_at": datetime(2026, 7, 17, 10, 30),
            "refresh_seconds": 300,
            "rotate_seconds": 15,
        }
        kwargs.update(overrides)
        return render_screen_html(**kwargs)

    def test_contains_theme_refresh_and_content(self):
        page = self._render()
        assert '<meta http-equiv="refresh" content="300">' in page
        assert "#0b4022" in page  # 深森林绿(YGGBi 官网风,暗色主题)
        assert "#f2ecd4" in page  # 奶白(亮色主题背景)
        assert "15000" in page  # 轮播间隔毫秒
        assert "营销情报站" in page
        assert "营销日报" in page
        assert "2026-07-17 10:30" in page
        assert "营销行业" in page
        assert "某品牌 campaign 案例" in page
        assert "核心锚点是情绪共鸣，背后是社交裂变策略。" in page
        assert "1 / 2" in page and "2 / 2" in page  # 板块页码
        assert "masthead-top" in page  # 报纸刊头
        assert "Songti SC" in page  # 衬线标题字体栈

    def test_emoji_stripped_for_editorial_tone(self):
        page = self._render()
        assert "💡" not in page
        assert "🤖" not in page

    def test_theme_auto_dark_light(self):
        assert 'var THEME_MODE = "auto";' in self._render()
        dark = self._render(theme="dark")
        assert 'var THEME_MODE = "dark";' in dark
        assert '<body class="theme-dark">' in dark
        light = self._render(theme="light")
        assert 'var THEME_MODE = "light";' in light
        assert '<body class="theme-light">' in light
        assert 'var THEME_MODE = "auto";' in self._render(theme="neon")  # 非法值回退 auto

    def test_photo_pane_with_images(self):
        page = self._render(images=["img/a.jpg", "img/b.jpg"], image_rotate_seconds=8)
        assert 'var FALLBACK_IMAGES = ["img/a.jpg", "img/b.jpg"];' in page
        assert "8000" in page  # 图片轮播间隔毫秒

    def test_section_images_json_and_fallback(self):
        page = self._render(
            images=["img/generic.jpg"],
            section_images=[["img/news/x.jpg"], []],
        )
        assert 'var SECTION_IMAGES = [["img/news/x.jpg"], []];' in page
        assert 'var FALLBACK_IMAGES = ["img/generic.jpg"];' in page
        # 板块无图时回退到通用图
        assert "(own && own.length) ? own : FALLBACK_IMAGES" in page

    def test_photo_pane_fallback_without_images(self):
        page = self._render()
        assert 'id="photo-fallback"' in page
        assert "var FALLBACK_IMAGES = [];" in page

    def test_refresh_and_rotate_overrides(self):
        page = self._render(refresh_seconds=60, rotate_seconds=5)
        assert '<meta http-equiv="refresh" content="60">' in page
        assert "5000" in page

    def test_rank_badges_source_labels_and_accents(self):
        page = self._render()
        assert '<div class="rank">01</div>' in page
        assert '<div class="rank">02</div>' in page
        assert '<div class="src">example.com</div>' in page
        assert 'id="progress"' in page  # 轮播进度条

    def test_invalid_refresh_and_rotate_fall_back_to_defaults(self):
        page = self._render(refresh_seconds=0, rotate_seconds=-3)
        assert '<meta http-equiv="refresh" content="300">' in page
        assert "15000" in page

    def test_escapes_injected_html(self):
        sections = [
            {
                "section": "板块<script>alert(1)</script>",
                "items": [
                    {"title": "标题<img src=x onerror=alert(1)>", "url": "https://example.com", "summary": "摘要<b>"}
                ],
            }
        ]
        page = self._render(sections=sections)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "&lt;img src=x onerror=alert(1)&gt;" in page
        assert "<script>alert(1)</script>" not in page
        assert "<img src=x onerror=alert(1)>" not in page

    def test_empty_sections_show_fallback_message(self):
        page = self._render(sections=[])
        assert EMPTY_MESSAGE in page
        assert 'class="page active"' in page


class TestListScreenImages:
    def test_scans_img_dir_sorted(self, tmp_path, monkeypatch):
        img_dir = tmp_path / "screen" / "img"
        img_dir.mkdir(parents=True)
        for name in ("b.jpg", "a.png", "notes.txt", "c.webp"):
            (img_dir / name).write_text("x")
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        assert list_screen_images() == ["img/a.png", "img/b.jpg", "img/c.webp"]

    def test_missing_dir_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "nope"))
        assert list_screen_images() == []


class TestCollectSelectedImageMap:
    def test_maps_urls_from_stage_results(self):
        stage_results = {
            "category_results": {
                "板块A": {
                    "selected_items": [
                        {"title": "t1", "url": "https://a.com/1", "summary": "s", "image_url": "https://img.com/1.jpg"},
                        {"title": "t2", "url": "https://a.com/2", "summary": "s", "image_url": ""},
                    ]
                },
                "板块B": "not-a-dict",
            }
        }
        assert collect_selected_image_map(stage_results) == {"https://a.com/1": "https://img.com/1.jpg"}

    def test_empty_stage_results(self):
        assert collect_selected_image_map({}) == {}


class TestPrepareSectionImages:
    def test_feed_image_with_og_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(
            "insightbot.screen_images.fetch_og_image_urls",
            lambda urls: {"https://example.com/b": "https://cdn.example.com/og-b.jpg"},
        )
        monkeypatch.setattr(
            "insightbot.screen_images.cache_news_images",
            lambda urls, cache_dir: {u: "h1.jpg" for u in urls},
        )
        sections = parse_brief_markdown(SAMPLE_MARKDOWN)
        result = prepare_section_images(sections, {"https://example.com/a": "https://img.example.com/a.jpg"})
        # 板块一:a 用 feed 图,b 走 og:image 兜底;板块二:c 无图
        assert result == [["img/news/h1.jpg", "img/news/h1.jpg"], []]

    def test_no_images_returns_empty_lists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("insightbot.screen_images.fetch_og_image_urls", lambda urls: {})
        monkeypatch.setattr("insightbot.screen_images.cache_news_images", lambda urls, cache_dir: {})
        result = prepare_section_images(parse_brief_markdown(SAMPLE_MARKDOWN), {})
        assert result == [[], []]


class TestConsoleScreenEditor:
    """控制台任务编辑器的大屏配置区(源码级 smoke,与现有 UI 测试同约定)。"""

    def test_task_editor_exposes_screen_controls(self):
        from pathlib import Path

        source = Path("scripts/app.py").read_text(encoding="utf-8")
        assert "📺 大屏:这条任务要不要上电视" in source
        assert "task_screen_enabled_" in source
        assert "task_screen_theme_" in source
        assert "task_screen_refresh_" in source
        assert "task_screen_rotate_" in source
        assert "task_screen_image_rotate_" in source
        assert "task_screen_title_" in source
        assert 'proposed_task_def["screen"]' in source
        assert '"image_rotate_seconds"' in source
        assert "/app/static/screen/" in source

    def test_config_error_banner_present(self):
        from pathlib import Path

        source = Path("scripts/app.py").read_text(encoding="utf-8")
        assert "scheduler.config_error" in source
        assert "tasks.json 加载失败" in source

    def test_sidebar_metrics_use_retained_task_map(self):
        """侧边栏指标不得再直接重读 tasks.json(坏文件时会崩)。"""
        from pathlib import Path

        source = Path("scripts/app.py").read_text(encoding="utf-8")
        assert "scheduler.tasks.items()" in source


class TestBuildScreenHtml:
    def test_report_title_date_placeholder_is_substituted(self):
        config = {
            "_task_name": "营销日报",
            "settings": {"report_title": "📅 营销早报 | {date}"},
            "_task_screen": {"enabled": True},
        }
        page = build_screen_html("Daily_brief", config, SAMPLE_MARKDOWN)
        assert "{date}" not in page
        assert datetime.now().strftime("%m-%d") in page
        assert "📅" not in page  # 标题 emoji 也被剥除

    def test_default_title_used_when_unconfigured(self):
        page = build_screen_html("Daily_brief", {}, SAMPLE_MARKDOWN)
        assert "营销情报早报" in page

    def test_task_screen_title_overrides_global(self):
        config = {
            "_task_name": "营销日报",
            "settings": {"report_title": "全局标题 | {date}"},
            "_task_screen": {"enabled": True, "title": "客户雷达 | {date}"},
        }
        page = build_screen_html("Daily_brief", config, SAMPLE_MARKDOWN)
        assert "客户雷达" in page
        assert "全局标题" not in page


class TestScreenIndex:
    def test_index_lists_only_enabled_tasks(self, tmp_path, monkeypatch):
        tasks = {
            "tasks": {
                "Daily_brief": {"name": "营销日报", "screen": {"enabled": True}},
                "Other_task": {"name": "其他任务", "screen": {"enabled": False}},
            }
        }
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("TASKS_FILE", str(tasks_file))
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        target = write_screen_index()
        assert target is not None
        page = target.read_text(encoding="utf-8")
        assert 'href="Daily_brief.html"' in page
        assert "营销日报" in page
        assert "Other_task" not in page
        assert list((tmp_path / "screen").glob("*.tmp")) == []

    def test_index_returns_none_without_enabled_tasks(self, tmp_path, monkeypatch):
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({"tasks": {"t1": {"name": "x"}}}), encoding="utf-8")
        monkeypatch.setenv("TASKS_FILE", str(tasks_file))
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        assert write_screen_index() is None

    def test_index_html_escapes_and_strips_emoji(self):
        page = build_screen_index_html(
            [("t1", "📊 标题<script>")], generated_at=datetime(2026, 7, 19, 10, 0)
        )
        assert "标题&lt;script&gt;" in page
        assert "📊" not in page
        assert 'href="t1.html"' in page


class TestWriteScreenHtml:
    def test_writes_atomically_with_env_override(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "screen"
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(out_dir))
        target = write_screen_html("Daily_brief", "<html>ok</html>")
        assert target == out_dir / "Daily_brief.html"
        assert target.read_text(encoding="utf-8") == "<html>ok</html>"
        assert list(out_dir.glob("*.tmp")) == []

    def test_rejects_unsafe_task_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path))
        try:
            write_screen_html("../escape", "<html></html>")
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for unsafe task_id")


class TestGenerateScreenFromLatestRun:
    def test_renders_from_run_record(self, tmp_path, monkeypatch):
        runs_file = tmp_path / "task_runs.jsonl"
        records = [
            {"task_id": "Daily_brief", "started_at": "2026-07-16T10:00:00", "run_trace": {}},
            {
                "task_id": "Daily_brief",
                "started_at": "2026-07-17T10:00:00",
                "run_trace": {"final_markdown": SAMPLE_MARKDOWN},
            },
        ]
        # list_task_runs sorts by started_at desc, so the markdown record comes first.
        runs_file.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
        )
        monkeypatch.setenv("TASK_RUNS_FILE", str(runs_file))
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        monkeypatch.setattr(
            "insightbot.config.load_tasks_config",
            lambda task_id, bot_dir=None: {
                "_task_name": "营销日报",
                "settings": {"report_title": "营销情报站"},
                "_task_screen": {"enabled": True, "refresh_seconds": 120},
            },
        )
        target = generate_screen_from_latest_run("Daily_brief")
        assert target is not None
        page = target.read_text(encoding="utf-8")
        assert "营销行业" in page
        assert "💡" not in page
        assert '<meta http-equiv="refresh" content="120">' in page

    def test_returns_none_without_usable_history(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TASK_RUNS_FILE", str(tmp_path / "missing.jsonl"))
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        assert generate_screen_from_latest_run("Daily_brief") is None


class TestTaskRunnerScreenHook:
    def _fake_config(self, screen_cfg):
        return {
            "_task_pipeline": "editorial",
            "_task_channels": ["ch1"],
            "_task_screen": screen_cfg,
            "feeds": {},
            "ai": {"api_url": "...", "api_key": "...", "model": "..."},
            "settings": {"report_title": "营销情报站"},
        }

    def _run(self, config):
        from insightbot.task_runner import run_task

        with patch("insightbot.task_runner._run_editorial_pipeline") as mock_ep:
            mock_ep.return_value = {"ok": True, "final_markdown": SAMPLE_MARKDOWN, "error": None}
            with patch("insightbot.task_runner.send_message_to_channel") as mock_send, \
                 patch("insightbot.task_runner.get_channel") as mock_channel, \
                 patch("insightbot.task_runner.append_run_record"), \
                 patch("insightbot.screen_images.fetch_og_image_urls", return_value={}), \
                 patch("insightbot.screen_images.cache_news_images", return_value={}):
                mock_channel.return_value.delivery_profile = {
                    "preferred_format": "markdown",
                    "channel_type": "wecom",
                }
                mock_send.return_value = True
                return run_task("Daily_brief", lambda: config, dry_run=False)

    def test_enabled_screen_writes_page(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        result = self._run(self._fake_config({"enabled": True}))
        page = tmp_path / "screen" / "Daily_brief.html"
        assert page.exists()
        assert "营销行业" in page.read_text(encoding="utf-8")
        assert result["screen_path"] == str(page)
        assert result["ok"] is True

    def test_enabled_screen_writes_index(self, tmp_path, monkeypatch):
        tasks = {"tasks": {"Daily_brief": {"name": "营销日报", "screen": {"enabled": True}}}}
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("TASKS_FILE", str(tasks_file))
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        result = self._run(self._fake_config({"enabled": True}))
        index = tmp_path / "screen" / "index.html"
        assert index.exists()
        assert 'href="Daily_brief.html"' in index.read_text(encoding="utf-8")
        assert result["ok"] is True

    def test_enabled_screen_includes_scanned_images(self, tmp_path, monkeypatch):
        img_dir = tmp_path / "screen" / "img"
        img_dir.mkdir(parents=True)
        (img_dir / "photo.jpg").write_text("x")
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        result = self._run(self._fake_config({"enabled": True}))
        page = (tmp_path / "screen" / "Daily_brief.html").read_text(encoding="utf-8")
        assert 'var FALLBACK_IMAGES = ["img/photo.jpg"];' in page
        assert result["ok"] is True

    def test_enabled_screen_writes_section_images(self, tmp_path, monkeypatch):
        """hook 把 stage_results 里的 image_url 传给渲染,写入 SECTION_IMAGES。"""
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        monkeypatch.setattr(
            "insightbot.screen_images.cache_news_images",
            lambda urls, cache_dir: {u: "cached1.jpg" for u in urls},
        )
        monkeypatch.setattr("insightbot.screen_images.fetch_og_image_urls", lambda urls: {})
        from insightbot.task_runner import run_task

        config = self._fake_config({"enabled": True})
        stage = {
            "ok": True,
            "final_markdown": SAMPLE_MARKDOWN,
            "error": None,
            "category_results": {
                "💡 营销行业": {
                    "selected_items": [
                        {
                            "title": "某品牌 campaign 案例",
                            "url": "https://example.com/a",
                            "summary": "…",
                            "image_url": "https://cdn.example.com/a.jpg",
                        }
                    ]
                }
            },
        }
        with patch("insightbot.task_runner._run_editorial_pipeline", return_value=stage), \
             patch("insightbot.task_runner.send_message_to_channel", return_value=True), \
             patch("insightbot.task_runner.get_channel") as mock_channel, \
             patch("insightbot.task_runner.append_run_record"):
            mock_channel.return_value.delivery_profile = {"preferred_format": "markdown", "channel_type": "wecom"}
            result = run_task("Daily_brief", lambda: config, dry_run=False)
        page = (tmp_path / "screen" / "Daily_brief.html").read_text(encoding="utf-8")
        assert 'var SECTION_IMAGES = [["img/news/cached1.jpg"], []];' in page
        assert result["ok"] is True

    def test_disabled_screen_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        result = self._run(self._fake_config({"enabled": False}))
        assert not (tmp_path / "screen" / "Daily_brief.html").exists()
        assert result["screen_path"] is None
        assert result["ok"] is True

    def test_screen_failure_does_not_break_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SCREEN_OUTPUT_DIR", str(tmp_path / "screen"))
        with patch("insightbot.screen.generate_screen_for_task", side_effect=RuntimeError("boom")):
            result = self._run(self._fake_config({"enabled": True}))
        assert result["ok"] is True
        assert result["screen_path"] is None
        assert result["channel_results"][0]["ok"] is True
