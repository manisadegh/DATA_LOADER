"""
dataloader_core/logging_utils.py - Centralized Logging Factory for Feeder & Orchestrator

Standardizes console and Batch Capsule file logger initialization across
BICC_INTAKE_CONTROLLER and DATA_INGESTION_ORCHESTRATOR using CapsulePathResolver.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Optional

from .capsule import CapsulePathResolver

FEEDER_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
ORCHESTRATOR_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(threadName)-12s | %(message)s"


def setup_feeder_logger(logs_dir: str, source: Optional[str] = None) -> logging.Logger:
    """
    Sets up dual stream and dedicated file logging in `logs_dir`:
      LOGS/[<SOURCE>/]LOG_FEEDER_<SOURCE>_<YYYYMMDD_HHMMSS>.log
    """
    os.makedirs(logs_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    src_tag = f"_{source}" if source else ""
    log_file = os.path.join(logs_dir, f"LOG_FEEDER{src_tag}_{ts}.log")

    logger = logging.getLogger("BICC_INTAKE_CONTROLLER")
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        try:
            h.close()
        except Exception:
            pass
    logger.handlers.clear()

    formatter = logging.Formatter(fmt=FEEDER_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    logger.info(f"Initialized BICC Intake Controller log file: '{log_file}'")
    return logger


def setup_orchestrator_console_logger() -> logging.Logger:
    """Initializes bootstrap console logger for DATA_INGESTION_ORCHESTRATOR."""
    logger = logging.getLogger("DATA_INGESTION_ORCHESTRATOR")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(logging.Formatter(ORCHESTRATOR_LOG_FORMAT))
        logger.addHandler(stdout_handler)
    return logger


def detach_batch_file_logger(logger: Optional[logging.Logger] = None) -> None:
    """Closes and removes all FileHandlers attached to the orchestrator logger."""
    if logger is None:
        logger = logging.getLogger("DATA_INGESTION_ORCHESTRATOR")
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            try:
                handler.close()
            except Exception:
                pass
            try:
                logger.removeHandler(handler)
            except Exception:
                pass


def attach_batch_file_logger(
    logger: logging.Logger,
    capsule_or_logs_dir: str,
    source: str,
    extract_timestamp: str,
    batch_id: str,
) -> str:
    """
    Attaches a dedicated run-specific FileHandler inside the Batch Log Capsule:
      LOGS/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/LOG_ORCHESTRATOR_<SOURCE>_<EXTRACT_TS>_<BATCH_ID>_<EXEC_TS>.log
    Uses `CapsulePathResolver.get_log_capsule_dir` (exact path-segment matching).
    """
    # Detach any previous batch FileHandlers to prevent stale handlers across batches/tests
    detach_batch_file_logger(logger)

    clean_src = CapsulePathResolver.sanitize_token(source)
    clean_ext = CapsulePathResolver.normalize_timestamp_token(extract_timestamp)
    clean_batch = CapsulePathResolver.sanitize_token(batch_id)

    target_dir = CapsulePathResolver.get_log_capsule_dir(
        logs_base=capsule_or_logs_dir,
        source=clean_src,
        batch_id=clean_batch,
        ts=clean_ext,
        ensure_exists=True,
    )

    execution_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"LOG_ORCHESTRATOR_{clean_src}_{clean_ext}_{clean_batch}_{execution_ts}.log"
    log_filepath = os.path.join(target_dir, log_filename)

    file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(ORCHESTRATOR_LOG_FORMAT))
    logger.addHandler(file_handler)

    logger.info(f"Initialized run log file: {log_filepath}")
    return log_filepath


def add_batch_file_logger(logs_dir: str, source: str, extract_timestamp: str, batch_id: str) -> str:
    """Backward-compatible helper attaching batch file handler to DATA_INGESTION_ORCHESTRATOR logger."""
    logger = logging.getLogger("DATA_INGESTION_ORCHESTRATOR")
    return attach_batch_file_logger(logger, logs_dir, source, extract_timestamp, batch_id)


class LoggingFactory:
    """Facade class for feeder and orchestrator logger setup."""

    setup_feeder_logger = staticmethod(setup_feeder_logger)
    setup_orchestrator_console_logger = staticmethod(setup_orchestrator_console_logger)
    attach_batch_file_logger = staticmethod(attach_batch_file_logger)
    detach_batch_file_logger = staticmethod(detach_batch_file_logger)
