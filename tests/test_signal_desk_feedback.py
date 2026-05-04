import pytest

import insightbot.signal_desk.feedback as feedback_module
from insightbot.signal_desk.feedback import (
    append_feedback,
    list_feedback,
    list_saved_signals,
    save_signal,
    summarize_feedback,
)
from insightbot.signal_desk.models import SignalItem
from insightbot.paths import signal_desk_saved_signals_file_path


def make_signal() -> SignalItem:
    return SignalItem(
        id="sig_001",
        room_id="client_radar_beauty",
        run_id="run_001",
        what_happened="Brand launches AI shopping assistant",
        why_it_matters="It affects retail conversion.",
        client_relevance="Beauty and retail clients.",
        suggested_action="Use as a client conversation starter.",
        judgement_lens=["client_relevance"],
        source={"title": "Example", "url": "https://example.com"},
        confidence="high",
        save_tags=["client-service"],
    )


def test_save_signal_and_list(tmp_path):
    saved = save_signal(make_signal(), tags=["pitch"], notes="Use next week", bot_dir=str(tmp_path))

    items = list_saved_signals(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert saved.id.startswith("saved_")
    assert len(items) == 1
    assert items[0]["room_id"] == "client_radar_beauty"
    assert items[0]["tags"] == ["pitch"]
    assert items[0]["notes"] == "Use next week"
    assert items[0]["signal"]["what_happened"] == "Brand launches AI shopping assistant"


def test_append_feedback_and_summarize(tmp_path):
    append_feedback("sig_001", "client_radar_beauty", "good_for_pitch", bot_dir=str(tmp_path))
    append_feedback("sig_002", "client_radar_beauty", "good_for_pitch", bot_dir=str(tmp_path))
    append_feedback("sig_003", "client_radar_beauty", "not_relevant", bot_dir=str(tmp_path))

    records = list_feedback(room_id="client_radar_beauty", bot_dir=str(tmp_path))
    summary = summarize_feedback(room_id="client_radar_beauty", bot_dir=str(tmp_path))

    assert len(records) == 3
    assert summary == {"good_for_pitch": 2, "not_relevant": 1}


def test_append_feedback_rejects_unsupported_action(tmp_path):
    with pytest.raises(ValueError, match="Unsupported feedback action"):
        append_feedback("sig_001", "client_radar_beauty", "send_to_everyone", bot_dir=str(tmp_path))


def test_list_saved_signals_skips_malformed_jsonl(tmp_path):
    save_signal(make_signal(), bot_dir=str(tmp_path))
    path = signal_desk_saved_signals_file_path(str(tmp_path))
    with open(path, "a", encoding="utf-8") as f:
        f.write("{ this is not json }\n")

    items = list_saved_signals(bot_dir=str(tmp_path))

    assert len(items) == 1
    assert items[0]["signal"]["id"] == "sig_001"


def test_append_feedback_holds_lock_while_writing(tmp_path, monkeypatch):
    original_open = feedback_module.Path.open
    lock_seen_during_write = []

    class LockCheckingWriter:
        def __init__(self, wrapped, path):
            self._wrapped = wrapped
            self._path = path

        def __enter__(self):
            self._wrapped.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._wrapped.__exit__(exc_type, exc, tb)

        def write(self, value):
            lock_seen_during_write.append(feedback_module.Path(str(self._path) + ".lock").exists())
            return self._wrapped.write(value)

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    def open_with_lock_check(path, *args, **kwargs):
        opened = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if path.name == "feedback.jsonl" and "a" in mode:
            return LockCheckingWriter(opened, path)
        return opened

    monkeypatch.setattr(feedback_module.Path, "open", open_with_lock_check)

    append_feedback("sig_001", "client_radar_beauty", "good_for_pitch", bot_dir=str(tmp_path))

    assert lock_seen_during_write == [True]
