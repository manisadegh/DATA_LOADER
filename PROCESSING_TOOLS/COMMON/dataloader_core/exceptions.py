"""
dataloader_core/exceptions.py - Typed Domain Exceptions for DATA_LOADER

Defines a structured exception hierarchy used across BICC_INTAKE_CONTROLLER,
DATA_INGESTION_ORCHESTRATOR, and dataloader_core utilities so service methods
raise typed exceptions instead of invoking sys.exit() inside business logic.
"""

from __future__ import annotations


class DataLoaderError(Exception):
    """Base exception for all DATA_LOADER operational and domain errors."""


class ConfigurationError(DataLoaderError):
    """Raised when configuration files or required parameters are missing or invalid."""


class LockTimeoutError(DataLoaderError):
    """Raised when waiting for an active PID or POSIX advisory file lock exceeds timeout."""


class BatchValidationError(DataLoaderError, ValueError):
    """
    Raised when batch validation fails:
      - Missing or 0-byte manifested files
      - Cryptographic checksum mismatch
      - Unmapped entity signatures
      - OPS-01 Single-Batch or unmanifested orphan file violations
    """


class SchemaSyncError(DataLoaderError, RuntimeError):
    """
    Raised when Schema Guard synchronization is blocked (e.g. auto_migrate_ddl=False
    or destructive drift in append mode) or when DDL execution fails.
    Inherits from RuntimeError to preserve backward compatibility with callers/tests.
    """


class OrchestratorExecutionError(DataLoaderError):
    """Raised when Orchestrator subprocess delegation or entity worker execution fails."""
