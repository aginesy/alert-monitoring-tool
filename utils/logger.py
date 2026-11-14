from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


class ColorFormatter(logging.Formatter):
    """
    Formateur de logs avec couleurs ANSI pour la console.
    """
    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

    _FORMATTERS = {
        logging.DEBUG: logging.Formatter(GREY + FORMAT + RESET, datefmt=DATE_FORMAT),
        logging.INFO: logging.Formatter(GREEN + FORMAT + RESET, datefmt=DATE_FORMAT),
        logging.WARNING: logging.Formatter(YELLOW + FORMAT + RESET, datefmt=DATE_FORMAT),
        logging.ERROR: logging.Formatter(RED + FORMAT + RESET, datefmt=DATE_FORMAT),
        logging.CRITICAL: logging.Formatter(BOLD_RED + FORMAT + RESET, datefmt=DATE_FORMAT),
    }
    _DEFAULT_FORMATTER = logging.Formatter(FORMAT, datefmt=DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        formatter = self._FORMATTERS.get(record.levelno, self._DEFAULT_FORMATTER)
        return formatter.format(record)


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure globalement le système de journalisation (logging) de l'application
    avec un formateur couleur ANSI pour la console.
    """
    root_logger = logging.getLogger()
    
    # Ne configurer que s'il n'y a pas de handlers déjà définis
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(ColorFormatter())
        root_logger.setLevel(level)
        root_logger.addHandler(handler)


def print_alerting_summary(
    channel_id: str,
    hours: int,
    output_file: str,
    excluded_titles: list[str] | None = None,
) -> None:
    """
    Affiche un encadré récapitulatif au lancement du traitement d'alerting.
    """
    logger.info("========================================================")
    logger.info("          INITIALISATION DU RAPPORT ALERTING            ")
    logger.info("========================================================")
    logger.info(" • Canal cible       : %s", channel_id or "Non configuré")
    logger.info(" • Période analysée  : Dernières %d heures", hours)
    logger.info(" • Fichier de sortie : %s", output_file)
    if excluded_titles:
        logger.info(" • Titres exclus     : %s", ", ".join(excluded_titles))
    logger.info("========================================================")
