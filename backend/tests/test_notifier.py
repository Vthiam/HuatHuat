from unittest import mock

from app import notifier


def test_notify_calls_osascript_on_darwin():
    with mock.patch.object(notifier.platform, "system", return_value="Darwin"), mock.patch.object(
        notifier.subprocess, "run"
    ) as mock_run:
        result = notifier.notify("Test Title", "Test message")

    assert result is True
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "osascript"
    assert "Test Title" in args[2]
    assert "Test message" in args[2]


def test_notify_noops_on_non_darwin():
    with mock.patch.object(notifier.platform, "system", return_value="Linux"), mock.patch.object(
        notifier.subprocess, "run"
    ) as mock_run:
        result = notifier.notify("Title", "Message")

    assert result is False
    mock_run.assert_not_called()


def test_notify_returns_false_instead_of_raising_on_failure():
    with mock.patch.object(notifier.platform, "system", return_value="Darwin"), mock.patch.object(
        notifier.subprocess, "run", side_effect=OSError("boom")
    ):
        result = notifier.notify("Title", "Message")

    assert result is False


def test_osa_quote_escapes_quotes_and_backslashes():
    quoted = notifier._osa_quote('He said "hi" and used a \\ backslash')
    assert quoted == '"He said \\"hi\\" and used a \\\\ backslash"'
