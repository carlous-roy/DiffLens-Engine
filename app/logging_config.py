"""Process-wide logging configuration driven by the LOG_LEVEL setting."""

import logging
import logging.config

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once; uvicorn's loggers keep their handlers.

    Calling it again only adjusts the level, so tests and reloads do not pile
    up handlers.
    """
    global _CONFIGURED
    numeric = logging.getLevelName(str(level).upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    if _CONFIGURED:
        logging.getLogger().setLevel(numeric)
        return
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "stream": "ext://sys.stderr",
                }
            },
            "root": {"level": numeric, "handlers": ["console"]},
            "loggers": {
                # Keep the third-party chatter down unless debugging.
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
                "sqlalchemy.engine": {"level": "WARNING"},
            },
        }
    )
    _CONFIGURED = True
