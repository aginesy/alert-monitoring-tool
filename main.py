from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Assurer la priorité des modules locaux au projet alerting
ALERTING_ROOT = Path(__file__).resolve().parent
if str(ALERTING_ROOT) not in sys.path:
    sys.path.insert(0, str(ALERTING_ROOT))

from dotenv import load_dotenv

load_dotenv()

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
    """Valide que la valeur fournie est un entier strictement positif."""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"La valeur '{value}' n'est pas un nombre entier valide.")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"Le nombre d'heures doit être supérieur à 0 (reçu : {value}).")
    return ivalue


def str_to_bool(value: str | bool) -> bool:
    """Convertit une chaîne en booléen (gère 'true', 'false', '1', '0', etc.)."""
    if isinstance(value, bool):
        return value
    val = value.strip().lower()
    if val in ("true", "1", "yes", "y", "t", "vrai"):
        return True
    if val in ("false", "0", "no", "n", "f", "faux"):
        return False
    raise argparse.ArgumentTypeError(
        f"Valeur booléenne invalide pour --suivi-confluence : '{value}'. "
        "Valeurs acceptées : 'true', 'false', '1', '0', 'yes', 'no'."
    )


def get_app_timezone() -> ZoneInfo | timezone:
    """Récupère le fuseau horaire configuré avec repli sur UTC en cas d'erreur."""
    try:
        return ZoneInfo(config.TIMEZONE)
    except (ZoneInfoNotFoundError, Exception):
        logger.warning(
            "[CONFIGURATION] Fuseau horaire '%s' indisponible ou invalide. Repli sur UTC.",
            config.TIMEZONE,
        )
        return timezone.utc


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Génération du rapport d'alertes Mattermost sur une période donnée.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--hours",
        type=positive_int,
        default=config.DEFAULT_HOURS,
        help="Nombre d'heures à analyser (entier strictement positif).",
    )

    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Chemin de sortie du fichier HTML généré.",
    )

    parser.add_argument(
        "--suivi-confluence",
        type=str_to_bool,
        nargs="?",
        const=True,
        default=os.getenv("SUIVI_CONFLUENCE", "false").lower() in ("true", "1", "yes"),
        metavar="true|false",
        help="Activer ou désactiver le mode de suivi des actions et la synchronisation avec Confluence.",
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="Lancer le mode démonstration autonome avec des alertes et un Confluence simulés (aucun serveur externe requis).",
    )

    parser.add_argument(
        "--open",
        action="store_true",
        help="Ouvrir automatiquement le rapport HTML dans le navigateur par défaut après génération.",
    )

    return parser.parse_args()


def save_report(content: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        file.write(content)

    logger.info("[SYSTÈME] Rapport sauvegardé avec succès dans : %s", output_path.resolve())


def main() -> int:
    try:
        args = parse_arguments()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1

    is_demo = bool(args.demo)

    # En mode démo, calibrer par défaut sur 168h (7 jours) pour un scénario complet représentatif
    if is_demo and not any(arg.startswith("--hours") for arg in sys.argv[1:]):
        hours = 168
    else:
        hours = args.hours

    output_file = Path(args.output) if args.output else config.OUTPUT_FILE
    app_tz = get_app_timezone()

    # En mode démo, activer le suivi Confluence par défaut sauf refus explicite
    if is_demo and not any(arg.startswith("--suivi-confluence") for arg in sys.argv[1:]):
        suivi_confluence = True
    else:
        suivi_confluence = bool(args.suivi_confluence)

    channel_id = (
        "canal-demo-alerting"
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
            "[CONFIGURATION] Variables Mattermost manquantes. Veuillez renseigner MATTERMOST_URL, "
            "MATTERMOST_TOKEN et MATTERMOST_CHANNEL_ID dans le fichier .env (ou tester avec --demo)."
        )
        return 1

    try:
        if is_demo:
            logger.info("[DÉMO] Mode démonstration autonome activé. Utilisation du client Mattermost simulé...")
            with MockMattermostClient(hours=hours, tz=app_tz) as client:
                alerts = client.fetch_messages()
        else:
            logger.info("[MATTERMOST] Initialisation du client Mattermost...")
            with MattermostClient(
                url=url,
                token=token,
                channel_id=channel_id,
                hours=hours,
                excluded_titles=config.EXCLUDED_ALERT_TITLES,
                team=team,
                tz=app_tz,
            ) as client:
                logger.info("[MATTERMOST] Récupération des alertes...")
                alerts = client.fetch_messages()

        logger.info("[ANALYSE] Catégorisation et décompte des occurrences...")
        categories = AlertService.categorize_alerts(alerts, tz=app_tz)

        # Date de génération du rapport (pour le rapport HTML et la synchronisation Confluence)
        current_date_str = datetime.now(tz=app_tz).strftime("%d/%m/%Y à %H:%M:%S")

        # Limitation du nombre d'alertes détaillées en fin de page pour optimiser la mémoire et le DOM
        max_detailed = config.MAX_DETAILED_ALERTS
        if max_detailed > 0 and len(alerts) > max_detailed:
            detailed_alerts = alerts[:max_detailed]
            detailed_limited = True
        else:
            detailed_alerts = alerts
            detailed_limited = False

        renderer = TemplateRenderer()

        def build_rendered_report(conf_url: str | None, conf_stats: dict[str, int]) -> str:
            is_suivi_active = bool(suivi_confluence)
            if not is_suivi_active:
                for cat in categories:
                    cat.pop("tracking", None)

            # Construction de la frise chronologique avec les catégories enrichies du suivi Confluence
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
                "confluence_page_url": conf_url if is_suivi_active else None,
                "confluence_stats": conf_stats if is_suivi_active else {},
                "suivi_confluence": is_suivi_active,
            }
            return renderer.render(config.TEMPLATE_FILE, context)

        # Suivi Confluence (activé uniquement avec l'option --suivi-confluence ou par défaut en --demo)
        confluence_page_url: str | None = None
        tracking_stats: dict[str, int] = {}
        demo_conf_client: MockConfluenceClient | None = None

        if suivi_confluence:
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
            logger.info("[CONFLUENCE] Mode suivi Confluence non spécifié. Exécution standard.")

        logger.info("[RENDU] Génération du rapport HTML...")
        rendered_html = build_rendered_report(confluence_page_url, tracking_stats)
        save_report(rendered_html, output_file)

        # En mode démonstration avec suivi activé, générer les 3 écrans Confluence simulés
        if is_demo and demo_conf_client:
            logger.info("[DÉMO] Génération des 3 pages web Confluence simulées...")
            exported = demo_conf_client.export_html_pages(
                output_dir=output_file.parent,
                sync_date_str=current_date_str,
            )
            logger.info("========================================================")
            logger.info("       🎉 DÉMONSTRATION COMPLÈTE PRÊTE EN LOCAL         ")
            logger.info("========================================================")
            logger.info(" • Rapport d'alerting       : %s", output_file.resolve())
            for key, path in exported.items():
                logger.info(" • Écran Confluence (%-7s) : %s", key, path.resolve())
            logger.info("========================================================")

        if args.open:
            import webbrowser
            report_uri = output_file.resolve().as_uri()
            logger.info("[SYSTÈME] Ouverture du rapport dans le navigateur : %s", report_uri)
            webbrowser.open(report_uri)

    except Exception:
        logger.exception("[SYSTÈME] Une erreur est survenue lors de la génération du rapport d'alerting.")
        return 1

    logger.info("[SYSTÈME] Traitement terminé avec succès.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
