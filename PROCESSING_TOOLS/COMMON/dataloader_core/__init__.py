"""
dataloader_core - Shared Core SDK for DATA_LOADER

Provides centralized configuration loading, POSIX advisory file locking,
Teradata credential resolution & connection pooling, entity mapping,
manifest parsing, streaming checksum calculation, in-memory CSV/archive header
inspection, Batch Capsule path resolution & `BatchDescriptor` serialization,
and logging utilities across BICC_INTAKE_CONTROLLER and DATA_INGESTION_ORCHESTRATOR.
"""

from .capsule import BatchDescriptor, CapsulePathResolver
from .checksum import compute_file_checksum
from .config import ConfigLoader, expand_env_vars, load_json_config, resolve_zone_path
from .db import (
    TeradataConnectionManager,
    build_tpt_environment,
    get_teradata_connection,
    resolve_teradata_credentials,
    validate_sql_identifier,
)
from .exceptions import (
    BatchValidationError,
    ConfigurationError,
    DataLoaderError,
    LockTimeoutError,
    OrchestratorExecutionError,
    SchemaSyncError,
)
from .locking import ProcessLock, UtilitySlotGovernor, is_pid_alive, read_pid_file, wait_for_pid_completion
from .logging_utils import (
    LoggingFactory,
    add_batch_file_logger,
    attach_batch_file_logger,
    detach_batch_file_logger,
    setup_feeder_logger,
    setup_orchestrator_console_logger,
)
from .manifest import (
    MANIFEST_PATTERNS,
    ManifestEntry,
    ManifestHandler,
    ManifestMetadata,
    extract_batch_id_from_filenames,
    parse_manifest_filename,
    read_manifest_entries,
    write_standardized_manifest,
)
from .mapping import EntityMapper, EntityRule, inspect_file_inner_extension
from .schema_reader import (
    clean_column_name,
    extract_csv_columns,
    select_header_chunk_file,
    validate_column_type,
)

__all__ = [
    "BatchDescriptor",
    "BatchValidationError",
    "CapsulePathResolver",
    "ConfigLoader",
    "ConfigurationError",
    "DataLoaderError",
    "EntityMapper",
    "EntityRule",
    "LockTimeoutError",
    "LoggingFactory",
    "MANIFEST_PATTERNS",
    "ManifestEntry",
    "ManifestHandler",
    "ManifestMetadata",
    "OrchestratorExecutionError",
    "ProcessLock",
    "SchemaSyncError",
    "TeradataConnectionManager",
    "UtilitySlotGovernor",
    "add_batch_file_logger",
    "attach_batch_file_logger",
    "build_tpt_environment",
    "clean_column_name",
    "compute_file_checksum",
    "detach_batch_file_logger",
    "expand_env_vars",
    "extract_batch_id_from_filenames",
    "extract_csv_columns",
    "get_teradata_connection",
    "inspect_file_inner_extension",
    "is_pid_alive",
    "load_json_config",
    "parse_manifest_filename",
    "read_manifest_entries",
    "read_pid_file",
    "resolve_teradata_credentials",
    "resolve_zone_path",
    "select_header_chunk_file",
    "setup_feeder_logger",
    "setup_orchestrator_console_logger",
    "validate_column_type",
    "validate_sql_identifier",
    "wait_for_pid_completion",
    "write_standardized_manifest",
]
