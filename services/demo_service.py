from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_demo_alerts(hours: int = 168, tz: tzinfo | None = None) -> list[dict[str, Any]]:
    """
    Generates a realistic, timestamped Mattermost alert dataset over the specified time window.
    Covers multiple microservices, severities, and statuses to showcase
    all alerting features and Confluence state machine transitions.
    """
    tz_to_use = tz or timezone.utc
    now = datetime.now(tz=tz_to_use)

    # Alert scenarios with frequency profile and severity
    scenarios = [
        {
            "category": "P99 latency exceeding 1.5s on api-gateway",
            "service": "api-gateway",
            "title": "API Latency Alert",
            "status": "FIRING",
            "severity": "MAJOR",
            "offsets_hours": [2, 5, 8, 14, 22, 28, 35, 42, 50, 70, 92, 110, 134, 150, 160],
            "description": "The P99 response time on api-gateway exceeds the critical threshold of 1.5s.",
        },
        {
            "category": "5xx error rate exceeding 2% on payment-service",
            "service": "payment-service",
            "title": "Payment Gateway HTTP 5xx Errors",
            "status": "FIRING:2",
            "severity": "CRITICAL",
            "offsets_hours": [1, 3, 6, 12, 18, 24, 48, 72, 96],
            "description": "The percentage of HTTP 5xx errors on payment-service reached 3.8% following a PSP timeout.",
        },
        {
            "category": "Memory utilization > 85% on database-cluster",
            "service": "database-cluster",
            "title": "PostgreSQL Memory Saturation",
            "status": "FIRING",
            "severity": "WARNING",
            "offsets_hours": [4, 10, 26, 32, 55],
            "description": "RAM consumption on database-cluster-primary pod exceeds warning threshold (88%).",
        },
        {
            "category": "Frequent restarts of bi-agent container",
            "service": "bi-agent",
            "title": "Container CrashLoopBackOff",
            "status": "FIRING",
            "severity": "WARNING",
            "offsets_hours": [7, 19, 31, 43, 67, 89, 120, 142],
            "description": "The bi-agent pod restarted with exit code 137 (OOMKilled).",
        },
        {
            "category": "Nightly accounting batch sync timeout",
            "service": "batch-engine",
            "title": "Overnight Batch SLA Exceeded",
            "status": "RESOLVED",
            "severity": "INFO",
            "offsets_hours": [20, 44, 68],
            "description": "The overnight accounting synchronization batch exceeded the 45-minute SLA execution window.",
        },
    ]

    alerts: list[dict[str, Any]] = []
    alert_counter = 1

    for sc in scenarios:
        for offset in sc["offsets_hours"]:
            if offset > hours:
                continue

            alert_time = now - timedelta(hours=offset)
            timestamp_ms = int(alert_time.timestamp() * 1000)
            created_at_str = alert_time.strftime("%d/%m/%Y %H:%M:%S")
            post_id = f"demo_post_{alert_counter:04d}"

            msg = (
                f"[{sc['status']}] {sc['severity']} - {sc['title']}\n"
                f"**Service:** `{sc['service']}`\n"
                f"**Description:** {sc['category']}\n"
                f"{sc['description']}"
            )

            alerts.append({
                "id": post_id,
                "message": msg,
                "created_at": created_at_str,
                "timestamp": timestamp_ms,
                "titles": [sc["title"]],
                "attachments": [
                    {
                        "title": sc["title"],
                        "text": sc["description"],
                        "description": sc["category"],
                    }
                ],
                "permalink": f"https://mattermost.example.com/demo/pl/{post_id}",
            })
            alert_counter += 1

    # Sort descending by timestamp (newest first, matching Mattermost API)
    alerts.sort(key=lambda a: a["timestamp"], reverse=True)
    logger.info("[DEMO] %d simulated alerts generated for the last %dh.", len(alerts), hours)
    return alerts


def convert_confluence_storage_to_html(xhtml: str) -> str:
    """
    Converts proprietary Atlassian XHTML storage format (<ac:*>, <ri:*>)
    into styled HTML faithful to Confluence Server / Data Center web UI.
    """
    if not xhtml:
        return "<p><em>No content.</em></p>"

    out = xhtml

    # 1. Atlassian Status Macro: <ac:structured-macro ac:name="status">...
    def replace_status(m: re.Match) -> str:
        body = m.group(1)
        title_m = re.search(r'<ac:parameter ac:name="title">([^<]+)</ac:parameter>', body)
        colour_m = re.search(r'<ac:parameter ac:name="colour">([^<]+)</ac:parameter>', body)
        title = title_m.group(1).strip() if title_m else "STATUS"
        colour = colour_m.group(1).strip().lower() if colour_m else "grey"
        return f'<span class="aui-lozenge status-{colour}">{html.escape(title)}</span>'

    out = re.sub(
        r'<ac:structured-macro ac:name="status">(.*?)</ac:structured-macro>',
        replace_status,
        out,
        flags=re.DOTALL,
    )

    # 2. Atlassian Panel Macro: <ac:structured-macro ac:name="panel">...
    def replace_panel(m: re.Match) -> str:
        body = m.group(1)
        title_m = re.search(r'<ac:parameter ac:name="title">([^<]+)</ac:parameter>', body)
        content_m = re.search(r'<ac:rich-text-body>(.*?)</ac:rich-text-body>', body, flags=re.DOTALL)
        title = title_m.group(1).strip() if title_m else ""
        content = content_m.group(1).strip() if content_m else ""
        header_html = f'<div class="panel-header">{html.escape(title)}</div>' if title else ""
        return f'<div class="confluence-panel">{header_html}<div class="panel-body">{content}</div></div>'

    out = re.sub(
        r'<ac:structured-macro ac:name="panel">(.*?)</ac:structured-macro>',
        replace_panel,
        out,
        flags=re.DOTALL,
    )

    # 3. Atlassian Anchor Macro: <ac:structured-macro ac:name="anchor">...
    def replace_anchor(m: re.Match) -> str:
        body = m.group(1)
        slug_m = re.search(r'<ac:parameter ac:name="">([^<]+)</ac:parameter>', body)
        slug = slug_m.group(1).strip() if slug_m else ""
        return f'<a id="{slug}" class="confluence-anchor" name="{slug}"></a>'

    out = re.sub(
        r'<ac:structured-macro ac:name="anchor">(.*?)</ac:structured-macro>',
        replace_anchor,
        out,
        flags=re.DOTALL,
    )

    # 4. <time datetime="YYYY-MM-DD" /> tags
    def replace_time(m: re.Match) -> str:
        dt_val = m.group(1)
        parts = dt_val.split("-")
        label = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else dt_val
        return f'<time class="confluence-time" datetime="{dt_val}">{label}</time>'

    out = re.sub(r'<time datetime="([^"]+)"\s*/>', replace_time, out)

    # 5. Attachment reference: <ri:attachment ri:filename="..." />
    def replace_attachment(m: re.Match) -> str:
        fname = m.group(1)
        return f'<a href="alertes.html" class="confluence-attachment-link" title="Open attached HTML report">📎 {html.escape(fname)}</a>'

    out = re.sub(r'<ri:attachment ri:filename="([^"]+)"\s*/>', replace_attachment, out)

    # 6. Style tables and rows
    out = out.replace("<table>", '<table class="confluenceTable">')
    out = out.replace("<th>", '<th class="confluenceTh">')
    out = out.replace("<td>", '<td class="confluenceTd">')

    # Strip remaining orphan Atlassian tags
    out = re.sub(r'</?ac:[^>]+>', '', out)
    out = re.sub(r'</?ri:[^>]+>', '', out)

    return out


def render_confluence_page_html(
    title: str,
    storage_xhtml: str,
    active_page_id: str,
    sync_date_str: str,
) -> str:
    """
    Renders a complete HTML page matching Confluence Server / Data Center styling.
    """
    body_html = convert_confluence_storage_to_html(storage_xhtml)

    pages_nav = [
        ("suivi", "confluence_suivi.html", "📋 1. Active Review Dashboard"),
        ("archive", "confluence_archive.html", "🗄️ 2. Archive (> 1 Month)"),
        ("stats", "confluence_stats.html", "📈 3. Weekly Statistics"),
    ]

    nav_tabs_html = []
    for pid, url, label in pages_nav:
        active_class = " nav-tab-active" if pid == active_page_id else ""
        nav_tabs_html.append(f'<a href="{url}" class="nav-tab{active_class}">{label}</a>')

    tabs_str = "\n".join(nav_tabs_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{html.escape(title)} - Confluence (Demo Simulation)</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        html {{
            scroll-behavior: smooth;
        }}
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", Ubuntu, "Droid Sans", "Helvetica Neue", sans-serif;
            color: #172b4d;
            background-color: #f4f5f7;
            font-size: 14px;
            line-height: 1.42857;
        }}

        /* Atlassian Confluence header bar */
        .atlassian-header {{
            height: 44px;
            background-color: #0052cc;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 16px;
            font-size: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12);
        }}
        .header-brand {{
            display: flex;
            align-items: center;
            gap: 12px;
            font-weight: 700;
            letter-spacing: 0.3px;
        }}
        .header-brand svg {{
            fill: #ffffff;
            width: 22px;
            height: 22px;
        }}
        .header-nav {{
            display: flex;
            align-items: center;
            gap: 16px;
            font-size: 13px;
            font-weight: 500;
        }}
        .header-nav a {{
            color: #deebff;
            text-decoration: none;
            padding: 4px 8px;
            border-radius: 3px;
        }}
        .header-nav a:hover {{
            background-color: rgba(255,255,255,0.15);
            color: #ffffff;
        }}

        /* Demo mode banner */
        .demo-callout {{
            background-color: #ebecf0;
            border-bottom: 1px solid #dfe1e6;
            padding: 8px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 10px;
            font-size: 12px;
            color: #42526e;
        }}
        .demo-callout strong {{
            color: #0052cc;
        }}
        .demo-back-btn {{
            background-color: #0052cc;
            color: #ffffff !important;
            padding: 4px 12px;
            border-radius: 3px;
            text-decoration: none;
            font-weight: 600;
            transition: background 0.15s ease;
        }}
        .demo-back-btn:hover {{
            background-color: #0747a6;
        }}

        /* Confluence page navigation tabs */
        .demo-tabs-bar {{
            background-color: #ffffff;
            border-bottom: 2px solid #dfe1e6;
            padding: 0 24px;
            display: flex;
            gap: 4px;
            overflow-x: auto;
        }}
        .nav-tab {{
            display: inline-block;
            padding: 10px 16px;
            color: #42526e;
            text-decoration: none;
            font-weight: 600;
            font-size: 13px;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.15s ease;
        }}
        .nav-tab:hover {{
            color: #0052cc;
        }}
        .nav-tab-active {{
            color: #0052cc;
            border-bottom-color: #0052cc;
            background-color: #f4f8ff;
        }}

        /* Main Confluence container */
        .page-wrapper {{
            max-width: 1400px;
            margin: 20px auto 40px auto;
            background: #ffffff;
            border: 1px solid #dfe1e6;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(9, 30, 66, 0.08);
            padding: 32px 40px;
        }}

        /* Breadcrumbs */
        .breadcrumbs {{
            font-size: 12px;
            color: #6b778c;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .breadcrumbs a {{
            color: #6b778c;
            text-decoration: none;
        }}
        .breadcrumbs a:hover {{
            text-decoration: underline;
        }}

        /* Page title */
        h1.page-title {{
            font-size: 28px;
            font-weight: 600;
            color: #172b4d;
            margin: 0 0 8px 0;
            line-height: 1.25;
        }}
        .page-meta {{
            font-size: 12px;
            color: #6b778c;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid #ebecf0;
            padding-bottom: 12px;
        }}
        .meta-avatar {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background-color: #0052cc;
            color: #ffffff;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 700;
        }}

        /* Body and macros */
        .page-content {{
            font-size: 14px;
            color: #172b4d;
            line-height: 1.5;
        }}
        .page-content h2 {{
            font-size: 20px;
            font-weight: 600;
            margin-top: 24px;
            border-bottom: 1px solid #ebecf0;
            padding-bottom: 6px;
        }}

        /* Confluence Tables */
        table.confluenceTable {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0 24px 0;
            font-size: 13px;
        }}
        th.confluenceTh {{
            background-color: #f4f5f7;
            color: #172b4d;
            font-weight: 600;
            text-align: left;
            padding: 8px 10px;
            border: 1px solid #dfe1e6;
            vertical-align: middle;
            font-size: 12px;
        }}
        td.confluenceTd {{
            padding: 8px 10px;
            border: 1px solid #dfe1e6;
            vertical-align: top;
            line-height: 1.45;
        }}
        table.confluenceTable tr:hover {{
            background-color: #fafbfc;
        }}

        /* Target row anchor highlight effect */
        tr:has(a:target), tr.target-highlight {{
            background-color: #deebff !important;
            outline: 2px solid #2684ff;
            transition: all 0.5s ease;
        }}

        /* Status Lozenges (AUI) */
        .aui-lozenge {{
            display: inline-block;
            font-size: 11px;
            font-weight: 700;
            line-height: 1;
            padding: 3px 6px;
            border-radius: 3px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            vertical-align: baseline;
            white-space: nowrap;
        }}
        .status-yellow {{
            background: #fff0b3;
            color: #172b4d;
            border: 1px solid #ffe380;
        }}
        .status-green {{
            background: #e3fcef;
            color: #006644;
            border: 1px solid #abf5d1;
        }}
        .status-red {{
            background: #ffebe6;
            color: #bf2600;
            border: 1px solid #ffbdad;
        }}
        .status-blue {{
            background: #deebff;
            color: #0747a6;
            border: 1px solid #b3d4ff;
        }}
        .status-grey {{
            background: #f4f5f7;
            color: #42526e;
            border: 1px solid #dfe1e6;
        }}
        .status-brown {{
            background: #795548;
            color: #ffffff;
            border: 1px solid #5d4037;
        }}

        /* Confluence Panels */
        .confluence-panel {{
            border: 1px solid #b3d4ff;
            background-color: #f4f8ff;
            border-radius: 4px;
            margin: 16px 0;
            overflow: hidden;
        }}
        .panel-header {{
            background-color: #deebff;
            color: #0747a6;
            font-weight: 600;
            padding: 8px 12px;
            font-size: 13px;
        }}
        .panel-body {{
            padding: 10px 14px;
            font-size: 13px;
            line-height: 1.5;
            color: #172b4d;
        }}
        .panel-body p, .panel-body ul {{
            margin: 4px 0;
        }}

        /* Date time pill */
        time.confluence-time {{
            background-color: #ebecf0;
            color: #172b4d;
            padding: 1px 5px;
            border-radius: 3px;
            font-size: 12px;
            font-family: inherit;
        }}

        .confluence-attachment-link {{
            color: #0052cc;
            text-decoration: none;
            font-weight: 500;
        }}
        .confluence-attachment-link:hover {{
            text-decoration: underline;
        }}

        /* Footer */
        .page-footer {{
            margin-top: 40px;
            padding-top: 16px;
            border-top: 1px solid #ebecf0;
            font-size: 12px;
            color: #6b778c;
            text-align: center;
        }}
    </style>
</head>
<body>

    <!-- Atlassian Confluence header bar -->
    <header class="atlassian-header">
        <div class="header-brand">
            <svg viewBox="0 0 24 24"><path d="M2.5 12.5C2.5 6.98 6.98 2.5 12.5 2.5s10 4.48 10 10-4.48 10-10 10S2.5 18.02 2.5 12.5zm6.8 4.2c.4 0 .7-.3.7-.7V8c0-.4-.3-.7-.7-.7s-.7.3-.7.7v8c0 .4.3.7.7.7zm5.4 0c.4 0 .7-.3.7-.7V8c0-.4-.3-.7-.7-.7s-.7.3-.7.7v8c0 .4.3.7.7.7z"/></svg>
            <span>Confluence Server</span>
        </div>
        <div class="header-nav">
            <a href="#">Spaces</a>
            <a href="#">People</a>
            <a href="#">Calendars</a>
            <a href="#" style="background: rgba(255,255,255,0.2); font-weight: 700;">Create</a>
        </div>
    </header>

    <!-- Demo Mode Callout Banner -->
    <div class="demo-callout">
        <div>
            💡 <strong>STANDALONE DEMO MODE</strong>: Authentic web rendering generated by the script from Confluence XHTML storage format.
        </div>
        <div>
            <a href="alertes.html" class="demo-back-btn">📊 Return to Visual Alerting Report</a>
        </div>
    </div>

    <!-- Tab navigation between the 3 Confluence pages -->
    <nav class="demo-tabs-bar">
        {tabs_str}
    </nav>

    <!-- Confluence Container -->
    <main class="page-wrapper">
        <nav class="breadcrumbs">
            <a href="#">Spaces</a> &gt;
            <a href="#">ALERTS</a> &gt;
            <a href="#">Pages</a> &gt;
            <span>{html.escape(title)}</span>
        </nav>

        <h1 class="page-title">{html.escape(title)}</h1>

        <div class="page-meta">
            <span class="meta-avatar">AB</span>
            <span>Automatically updated by <strong>Alerting Bot</strong> on {sync_date_str or 'today'}</span>
            <span>• Space: <strong>ALERTS</strong></span>
        </div>

        <article class="page-content">
            {body_html}
        </article>

        <footer class="page-footer">
            Confluence 8.5 Data Center • Demo simulation automatically generated for alerting project
        </footer>
    </main>

    <script>
        // Smoothly scroll to and highlight target row when URL contains an anchor hash
        function highlightTargetRow() {{
            const hash = window.location.hash;
            if (hash) {{
                const target = document.querySelector(hash);
                if (target) {{
                    const row = target.closest('tr');
                    if (row) {{
                        document.querySelectorAll('tr.target-highlight').forEach(r => r.classList.remove('target-highlight'));
                        row.classList.add('target-highlight');
                        row.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    }}
                }}
            }}
        }}
        window.addEventListener('load', highlightTargetRow);
        window.addEventListener('hashchange', highlightTargetRow);
    </script>
</body>
</html>
"""


class MockConfluenceClient:
    """
    In-memory simulated Confluence client for standalone demo mode.
    Pre-populates an active team registry to exercise the full alert lifecycle
    and state transitions (NEW, RECURRING, UNATTENDED, NOISE, archiving).
    Also handles exporting the 3 pages as realistic HTML views into output/.
    """

    def __init__(
        self,
        url: str = "https://confluence.example.com",
        token: str = "demo_token",
        page_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.page_id = page_id or "123456789"
        self.archive_page_id = "123456780"
        self.stats_page_id = "123456781"
        self.space_key = "ALERTS"

        # Initial state of active tracking page (simulating existing team registry)
        main_storage = """
        <p>Team production alerting review registry.</p>
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
                  <ac:parameter ac:name="">p99-latency-exceeding-1-5s-on-api-gateway</ac:parameter>
                </ac:structured-macro>
                <strong>P99 latency exceeding 1.5s on api-gateway</strong>
              </td>
              <td>35 this week</td>
              <td><time datetime="2026-11-08" /> 14:00:00</td>
              <td>Alice</td>
              <td><time datetime="2026-11-18" /></td>
              <td><ul><li>Redis connection pool tuning</li><li>Scale out HPA pod replicas</li></ul></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">RESOLVED</ac:parameter>
                  <ac:parameter ac:name="colour">Green</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">5xx-error-rate-exceeding-2-on-payment-service</ac:parameter>
                </ac:structured-macro>
                <strong>5xx error rate exceeding 2% on payment-service</strong>
              </td>
              <td>-</td>
              <td><time datetime="2026-11-01" /> 09:30:00</td>
              <td>Bob</td>
              <td>-</td>
              <td><p>Deployed patch v2.4.1 handling PSP gateway retries</p></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">UNATTENDED</ac:parameter>
                  <ac:parameter ac:name="colour">Grey</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">nightly-accounting-batch-sync-timeout</ac:parameter>
                </ac:structured-macro>
                <strong>Nightly accounting batch sync timeout</strong>
              </td>
              <td>2 this week</td>
              <td><time datetime="2026-10-12" /> 04:00:00</td>
              <td>-</td>
              <td>-</td>
              <td><p>Non-blocking issue, pending business prioritization</p></td>
            </tr>
            <tr>
              <td>
                <ac:structured-macro ac:name="status">
                  <ac:parameter ac:name="title">RESOLVED</ac:parameter>
                  <ac:parameter ac:name="colour">Green</ac:parameter>
                </ac:structured-macro>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">temporary-dns-failure-on-auth-service</ac:parameter>
                </ac:structured-macro>
                <strong>Temporary DNS failure on auth-service</strong>
              </td>
              <td>-</td>
              <td><time datetime="2026-09-15" /> 11:20:00</td>
              <td>Charlie</td>
              <td>-</td>
              <td><p>Completed failover to high-availability CoreDNS resolver</p></td>
            </tr>
            <tr>
              <td>
                <span style="background-color: #795548; color: #ffffff; padding: 2px 8px; border-radius: 3px; font-weight: bold; font-size: 11px;">NOISE</span>
              </td>
              <td>
                <ac:structured-macro ac:name="anchor">
                  <ac:parameter ac:name="">frequent-restarts-of-bi-agent-container</ac:parameter>
                </ac:structured-macro>
                <strong>Frequent restarts of bi-agent container</strong>
              </td>
              <td>12 this week</td>
              <td><time datetime="2026-11-09" /> 16:15:00</td>
              <td>-</td>
              <td>-</td>
              <td><p>Periodic GC behavior, harmless to production workflows</p></td>
            </tr>
          </tbody>
        </table>
        """

        archive_storage = """
        <p>Historical record of decisions for alerts resolved over 1 month ago.</p>
        <table>
          <thead>
            <tr>
              <th>Alert Category</th>
              <th>Occurrences During Review</th>
              <th>Last Seen</th>
              <th>Assignee</th>
              <th>Due Date</th>
              <th>Action Items (Review Meeting)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
        """

        stats_storage = """
        <p>Weekly alerting tracking statistics log.</p>
        <table>
          <thead>
            <tr>
              <th>Execution Date</th>
              <th>Total Alerts</th>
              <th>Categories</th>
              <th>Active</th>
              <th>New</th>
              <th>In Progress</th>
              <th>Recurring</th>
              <th>Unattended</th>
              <th>Resolved</th>
              <th>Noise</th>
              <th>Archived</th>
              <th>HTML Report (Attachment)</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
        """

        self._pages: dict[str, dict[str, Any]] = {
            self.page_id: {
                "id": self.page_id,
                "title": "Weekly Alert Tracking and Team Action Plan",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": main_storage}},
            },
            self.archive_page_id: {
                "id": self.archive_page_id,
                "title": "Resolved Alerts Archive (> 1 Month)",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": archive_storage}},
            },
            self.stats_page_id: {
                "id": self.stats_page_id,
                "title": "Weekly Alerting Evolution and Metrics",
                "space": {"key": self.space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": stats_storage}},
            },
        }

        self.attached_files: list[dict[str, Any]] = []

    def __enter__(self) -> MockConfluenceClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        pass

    def get_page(self, page_id: str | None = None) -> dict[str, Any]:
        target_id = page_id or self.page_id
        if target_id not in self._pages:
            raise ValueError(f"Simulated Confluence page not found: {target_id}")
        return self._pages[target_id]

    def update_page(
        self,
        page_id: str | None,
        title: str,
        space_key: str,
        storage_html: str,
        next_version: int,
    ) -> dict[str, Any]:
        target_id = page_id or self.page_id
        if target_id not in self._pages:
            self._pages[target_id] = {
                "id": target_id,
                "title": title,
                "space": {"key": space_key},
                "version": {"number": next_version},
                "body": {"storage": {"value": storage_html}},
            }
        else:
            self._pages[target_id]["title"] = title
            self._pages[target_id]["version"]["number"] = next_version
            self._pages[target_id]["body"]["storage"]["value"] = storage_html

        logger.info("[DEMO CONFLUENCE] Simulated update of page '%s' (v%d).", title, next_version)
        return self._pages[target_id]

    def attach_file(
        self,
        page_id: str | None,
        filename: str,
        content: bytes | str,
        content_type: str = "text/html; charset=utf-8",
        comment: str | None = None,
    ) -> dict[str, Any]:
        target_id = page_id or self.page_id
        record = {
            "page_id": target_id,
            "filename": filename,
            "size": len(content) if isinstance(content, (bytes, str)) else 0,
            "comment": comment,
        }
        self.attached_files.append(record)
        logger.info("[DEMO CONFLUENCE] Simulated attachment '%s' added to page %s.", filename, target_id)
        return {"id": "demo_att_1", "title": filename}

    def build_page_url(self, page_data: dict[str, Any] | None = None) -> str:
        """
        In demo mode, page URLs point to local generated HTML files
        to provide a seamless interconnected in-browser navigation.
        """
        target_id = (page_data.get("id") if page_data else None) or self.page_id
        if target_id == self.archive_page_id:
            return "confluence_archive.html"
        elif target_id == self.stats_page_id:
            return "confluence_stats.html"
        return "confluence_suivi.html"

    def export_html_pages(self, output_dir: Path, sync_date_str: str = "") -> dict[str, Path]:
        """
        Exports the 3 simulated Confluence pages as styled HTML files
        in the output folder to enable a complete visual local demo.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        date_label = sync_date_str or datetime.now().strftime("%d/%m/%Y at %H:%M:%S")

        pages_to_export = [
            (self.page_id, "confluence_suivi.html", "suivi"),
            (self.archive_page_id, "confluence_archive.html", "archive"),
            (self.stats_page_id, "confluence_stats.html", "stats"),
        ]

        generated_files: dict[str, Path] = {}

        for page_id, filename, active_id in pages_to_export:
            page_data = self._pages.get(page_id, {})
            title = page_data.get("title", "Confluence Page")
            storage_xhtml = page_data.get("body", {}).get("storage", {}).get("value", "")

            full_html = render_confluence_page_html(
                title=title,
                storage_xhtml=storage_xhtml,
                active_page_id=active_id,
                sync_date_str=date_label,
            )

            file_path = output_dir / filename
            file_path.write_text(full_html, encoding="utf-8")
            generated_files[active_id] = file_path
            logger.info("[DEMO] Confluence page generated: %s", file_path.resolve())

        return generated_files


class MockMattermostClient:
    """
    In-memory simulated Mattermost client for standalone demo mode.
    """

    def __init__(
        self,
        hours: int = 168,
        tz: tzinfo | None = None,
        **kwargs: Any,
    ) -> None:
        self.hours = hours
        self.tz = tz

    def __enter__(self) -> MockMattermostClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def close(self) -> None:
        pass

    def fetch_messages(self) -> list[dict[str, Any]]:
        return generate_demo_alerts(hours=self.hours, tz=self.tz)
