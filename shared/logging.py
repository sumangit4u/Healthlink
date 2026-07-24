"""
Simple logging configuration shared across HealthLink microservices.
Uses Python's built-in logging - no external dependencies needed.
"""
import logging
import sys


def setup_logging(log_level: str = "INFO", service_name: str = "healthlink") -> logging.Logger:
    """
    Configure logging for a service with Python's built-in logger.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        service_name: Root logger name for this service (e.g. "healthlink.symptom")

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(service_name)
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level.upper()))

    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.info(f"Logging initialized at {log_level} level for {service_name}")

    return logger


def get_logger(name: str = "healthlink") -> logging.Logger:
    """Get a logger instance by name."""
    return logging.getLogger(name)
