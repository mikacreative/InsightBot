from insightbot.run_diagnosis import build_no_push_diagnosis, parse_recent_run_summary


def test_parse_recent_run_summary_extracts_category_states(tmp_path):
    log_file = tmp_path / "bot.log"
    log_file.write_text(
        "\n".join(
            [
                "2026-04-07 09:00:00,000 - INFO - 🚀 === 营销情报抓取任务开始 ===",
                "2026-04-07 09:00:01,000 - INFO - 📁 正在处理板块: 【💡 营销行业】",
                "2026-04-07 09:00:02,000 - INFO - ⏳ 板块 【💡 营销行业】 排重后剩余 14 条数据交由 AI 筛选...",
                "2026-04-07 09:00:03,000 - INFO - 🈳 AI 判定 [💡 营销行业] 无合格内容，已拦截。",
                "2026-04-07 09:00:04,000 - INFO - 📁 正在处理板块: 【📢 政策导向】",
                "2026-04-07 09:00:05,000 - INFO - 📭 板块 【📢 政策导向】 今日无更新数据",
                "2026-04-07 09:00:06,000 - INFO - 📭 今日全网无更新内容被推送",
            ]
        ),
        encoding="utf-8",
    )

    summary = parse_recent_run_summary(str(log_file))

    assert summary["overall_no_push"] is True
    assert summary["categories"]["💡 营销行业"]["status"] == "blocked_by_prompt"
    assert summary["categories"]["💡 营销行业"]["candidate_count"] == 14
    assert summary["categories"]["📢 政策导向"]["status"] == "no_candidates"


def test_build_no_push_diagnosis_prioritizes_source_error():
    health_snapshot = {
        "categories": [
            {
                "category": "💡 营销行业",
                "feeds": [
                    {
                        "status": "error",
                        "url": "https://example.com/feed.xml",
                        "error_type": "timeout",
                        "error_message": "timed out",
                    }
                ],
            }
        ]
    }
    run_summary = {
        "overall_no_push": True,
        "categories": {
            "💡 营销行业": {"category": "💡 营销行业", "status": "blocked_by_prompt"},
        },
        "runtime_errors": [],
    }

    cards = build_no_push_diagnosis(
        health_snapshot=health_snapshot,
        run_summary=run_summary,
        configured_categories=["💡 营销行业"],
    )

    assert cards[0]["kind"] == "source_error"
    assert cards[1]["kind"] == "prompt_block"
