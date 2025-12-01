import logging
import sys

import colorlog


def setup_logging(debug: bool = False) -> None:
    """Set up logging configuration."""
    if sys.stdout.isatty():  # Stdout probably accepts color.
        handler = colorlog.StreamHandler()
        handler.setFormatter(
            colorlog.ColoredFormatter(
                "%(blue)s[%(asctime)s]%(reset)s %(log_color)s%(levelname)s%(reset)s"
                " %(thin)sin %(name)s -%(reset)s %(message)s",
                log_colors={
                    "DEBUG": "light_cyan",
                    "INFO": "light_green",
                    "WARNING": "light_yellow",
                    "ERROR": "light_red",
                    "CRITICAL": "bold_red,bg_white",
                },
            )
        )
    else:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s - %(message)s")
        )

    logging.basicConfig(handlers=[handler], level=logging.INFO)

    # Set log level for specific modules.
    if debug:
        logging.getLogger("karboni").setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.DEBUG)
    else:
        logging.getLogger("karboni").setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.WARNING)
