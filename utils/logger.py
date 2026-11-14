from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)


class ColorFormatter(logging.Formatter):
    """
    Log formatter with ANSI colors for console output.
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
    Globally configures the application logging system
    with an ANSI color formatter for console output.
    """
    root_logger = logging.getLogger()

    # Only configure if no handlers are already defined
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
    Displays an initialization summary banner when alerting processing starts.
    """
    logger.info("========================================================")
    logger.info("          ALERTING REPORT INITIALIZATION                ")
    logger.info("========================================================")
    logger.info(" • Target Channel  : %s", channel_id or "Not configured")
    logger.info(" • Analyzed Period : Last %d hours", hours)
    logger.info(" • Output File     : %s", output_file)
    if excluded_titles:
        logger.info(" • Excluded Titles : %s", ", ".join(excluded_titles))
    logger.info("========================================================")
