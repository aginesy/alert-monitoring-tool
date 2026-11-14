from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import pytest

from services.demo_service import (
    generate_demo_alerts,
    MockMattermostClient,
    MockConfluenceClient,
)
from main import main


def test_generate_demo_alerts_fields_and_order() -> None:
    alerts = generate_demo_alerts(hours=168)
    assert len(alerts) > 0

    # Validate required fields
    for a in alerts:
        assert "id" in a
        assert "message" in a
        assert "timestamp" in a
        assert "created_at" in a
        assert "permalink" in a
        assert len(a["titles"]) >= 1

    # Validate reverse chronological ordering
    timestamps = [a["timestamp"] for a in alerts]
    assert timestamps == sorted(timestamps, reverse=True)


def test_generate_demo_alerts_respects_hours_boundary() -> None:
    short_alerts = generate_demo_alerts(hours=12)
    long_alerts = generate_demo_alerts(hours=168)
    assert len(short_alerts) < len(long_alerts)


def test_mock_confluence_client_workflow(tmp_path: Path) -> None:
    client = MockConfluenceClient()
    page = client.get_page("123456789")
    assert page["id"] == "123456789"
    assert "storage" in page["body"]

    updated = client.update_page(
        page_id="123456789",
        title="New Title",
        space_key="ALERTS",
        storage_html="<p>Test</p>",
        next_version=2,
    )
    assert updated["title"] == "New Title"
    assert updated["version"]["number"] == 2

    attachment = client.attach_file("123456781", "report.html", b"<html></html>")
    assert attachment["title"] == "report.html"
    assert len(client.attached_files) == 1

    url = client.build_page_url(page)
    assert "confluence_suivi.html" in url

    # Test HTML export
    exported = client.export_html_pages(tmp_path)
    assert len(exported) == 3
    assert (tmp_path / "confluence_suivi.html").exists()
    assert (tmp_path / "confluence_archive.html").exists()
    assert (tmp_path / "confluence_stats.html").exists()


def test_main_demo_mode_full_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_html = tmp_path / "test_demo_report.html"
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--demo", "--output", str(output_html)],
    )

    exit_code = main()

    assert exit_code == 0
    assert output_html.exists()
    content = output_html.read_text(encoding="utf-8")
    assert "Alerting Report" in content
    assert "api-gateway" in content
    assert "payment-service" in content
    assert "confluence-kpi-item" in content

    # Verify that the 3 simulated Confluence views are exported
    suivi_html = tmp_path / "confluence_suivi.html"
    archive_html = tmp_path / "confluence_archive.html"
    stats_html = tmp_path / "confluence_stats.html"

    assert suivi_html.exists()
    assert archive_html.exists()
    assert stats_html.exists()

    suivi_content = suivi_html.read_text(encoding="utf-8")
    assert "Weekly Alert Tracking and Team Action Plan" in suivi_content
    assert "aui-lozenge" in suivi_content

    archive_content = archive_html.read_text(encoding="utf-8")
    assert "Resolved Alerts Archive" in archive_content

    stats_content = stats_html.read_text(encoding="utf-8")
    assert "Weekly Alerting Evolution and Metrics" in stats_content


def test_main_demo_mode_without_confluence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_html = tmp_path / "test_demo_no_conf.html"
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--demo", "--confluence-tracking=false", "--output", str(output_html)],
    )

    exit_code = main()

    assert exit_code == 0
    assert output_html.exists()
    content = output_html.read_text(encoding="utf-8")
    assert "Alerting Report" in content
    assert "api-gateway" in content
