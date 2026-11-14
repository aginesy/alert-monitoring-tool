from __future__ import annotations

from datetime import datetime
import pytest
from services.tracking_service import TrackingService


def test_normalize_category_name() -> None:
    # 1. Stripping dynamic metric values
    raw_1 = "Disk space used on opmilo10d:/ARCHIVE is more than 90% (current : 91)"
    expected_1 = "Disk space used on opmilo10d:/ARCHIVE is more than 90%"
    assert TrackingService.normalize_category_name(raw_1) == expected_1

    # 2. Stripping ephemeral kubernetes pod replica hashes
    raw_2 = "Pod bi-agent-8578c8c7ff-wld7g restarted for reason Error"
    expected_2 = "Pod bi-agent restarted for reason Error"
    assert TrackingService.normalize_category_name(raw_2) == expected_2

    # 3. HTML entities and multiple spaces
    raw_3 = "Number of errors &#39;5xx&#39;   for service api-store"
    expected_3 = "Number of errors '5xx' for service api-store"
    assert TrackingService.normalize_category_name(raw_3) == expected_3


def test_get_category_slug() -> None:
    name = "Response time of api-store service is higher than 1s"
    slug = TrackingService.get_category_slug(name)
    assert "response-time-of-api-store-service" in slug
    assert not any(c in slug for c in [" ", "'", "à", "é"])


def test_parse_confluence_storage() -> None:
    sample_storage = """
    <p>Introduction</p>
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Alert Category</th>
          <th>Occurrences</th>
          <th>Last Seen in Mattermost</th>
          <th>Assignee</th>
          <th>Due Date</th>
          <th>Action Items (Review Meeting)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <ac:structured-macro ac:name="status">
              <ac:parameter ac:name="title">IN PROGRESS</ac:parameter>
              <ac:parameter ac:name="colour">Yellow</ac:parameter>
            </ac:structured-macro>
          </td>
          <td>
            <ac:structured-macro ac:name="anchor">
              <ac:parameter ac:name="">api-store-latency</ac:parameter>
            </ac:structured-macro>
            <strong>Response time of api-store service is higher than 1s</strong>
          </td>
          <td>50 this week</td>
          <td>20/10/2026 14:00</td>
          <td>Alice</td>
          <td><time datetime="2026-11-05" /></td>
          <td><ul><li>Optimize MongoDB queries</li></ul></td>
        </tr>
      </tbody>
    </table>
    """
    registry = TrackingService.parse_confluence_storage(sample_storage)
    assert "api-store-latency" in registry
    entry = registry["api-store-latency"]
    assert entry["name"] == "Response time of api-store service is higher than 1s"
    assert entry["status"] == "IN PROGRESS"
    assert entry["assignee"] == "Alice"
    assert entry["due_date"] == "2026-11-05"
    assert "Optimize MongoDB queries" in entry["actions_html"]


def test_reconciliation_new_category() -> None:
    categories = [
        {"name": "Brand new unknown alert", "count": 12}
    ]
    existing = {}
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")

    assert len(tracked) == 1
    assert tracked[0]["status"] == "NEW"
    assert tracked[0]["count_this_week"] == 12
    assert tracked[0]["total_occurrences"] == 12
    assert stats["NEW"] == 1
    assert stats["ACTIVE_THIS_WEEK"] == 1


def test_reconciliation_new_without_action_becomes_unattended() -> None:
    categories = [{"name": "Alert without action", "count": 4}]
    slug = TrackingService.get_category_slug("Alert without action")
    existing = {
        slug: {
            "slug": slug,
            "name": "Alert without action",
            "status": "NEW",
            "total_occurrences": 10,
            "actions_html": "<p><em>To be defined during review meeting</em></p>",
            "assignee": "",
            "last_seen": "20/10/2026",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "UNATTENDED"


def test_reconciliation_unattended_without_action_stays_unattended() -> None:
    categories = [{"name": "Already unattended alert", "count": 2}]
    slug = TrackingService.get_category_slug("Already unattended alert")
    existing = {
        slug: {
            "slug": slug,
            "name": "Already unattended alert",
            "status": "UNATTENDED",
            "total_occurrences": 15,
            "actions_html": "<p><em>To be defined during review meeting</em></p>",
            "assignee": "",
            "last_seen": "15/10/2026",
            "unattended_since": "2026-10-15",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "UNATTENDED"
    assert tracked[0]["unattended_since"] == "2026-10-15"


def test_reconciliation_new_with_real_action_becomes_in_progress() -> None:
    categories = [{"name": "Assigned alert", "count": 3}]
    slug = TrackingService.get_category_slug("Assigned alert")
    existing = {
        slug: {
            "slug": slug,
            "name": "Assigned alert",
            "status": "NEW",
            "total_occurrences": 10,
            "actions_html": "<ul><li>Code review and fix deployment</li></ul>",
            "assignee": "Alice",
            "last_seen": "20/10/2026",
        }
    }
    tracked, _ = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")
    assert tracked[0]["status"] == "IN PROGRESS"


def test_reconciliation_resolved_becomes_recurrent() -> None:
    categories = [
        {"name": "Recurring alert", "count": 5}
    ]
    slug = TrackingService.get_category_slug("Recurring alert")
    existing = {
        slug: {
            "slug": slug,
            "name": "Recurring alert",
            "status": "RESOLVED",
            "total_occurrences": 30,
            "actions_html": "<p>Patch deployed in v1.2</p>",
            "assignee": "Alice",
            "last_seen": "15/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")

    entry = tracked[0]
    assert entry["status"] == "RECURRING"
    assert entry["count_this_week"] == 5
    assert entry["total_occurrences"] == 35
    assert "Patch deployed in v1.2" in entry["actions_html"]
    assert entry["assignee"] == "Alice"
    assert stats["RECURRING"] == 1


def test_reconciliation_preserves_inactive_categories() -> None:
    categories: list[dict[str, Any]] = []
    slug = "dormant-alert"
    existing = {
        slug: {
            "slug": slug,
            "name": "Dormant Alert",
            "status": "IN PROGRESS",
            "total_occurrences": 10,
            "actions_html": "<p>Awaiting vendor support</p>",
            "assignee": "Bob",
            "last_seen": "12/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "27/10/2026 10:00")

    assert len(tracked) == 1
    entry = tracked[0]
    assert entry["slug"] == slug
    assert entry["count_this_week"] == 0
    assert entry["status"] == "IN PROGRESS"
    assert entry["is_active_now"] is False
    assert stats["ACTIVE_THIS_WEEK"] == 0
    assert stats["TOTAL"] == 1


def test_add_months() -> None:
    dt = datetime(2026, 10, 28)
    assert TrackingService._add_months(dt, 1) == datetime(2026, 11, 28)
    assert TrackingService._add_months(dt, -3) == datetime(2026, 7, 28)
    assert TrackingService._add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
    assert TrackingService._add_months(datetime(2026, 3, 31), -1) == datetime(2026, 2, 28)


def test_build_confluence_storage_html() -> None:
    tracked = [
        {
            "slug": "cat-test",
            "name": "Test Alert",
            "status": "IN PROGRESS",
            "count_this_week": 10,
            "total_occurrences": 20,
            "occurrences_display": "10 this week",
            "actions_html": "<p>Action 1</p>",
            "assignee": "Alice",
            "last_seen": "27/10/2026",
            "is_active_now": True,
        }
    ]
    stats = TrackingService.calculate_stats(tracked)
    artifact_url = "https://gitlab.example.com/username/alerting/-/jobs/artifacts/dev/raw/output/alertes.html"
    artifact_browse = "https://gitlab.example.com/username/alerting/-/jobs/artifacts/dev/browse/output"
    sync_date = "27/10/2026 11:00"

    html_out = TrackingService.build_confluence_storage_html(
        tracked,
        stats,
        sync_date_str=sync_date,
        artifact_url=artifact_url,
        artifact_browse_url=artifact_browse,
    )

    assert '<ac:structured-macro ac:name="info">' in html_out
    assert '<ac:structured-macro ac:name="status">' in html_out
    assert '<ac:parameter ac:name="colour">Yellow</ac:parameter>' in html_out
    assert '<ac:parameter ac:name="title">IN PROGRESS</ac:parameter>' in html_out
    assert '<ac:structured-macro ac:name="anchor">' in html_out
    assert 'Test Alert' in html_out
    assert 'Alice' in html_out
    assert '<p>Action 1</p>' in html_out
    assert artifact_url in html_out
    assert artifact_browse in html_out
    assert '<ac:structured-macro ac:name="panel">' in html_out
    assert 'Status Palette' in html_out
    assert '<th>Due Date</th>' in html_out
    assert '<th>Action Items (Review Meeting)</th>' in html_out
    assert 'Latest Visual HTML Report' in html_out
    assert f'Last execution: <strong>{sync_date}</strong>' in html_out


def test_sanitize_actions_html() -> None:
    dangerous = "<script>alert('xss')</script><p onclick='evil()'>Normal action <a href='javascript:steal()'>Link</a></p>"
    cleaned = TrackingService.sanitize_actions_html(dangerous)
    assert "<script>" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "<p>Normal action <a>Link</a></p>" in cleaned

    safe = "<ul><li>Task 1</li><li>Task 2 on <a href='https://jira.example.com/123'>Jira</a></li></ul>"
    cleaned_safe = TrackingService.sanitize_actions_html(safe)
    assert "<ul><li>Task 1</li>" in cleaned_safe
    assert "rel=\"noopener noreferrer\"" in cleaned_safe
    assert "target=\"_blank\"" in cleaned_safe


def test_reconciliation_uses_latest_occurrence_at() -> None:
    categories = [
        {
            "name": "Alert test date",
            "count": 3,
            "latest_occurrence_at": "27/10/2026 10:21:47",
        }
    ]
    tracked, _ = TrackingService.reconcile(categories, {}, "27/10/2026 14:00:00")
    assert tracked[0]["last_seen"] == "27/10/2026 10:21:47"


def test_parse_datetime() -> None:
    assert TrackingService.parse_datetime("27/10/2026 10:21:47") == datetime(2026, 10, 27, 10, 21, 47)
    assert TrackingService.parse_datetime("27/10/2026") == datetime(2026, 10, 27, 0, 0, 0)
    assert TrackingService.parse_datetime("2026-07-15 14:30:00") == datetime(2026, 7, 15, 14, 30, 0)
    assert TrackingService.parse_datetime('<time datetime="2026-06-01" /> 09:15:00') == datetime(2026, 6, 1, 9, 15, 0)
    assert TrackingService.parse_datetime("Previous") is None
    assert TrackingService.parse_datetime("-") is None
    assert TrackingService.parse_datetime("") is None


def test_is_older_than_months() -> None:
    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    assert TrackingService.is_older_than_months("2026-07-27", ref_date, months=3) is True
    assert TrackingService.is_older_than_months("15/06/2026 10:00:00", ref_date, months=3) is True
    assert TrackingService.is_older_than_months("2026-07-29", ref_date, months=3) is False
    assert TrackingService.is_older_than_months("01/10/2026 08:00:00", ref_date, months=3) is False
    assert TrackingService.is_older_than_months("Previous", ref_date, months=3) is False


def test_separate_archived_categories() -> None:
    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    categories = [
        {
            "slug": "res-old",
            "name": "Old resolved alert",
            "status": "RESOLVED",
            "last_seen": "15/09/2026 10:00:00",
            "is_active_now": False,
        },
        {
            "slug": "res-recent",
            "name": "Recent resolved alert",
            "status": "RESOLVED",
            "last_seen": "15/10/2026 10:00:00",
            "is_active_now": False,
        },
        {
            "slug": "encours-old",
            "name": "Old in-progress alert",
            "status": "IN PROGRESS",
            "last_seen": "15/08/2026 10:00:00",
            "is_active_now": False,
        },
    ]

    active, to_archive = TrackingService.separate_archived_categories(categories, ref_dt=ref_date)

    assert len(to_archive) == 1
    assert to_archive[0]["slug"] == "res-old"
    assert len(active) == 2
    active_slugs = {c["slug"] for c in active}
    assert "res-recent" in active_slugs
    assert "encours-old" in active_slugs


def test_parse_confluence_archive_storage() -> None:
    sample_archive_storage = """
    <table>
      <thead>
        <tr>
          <th>Alert Category</th>
          <th>Occurrences</th>
          <th>Last Seen in Mattermost</th>
          <th>Assignee</th>
          <th>Due Date</th>
          <th>Action Items (Review Meeting)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>
            <ac:structured-macro ac:name="anchor">
              <ac:parameter ac:name="">old-alert</ac:parameter>
            </ac:structured-macro>
            <strong>Archived Old Alert</strong>
          </td>
          <td>25 total</td>
          <td><time datetime="2026-05-10" /> 14:00</td>
          <td>Bob</td>
          <td><time datetime="2026-06-01" /></td>
          <td><p>Issue permanently fixed</p></td>
        </tr>
      </tbody>
    </table>
    """
    registry = TrackingService.parse_confluence_archive_storage(sample_archive_storage)
    assert "old-alert" in registry
    entry = registry["old-alert"]
    assert entry["name"] == "Archived Old Alert"
    assert entry["status"] == "RESOLVED"
    assert entry["assignee"] == "Bob"
    assert entry["due_date"] == "2026-06-01"
    assert "Issue permanently fixed" in entry["actions_html"]


def test_build_confluence_archive_storage_html() -> None:
    archived = [
        {
            "slug": "archive-cat",
            "name": "Archived Alert",
            "occurrences_display": "15 total",
            "last_seen": "10/05/2026 12:00:00",
            "assignee": "Charlie",
            "due_date": "2026-05-20",
            "actions_html": "<p>Fix deployed and verified</p>",
        }
    ]
    html_out = TrackingService.build_confluence_archive_storage_html(
        archived_categories=archived,
        sync_date_str="28/10/2026 at 10:00:00",
        main_page_url="https://confluence.example.com/main",
    )
    assert "Archive of Review Decisions for Alerts Resolved &gt; 1 Month" in html_out
    assert "Archived Alert" in html_out
    assert "15 total" in html_out
    assert "Charlie" in html_out
    assert "Fix deployed and verified" in html_out
    assert "<th>Alert Category</th>" in html_out
    assert "<th>Action Items (Review Meeting)</th>" in html_out
    assert "<th>Status</th>" not in html_out
    assert "https://confluence.example.com/main" in html_out


def test_check_unattended_duration() -> None:
    u_date = datetime(2026, 9, 28, 10, 0, 0)

    # 1. Under 4 weeks (21 days): no warning, no deletion
    del_1, warn_1, days_1 = TrackingService.check_unattended_duration(u_date, datetime(2026, 10, 19, 10, 0, 0))
    assert del_1 is False
    assert warn_1 is False
    assert days_1 == 9

    # 2. At 4 weeks (28 days): warning active with 2 days left
    del_2, warn_2, days_2 = TrackingService.check_unattended_duration(u_date, datetime(2026, 10, 26, 10, 0, 0))
    assert del_2 is False
    assert warn_2 is True
    assert days_2 == 2

    # 3. At 29 days: warning active with 1 day left
    del_3, warn_3, days_3 = TrackingService.check_unattended_duration(u_date, datetime(2026, 10, 27, 10, 0, 0))
    assert del_3 is False
    assert warn_3 is True
    assert days_3 == 1

    # 4. At over 1 month (31 days): deletion required
    del_4, warn_4, _ = TrackingService.check_unattended_duration(u_date, datetime(2026, 10, 29, 10, 0, 0))
    assert del_4 is True
    assert warn_4 is False


def test_filter_and_tag_unattended_categories() -> None:
    ref_date = datetime(2026, 10, 28, 12, 0, 0)
    categories = [
        # UNATTENDED over 1 month -> deleted
        {
            "slug": "unattended-expired",
            "name": "Expired Unattended Alert",
            "status": "UNATTENDED",
            "unattended_since": "2026-09-20",
        },
        # UNATTENDED at 4 weeks (28 days) -> warning active
        {
            "slug": "unattended-warning",
            "name": "4-week Unattended Alert",
            "status": "UNATTENDED",
            "unattended_since": "2026-09-30",
        },
        # UNATTENDED recent (1 week) -> kept without warning
        {
            "slug": "unattended-recent",
            "name": "Recent Unattended Alert",
            "status": "UNATTENDED",
            "unattended_since": "2026-10-21",
        },
        # IN PROGRESS old -> kept (only UNATTENDED is purged)
        {
            "slug": "encours-old",
            "name": "Old In Progress Alert",
            "status": "IN PROGRESS",
            "last_seen": "2026-09-10",
        },
    ]

    remaining, deleted = TrackingService.filter_and_tag_unattended_categories(categories, ref_dt=ref_date)

    assert len(deleted) == 1
    assert deleted[0]["slug"] == "unattended-expired"
    assert len(remaining) == 3
    slugs = {c["slug"] for c in remaining}
    assert "unattended-warning" in slugs
    assert "unattended-recent" in slugs
    assert "encours-old" in slugs

    warned_cat = next(c for c in remaining if c["slug"] == "unattended-warning")
    assert "unattended_warning" in warned_cat
    assert "⚠️ Purge scheduled in" in warned_cat["unattended_warning"]


def test_build_confluence_storage_html_renders_noise_table() -> None:
    tracked = [
        {
            "slug": "normal-alert",
            "name": "Normal Alert",
            "status": "IN PROGRESS",
            "count_this_week": 3,
            "total_occurrences": 10,
            "occurrences_display": "3 this week",
            "actions_html": "<p>Action</p>",
            "assignee": "Alice",
            "due_date": "-",
            "last_seen": "28/10/2026",
            "is_active_now": True,
        },
        {
            "slug": "noise-alert-1",
            "name": "Incompressible Noise Alert",
            "status": "NOISE",
            "count_this_week": 50,
            "total_occurrences": 200,
            "occurrences_display": "50 this week",
            "actions_html": "<p>Known periodic alert</p>",
            "assignee": "",
            "due_date": "-",
            "last_seen": "28/10/2026",
            "is_active_now": True,
        },
    ]
    stats = TrackingService.calculate_stats(tracked)
    assert stats["NOISE"] == 1

    html_out = TrackingService.build_confluence_storage_html(
        tracked_categories=tracked,
        stats=stats,
        sync_date_str="28/10/2026 at 10:00:00",
    )

    assert "🟤 <strong>1</strong> Noise" in html_out
    assert "NOISE" in html_out
    assert "background-color: #795548" in html_out
    assert "🟤 Known Incompressible Noise Alerts" in html_out

    parsed = TrackingService.parse_confluence_storage(html_out)
    assert "noise-alert-1" in parsed
    assert parsed["noise-alert-1"]["status"] == "NOISE"
    assert parsed["normal-alert"]["status"] == "IN PROGRESS"


def test_reconciliation_noise_stays_noise() -> None:
    categories = [{"name": "Recurring Noise Alert", "count": 10}]
    slug = TrackingService.get_category_slug("Recurring Noise Alert")
    existing = {
        slug: {
            "slug": slug,
            "name": "Recurring Noise Alert",
            "status": "NOISE",
            "total_occurrences": 100,
            "actions_html": "<p>Known noise</p>",
            "assignee": "",
            "last_seen": "20/10/2026",
        }
    }
    tracked, stats = TrackingService.reconcile(categories, existing, "28/10/2026 10:00")
    assert tracked[0]["status"] == "NOISE"
    assert tracked[0]["total_occurrences"] == 110
    assert stats["NOISE"] == 1


def test_append_weekly_stats_row_new_page() -> None:
    stats = {
        "NEW": 3,
        "UNATTENDED": 1,
        "IN PROGRESS": 4,
        "RECURRING": 2,
        "RESOLVED": 5,
        "NOISE": 2,
        "UNATTENDED_PURGED": 1,
        "TOTAL": 17,
        "ACTIVE_THIS_WEEK": 8,
    }
    html_out = TrackingService.append_weekly_stats_row(
        storage_html="",
        stats=stats,
        sync_date_str="28/10/2026 at 10:30:00",
        total_alerts=150,
        main_page_url="https://confluence.example.com/main",
        report_filename="rapport_alertes_20261028_103000.html",
        artifact_url="https://gitlab.example.com/artifacts/alertes.html",
    )
    assert "📊 Weekly Mattermost Alert Metrics Log" in html_out
    assert "<th>Execution Date</th>" in html_out
    assert "<th>Total Alerts</th>" in html_out
    assert "<th>Unattended (⚪)</th>" in html_out
    assert "<th>Noise (🟤)</th>" in html_out
    assert "<th>HTML Report (Attachment)</th>" in html_out
    assert "rapport_alertes_20261028_103000.html" in html_out
    assert "<ri:attachment" in html_out
    assert "<strong>150</strong>" in html_out
    assert "<strong>8</strong>" in html_out
    assert "https://confluence.example.com/main" in html_out
