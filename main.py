from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Ensure alerting project root directory is available in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.logger import setup_logging, print_alerting_summary
from config import config, config_mattermost, config_confluence
from clients.mattermost_client import MattermostClient
from clients.confluence_client import ConfluenceClient
from services.template_renderer import TemplateRenderer
from services.alert_service import AlertService
from services.tracking_service import TrackingService
from services.demo_service import MockMattermostClient, MockConfluenceClient

setup_logging()
logger = logging.getLogger(__name__)


def positive_int(value: str) -> int:
    """Validates that the provided value is a strictly positive integer."""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Value '{value}' is not a valid integer.")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"Number of hours must be greater than 0 (received: {value}).")
    return ivalue


def str_to_bool(value: str | bool) -> bool:
    """Converts a string representation into a boolean (handles 'true', 'false', '1', '0', etc.)."""
    if isinstance(value, bool):
        return value
    val = value.strip().lower()
    if val in ("true", "1", "yes", "y", "t"):
        return True
    if val in ("false", "0", "no", "n", "f"):
        return False
    raise argparse.ArgumentTypeError(
        f"Invalid boolean value for --confluence-tracking: '{value}'. "
        "Accepted values: 'true', 'false', '1', '0', 'yes', 'no'."
    )


def get_app_timezone() -> ZoneInfo | timezone:
    """Retrieves configured timezone with fallback to UTC on error."""
    try:
        return ZoneInfo(config.TIMEZONE)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning(
            "[CONFIGURATION] Timezone '%s' unavailable or invalid. Falling back to UTC.",
            config.TIMEZONE,
        )
        return timezone.utc


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mattermost alerting report generation and Confluence review tracking over a time window.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--hours",
        type=positive_int,
        default=config.DEFAULT_HOURS,
        help="Number of hours of history to analyze (strictly positive integer).",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output file path for the generated HTML report.",
    )

    parser.add_argument(
        "--confluence-tracking",
        "--suivi-confluence",
        dest="confluence_tracking",
        type=str_to_bool,
        nargs="?",
        const=True,
        default=(
            os.getenv("CONFLUENCE_TRACKING") or os.getenv("SUIVI_CONFLUENCE", "false")
        ).lower() in ("true", "1", "yes"),
        metavar="true|false",
        help="Enable or disable action tracking and synchronization with Confluence.",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run standalone demo mode with simulated alerts and Confluence pages (no external servers required).",
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the generated HTML report in the default web browser.",
    )

    ns = parser.parse_args()
    setattr(ns, "suivi_confluence", ns.confluence_tracking)
    return ns


def save_report(content: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(content)

    logger.info("[SYSTEM] Report successfully saved to: %s", output_path.resolve())


def main() -> int:
    try:
        args = parse_arguments()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    is_demo = bool(args.demo)

    # In demo mode, default to 168h (7 days) for a representative weekly view unless explicitly overridden
    if is_demo and not any(arg.startswith("--hours") for arg in sys.argv[1:]):
        hours = 168
    else:
        hours = args.hours

    output_file = Path(args.output) if args.output else config.OUTPUT_FILE
    app_tz = get_app_timezone()

    # In demo mode, enable Confluence tracking by default unless explicitly disabled
    has_explicit_tracking_flag = any(
        arg.startswith(("--confluence-tracking", "--suivi-confluence"))
        for arg in sys.argv[1:]
    )
    if is_demo and not has_explicit_tracking_flag:
        confluence_tracking = True
    else:
        confluence_tracking = bool(args.confluence_tracking)

    channel_id = (
        "demo-alerting-channel"
        if is_demo
        else (config_mattermost.mattermost_client_config.get("channel_id") or "")
    )

    print_alerting_summary(
        channel_id=channel_id,
        hours=hours,
        output_file=str(output_file),
        excluded_titles=config.EXCLUDED_ALERT_TITLES,
    )

    url = config_mattermost.mattermost_client_config.get("url")
    token = config_mattermost.mattermost_client_config.get("token")
    team = config_mattermost.mattermost_client_config.get("team")

    if not is_demo and (not url or not token or not channel_id):
        logger.error(
            "[CONFIGURATION] Missing Mattermost environment variables. Please provide MATTERMOST_URL, "
            "MATTERMOST_TOKEN and MATTERMOST_CHANNEL_ID in .env (or test using --demo)."
        )
        return 1

    try:
        if is_demo:
            logger.info("[DEMO] Standalone demo mode enabled. Using simulated Mattermost client...")
            with MockMattermostClient(hours=hours, tz=app_tz) as client:
                alerts = client.fetch_messages()
        else:
            logger.info("[MATTERMOST] Initializing Mattermost client...")
            with MattermostClient(
                url=url,
                token=token,
                channel_id=channel_id,
                hours=hours,
                excluded_titles=config.EXCLUDED_ALERT_TITLES,
                team=team,
                tz=app_tz,
            ) as client:
                logger.info("[MATTERMOST] Fetching alert messages...")
                alerts = client.fetch_messages()

        logger.info("[ANALYSIS] Categorizing alerts and counting occurrences...")
        categories = AlertService.categorize_alerts(alerts, tz=app_tz)

        # Generation timestamp (used in HTML report and Confluence synchronization)
        current_date_str = datetime.now(tz=app_tz).strftime("%d/%m/%Y at %H:%M:%S")

        # Limit number of detailed alerts at the end of the report to keep DOM responsive
        max_detailed = config.MAX_DETAILED_ALERTS
        if max_detailed > 0 and len(alerts) > max_detailed:
            detailed_alerts = alerts[:max_detailed]
            detailed_limited = True
        else:
            detailed_alerts = alerts
            detailed_limited = False

        renderer = TemplateRenderer()

        def build_rendered_report(conf_url: str | None, conf_stats: dict[str, int]) -> str:
            is_tracking_active = bool(confluence_tracking)
            if not is_tracking_active:
                for cat in categories:
                    cat.pop("tracking", None)

            # Build timeline chart data with Confluence-enriched categories
            timeline = AlertService.build_timeline_data(alerts, hours, categories=categories, tz=app_tz)
            context = {
                "alerts": alerts,
                "detailed_alerts": detailed_alerts,
                "detailed_limited": detailed_limited,
                "max_detailed": max_detailed,
                "categories": categories,
                "timeline": timeline,
                "total_alerts": len(alerts),
                "total_categories": len(categories),
                "hours": hours,
                "generation_date": current_date_str,
                "confluence_page_url": conf_url if is_tracking_active else None,
                "confluence_stats": conf_stats if is_tracking_active else {},
                "suivi_confluence": is_tracking_active,
                "confluence_tracking": is_tracking_active,
            }
            return renderer.render(config.TEMPLATE_FILE, context)

        # Confluence synchronization (active only with --confluence-tracking / --suivi-confluence or in --demo)
        confluence_page_url: str | None = None
        tracking_stats: dict[str, int] = {}
        demo_conf_client: MockConfluenceClient | None = None

        if confluence_tracking:
            if is_demo:
                conf_config = {
                    "url": "confluence_suivi.html",
                    "token": "demo_token",
                    "page_id": "123456789",
                    "archive_page_id": "123456780",
                    "stats_page_id": "123456781",
                    "disabled": False,
                }
                demo_conf_client = MockConfluenceClient()
                client_cls: Any = lambda *a, **kw: demo_conf_client
            else:
                conf_config = config_confluence.confluence_config
                client_cls = ConfluenceClient

            confluence_page_url, tracking_stats = TrackingService.synchronize_confluence(
                confluence_config=conf_config,
                categories=categories,
                alerts=alerts,
                current_date_str=current_date_str,
                app_tz=app_tz,
                gitlab_artifact_url="alertes.html" if is_demo else config.GITLAB_ARTIFACT_URL,
                gitlab_artifact_browse_url="." if is_demo else config.GITLAB_ARTIFACT_BROWSE_URL,
                client_class=client_cls,
                render_html_callback=build_rendered_report,
            )
        else:
            logger.info("[CONFLUENCE] Confluence tracking mode not specified. Standard execution.")

        logger.info("[RENDERING] Generating HTML report...")
        rendered_html = build_rendered_report(confluence_page_url, tracking_stats)
        save_report(rendered_html, output_file)

        # In standalone demo mode with tracking, export the 3 simulated Confluence web screens
        if is_demo and demo_conf_client:
            logger.info("[DEMO] Generating 3 simulated Confluence web views...")
            exported = demo_conf_client.export_html_pages(
                output_dir=output_file.parent,
                sync_date_str=current_date_str,
            )
            logger.info("========================================================")
            logger.info("       🎉 COMPLETE LOCAL DEMONSTRATION READY            ")
            logger.info("========================================================")
            logger.info(" • Alerting Report           : %s", output_file.resolve())
            for key, path in exported.items():
                logger.info(" • Confluence Screen (%-7s): %s", key, path.resolve())
            logger.info("========================================================")

        if args.open:
            import webbrowser
            report_uri = output_file.resolve().as_uri()
            logger.info("[SYSTEM] Opening report in default browser: %s", report_uri)
            webbrowser.open(report_uri)

    except Exception:
        logger.exception("[SYSTEM] An error occurred while generating the alerting report.")
        return 1

    logger.info("[SYSTEM] Processing completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
