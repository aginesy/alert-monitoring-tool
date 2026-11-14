from __future__ import annotations

import argparse
import os
import pytest
from main import parse_arguments, str_to_bool


def test_str_to_bool() -> None:
    assert str_to_bool(True) is True
    assert str_to_bool(False) is False
    assert str_to_bool("true") is True
    assert str_to_bool("True") is True
    assert str_to_bool("TRUE") is True
    assert str_to_bool("1") is True
    assert str_to_bool("yes") is True
    assert str_to_bool("false") is False
    assert str_to_bool("False") is False
    assert str_to_bool("FALSE") is False
    assert str_to_bool("0") is False
    assert str_to_bool("no") is False

    with pytest.raises(argparse.ArgumentTypeError):
        str_to_bool("invalid")


def test_parse_arguments_default_confluence_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFLUENCE_TRACKING", raising=False)
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--hours", "24"])
    args = parse_arguments()
    assert args.confluence_tracking is False
    assert args.suivi_confluence is False
    assert args.hours == 24


def test_parse_arguments_with_confluence_tracking_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFLUENCE_TRACKING", raising=False)
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--hours", "48", "--confluence-tracking"])
    args = parse_arguments()
    assert args.confluence_tracking is True
    assert args.suivi_confluence is True
    assert args.hours == 48


@pytest.mark.parametrize(
    "arg_value,expected",
    [
        ("--confluence-tracking=true", True),
        ("--confluence-tracking=True", True),
        ("--confluence-tracking=1", True),
        ("--confluence-tracking=false", False),
        ("--confluence-tracking=False", False),
        ("--confluence-tracking=0", False),
        ("--suivi-confluence=true", True),
        ("--suivi-confluence=false", False),
    ],
)
def test_parse_arguments_with_confluence_tracking_equals_value(
    monkeypatch: pytest.MonkeyPatch, arg_value: str, expected: bool
) -> None:
    monkeypatch.delenv("CONFLUENCE_TRACKING", raising=False)
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", arg_value])
    args = parse_arguments()
    assert args.confluence_tracking is expected
    assert args.suivi_confluence is expected


def test_parse_arguments_with_confluence_tracking_separate_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONFLUENCE_TRACKING", raising=False)
    monkeypatch.delenv("SUIVI_CONFLUENCE", raising=False)
    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking", "false"])
    args = parse_arguments()
    assert args.confluence_tracking is False

    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking", "true"])
    args = parse_arguments()
    assert args.confluence_tracking is True


def test_parse_arguments_with_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_TRACKING", "true")
    monkeypatch.setattr("sys.argv", ["main.py"])
    args = parse_arguments()
    assert args.confluence_tracking is True


def test_parse_arguments_cli_overrides_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONFLUENCE_TRACKING", "true")
    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=false"])
    args = parse_arguments()
    assert args.confluence_tracking is False

    monkeypatch.setenv("CONFLUENCE_TRACKING", "false")
    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=true"])
    args = parse_arguments()
    assert args.confluence_tracking is True


def test_parse_arguments_invalid_confluence_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=notabool"])
    with pytest.raises(SystemExit):
        parse_arguments()


def test_main_execution_with_confluence_tracking_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=false"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )

    sample_alert = {
        "id": "post_1",
        "category": "Test alert",
        "title": "Test alert",
        "message": "**Alert :** Test alert",
        "created_at": "28/10/2026 at 10:00:00",
        "timestamp": 1793181600000,
        "status": "FIRING",
        "status_type": "firing",
        "permalink": "https://mattermost.test/post_1",
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.fetch_messages.return_value = [sample_alert]

    with patch("main.MattermostClient", return_value=mock_client), patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]
    assert "Alerting Report" in saved_html
    assert "Generated on:" in saved_html

    # Strict check: No Confluence elements should appear in standard mode DOM
    assert "📋 Confluence Review ↗" not in saved_html
    assert '<div class="confluence-kpi-bar">' not in saved_html
    assert '<div class="confluence-tracking-card">' not in saved_html
    assert 'class="tracking-pill' not in saved_html
    assert "Decided Action Items:" not in saved_html
    assert "Assignee:" not in saved_html


def test_main_execution_with_confluence_tracking_true_missing_confluence_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {"url": "", "token": "", "page_id": ""},
    )

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.fetch_messages.return_value = []

    with patch("main.MattermostClient", return_value=mock_client), patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]
    assert "Alerting Report" in saved_html
    assert "Generated on:" in saved_html


def test_main_execution_with_confluence_tracking_true_and_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {
            "url": "https://confluence.test",
            "token": "conf_token",
            "page_id": "123456789",
            "archive_page_id": "123456780",
            "stats_page_id": "123456781",
        },
    )

    mock_mm_client = MagicMock()
    mock_mm_client.__enter__.return_value = mock_mm_client
    mock_mm_client.fetch_messages.return_value = []

    mock_conf_client = MagicMock()
    mock_conf_client.__enter__.return_value = mock_conf_client
    mock_conf_client.build_page_url.side_effect = lambda data: f"https://confluence.test/pages/{data.get('id', '0')}"

    # Simulation: Main page contains an old resolved alert (10/05/2026, > 3 months)
    main_page_storage = """
    <table>
      <thead>
        <tr>
          <th>Status</th><th>Alert Category</th><th>Occurrences</th>
          <th>Last Seen in Mattermost</th>
          <th>Assignee</th><th>Due Date</th><th>Action Items (Review Meeting)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">RESOLVED</ac:parameter></ac:structured-macro></td>
          <td><strong>Old alert to archive</strong></td>
          <td>10 this week</td>
          <td>10/05/2026 14:00:00</td>
          <td>Alice</td><td>-</td><td><p>Issue resolved</p></td>
        </tr>
      </tbody>
    </table>
    """

    def mock_get_page(page_id=None):
        if page_id == "123456780":
            return {
                "id": "123456780",
                "title": "Resolved Alerts Archive (> 1 Month)",
                "space": {"key": "ALERTS"},
                "version": {"number": 1},
                "body": {"storage": {"value": "<table></table>"}},
            }
        elif page_id == "123456781":
            return {
                "id": "123456781",
                "title": "Alert Tracking Statistics",
                "space": {"key": "ALERTS"},
                "version": {"number": 2},
                "body": {"storage": {"value": "<table><thead><tr><th>Execution Date</th></tr></thead><tbody></tbody></table>"}},
            }
        return {
            "id": "123456789",
            "title": "Alert Analysis",
            "space": {"key": "ALERTS"},
            "version": {"number": 3},
            "body": {"storage": {"value": main_page_storage}},
        }

    mock_conf_client.get_page.side_effect = mock_get_page

    with patch("main.MattermostClient", return_value=mock_mm_client), \
         patch("main.ConfluenceClient", return_value=mock_conf_client), \
         patch("main.save_report"):
        exit_code = main()

    assert exit_code == 0
    assert mock_conf_client.update_page.call_count == 3
    calls = mock_conf_client.update_page.call_args_list

    # Call 1: Archive page updated with old resolved alert
    archive_call = calls[0].kwargs
    assert archive_call["page_id"] == "123456780"
    assert "Old alert to archive" in archive_call["storage_html"]
    assert "<th>Action Items (Review Meeting)</th>" in archive_call["storage_html"]

    # Call 2: Statistics page incremented with metrics and attachment
    stats_call = calls[1].kwargs
    assert stats_call["page_id"] == "123456781"
    assert "<tbody><tr>" in stats_call["storage_html"]
    assert "rapport_alertes_" in stats_call["storage_html"]
    assert "<ri:attachment" in stats_call["storage_html"]

    # Validate attachment API call
    assert mock_conf_client.attach_file.called
    attach_call = mock_conf_client.attach_file.call_args.kwargs
    assert attach_call["page_id"] == "123456781"
    assert attach_call["filename"].startswith("rapport_alertes_")

    # Call 3: Active page updated
    main_call = calls[2].kwargs
    assert main_call["page_id"] == "123456789"
    assert "Old alert to archive" not in main_call["storage_html"]
    assert "https://confluence.test/pages/123456780" in main_call["storage_html"]
    assert "https://confluence.test/pages/123456781" in main_call["storage_html"]


def test_main_report_html_contains_confluence_tracking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch
    from main import main

    monkeypatch.setattr("sys.argv", ["main.py", "--confluence-tracking=true"])
    monkeypatch.setattr(
        "config.config_mattermost.mattermost_client_config",
        {
            "url": "https://mattermost.test",
            "token": "test_token",
            "channel_id": "test_channel",
            "team": "test_team",
        },
    )
    monkeypatch.setattr(
        "config.config_confluence.confluence_config",
        {
            "url": "https://confluence.test",
            "token": "conf_token",
            "page_id": "123456789",
            "archive_page_id": "",
            "stats_page_id": "",
        },
    )

    sample_alert = {
        "id": "post_1",
        "category": "Active tracked alert",
        "title": "Active tracked alert",
        "message": "**Alert :** Active tracked alert",
        "created_at": "28/10/2026 at 10:00:00",
        "timestamp": 1793181600000,
        "status": "FIRING",
        "status_type": "firing",
        "permalink": "https://mattermost.test/post_1",
    }

    mock_mm_client = MagicMock()
    mock_mm_client.__enter__.return_value = mock_mm_client
    mock_mm_client.fetch_messages.return_value = [sample_alert]

    mock_conf_client = MagicMock()
    mock_conf_client.__enter__.return_value = mock_conf_client
    mock_conf_client.build_page_url.return_value = "https://confluence.test/pages/123456789"

    main_page_storage = """
    <table>
      <thead>
        <tr>
          <th>Status</th><th>Alert Category</th><th>Occurrences</th>
          <th>Last Seen in Mattermost</th>
          <th>Assignee</th><th>Due Date</th><th>Action Items (Review Meeting)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><ac:structured-macro ac:name="status"><ac:parameter ac:name="title">IN PROGRESS</ac:parameter><ac:parameter ac:name="colour">Yellow</ac:parameter></ac:structured-macro></td>
          <td><strong>Active tracked alert</strong></td>
          <td>5 this week</td>
          <td>28/10/2026 10:00:00</td>
          <td>Alice</td><td>15/11/2026</td>
          <td><ul><li>Database index tuning</li></ul></td>
        </tr>
      </tbody>
    </table>
    """

    mock_conf_client.get_page.return_value = {
        "id": "123456789",
        "title": "Alert Analysis",
        "space": {"key": "ALERTS"},
        "version": {"number": 1},
        "body": {"storage": {"value": main_page_storage}},
    }

    with patch("main.MattermostClient", return_value=mock_mm_client), \
         patch("main.ConfluenceClient", return_value=mock_conf_client), \
         patch("main.save_report") as mock_save:
        exit_code = main()

    assert exit_code == 0
    assert mock_save.called
    saved_html, _ = mock_save.call_args[0]

    # Verify status, assignee, and actions appear in report
    assert "status-in-progress" in saved_html
    assert "Alice" in saved_html
    assert "Database index tuning" in saved_html
    assert "confluence-tracking-card" in saved_html
