from unittest.mock import MagicMock, patch

from insightbot.wecom_callback import _handle_command


class TestWeComCallbackAuth:
    def test_run_requires_allowed_user(self):
        scheduler = MagicMock()

        with patch.dict("os.environ", {}, clear=True):
            reply = _handle_command("run daily_brief", scheduler, None, from_user="alice")

        assert "未授权" in reply
        scheduler.run_task_by_id.assert_not_called()

    def test_allowed_user_can_run(self):
        scheduler = MagicMock()
        scheduler.run_task_by_id.return_value = {"ok": True}

        with patch.dict("os.environ", {"WECOM_ALLOWED_USERS": "alice,bob"}, clear=True):
            reply = _handle_command("run daily_brief", scheduler, None, from_user="alice")

        assert "执行成功" in reply
        scheduler.run_task_by_id.assert_called_once_with("daily_brief", dry_run=False)

    def test_dry_run_does_not_require_allowed_user(self):
        scheduler = MagicMock()
        scheduler.run_task_by_id.return_value = {"ok": True, "final_markdown": "preview"}

        with patch.dict("os.environ", {}, clear=True):
            reply = _handle_command("dry daily_brief", scheduler, None, from_user="alice")

        assert "试运行成功" in reply
        scheduler.run_task_by_id.assert_called_once_with("daily_brief", dry_run=True)
