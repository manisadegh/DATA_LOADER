"""
dataloader_core/intake/base_controller.py - Pluggable Intake Producer Controller Base

Implements the Template Method pattern for flat-file intake across all source systems:
  1. Concurrency isolation (.feeder_<source>.pid) via ProcessLock
  2. Multi-batch discovery via SourceIntakePlugin
  3. Chronological FIFO queue ordering
  4. Payload stability verification (>0 bytes, settling window)
  5. In-memory CSV/archive header extraction via schema_reader
  6. Per-entity mapping and attribute resolution via EntityMapper
  7. Manifest normalization & MD5 streaming
  8. Atomic Batch Capsule publishing into LANDING_ZONE/<SOURCE>/BATCH_<TS>_<ID>/
  9. Optional FAIL_STOP delegation to DATA_INGESTION_ORCHESTRATOR
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from dataloader_core.capsule import BatchDescriptor, CapsulePathResolver
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.config import ConfigLoader
from dataloader_core.exceptions import (
    BatchValidationError,
    ConfigurationError,
    DataLoaderError,
    OrchestratorExecutionError,
)
from dataloader_core.locking import ProcessLock
from dataloader_core.logging_utils import LoggingFactory
from dataloader_core.mapping import EntityMapper
from dataloader_core.schema_reader import extract_csv_columns, select_header_chunk_file

from .plugin import (
    BICCIntakePlugin,
    PluginRegistry,
    RawBatchCandidate,
    SourceIntakePlugin,
)


class BaseIntakeController:
    """
    Template Method controller orchestrating generic intake mechanics decoupled from
    source-specific file discovery and formats.
    """

    def __init__(
        self,
        config_path: str,
        source_override: Optional[str] = None,
        skip_post_tasks: bool = False,
        enqueue_only: bool = False,
        plugin: Optional[SourceIntakePlugin] = None,
    ) -> None:
        self.config_path = config_path
        self.config = ConfigLoader.load_json_config(config_path)
        self.base_dir = os.path.dirname(os.path.abspath(config_path))
        self.skip_post_tasks = skip_post_tasks
        self.enqueue_only = enqueue_only

        self.feeder_cfg = self.config.get("feeder", {})
        self.schema_cfg = self.config.get("schema_guard", {})
        self.orch_bridge_cfg = self.config.get("orchestrator", {})

        self.settling_sec = self.feeder_cfg.get("file_stability_window_seconds", 5)
        self.default_source = source_override or self.feeder_cfg.get("source_system_code", "ORACLE_FUSION")
        self.source_post_tasks = self.feeder_cfg.get("post_ingestion_tasks")

        concurrency_cfg = self.feeder_cfg.get("concurrency", {})
        self.poll_interval_sec = concurrency_cfg.get("poll_interval_seconds", 5)
        self.lock_timeout_sec = concurrency_cfg.get("lock_timeout_seconds", 7200)

        drop_zone_cfg = self.feeder_cfg.get("drop_zone")
        if not drop_zone_cfg:
            raise ConfigurationError("Configuration error: 'feeder.drop_zone' is required.")
        self.drop_zone = ConfigLoader.resolve_path(
            self.base_dir, drop_zone_cfg, source=self.default_source, ensure_exists=True
        )

        logs_dir_cfg = self.feeder_cfg.get("logs_dir") or os.path.join(self.base_dir, "logs")
        self.logs_dir = ConfigLoader.resolve_path(
            self.base_dir, logs_dir_cfg, source=self.default_source, ensure_exists=True
        )

        mapping_cfg = (
            self.feeder_cfg.get("entity_mapping_file")
            or self.schema_cfg.get("entity_mapping_file")
            or "entity_mapping.csv"
        )
        self.mapping_file = (
            mapping_cfg
            if os.path.isabs(mapping_cfg)
            else os.path.normpath(os.path.join(self.base_dir, mapping_cfg))
        )

        orch_dir_cfg = self.orch_bridge_cfg.get("orchestrator_dir", "../DATA_INGESTION_ORCHESTRATOR")
        self.orch_dir = (
            orch_dir_cfg
            if os.path.isabs(orch_dir_cfg)
            else os.path.normpath(os.path.join(self.base_dir, orch_dir_cfg))
        )
        self.orch_config = self.orch_bridge_cfg.get("config_file", "config.json")

        landing_cfg = self.orch_bridge_cfg.get("landing_zone")
        if landing_cfg:
            self.landing_zone_base = (
                landing_cfg
                if os.path.isabs(landing_cfg)
                else os.path.normpath(os.path.join(self.base_dir, landing_cfg))
            )
        else:
            self.landing_zone_base = os.path.normpath(os.path.join(self.orch_dir, "../LANDING_ZONE"))

        self.python_bin = self.orch_bridge_cfg.get("python_executable", "python3")
        self.trigger_orchestrator = (
            False
            if self.enqueue_only
            else bool(self.orch_bridge_cfg.get("trigger_orchestrator", True))
        )

        self.logger = LoggingFactory.setup_feeder_logger(self.logs_dir, source=self.default_source)

        # Resolve Source Plugin
        if plugin is not None:
            self.plugin = plugin
        else:
            plugin_name = self.feeder_cfg.get("intake_plugin")
            if self.default_source != "ORACLE_FUSION" and (not plugin_name or plugin_name.lower() in ("bicc", "oracle_fusion")):
                plugin_name = self.default_source
            self.plugin = PluginRegistry.get_plugin(plugin_name, default_source=self.default_source)

        self.mapper = EntityMapper(self.mapping_file, default_source=self.default_source)

        self.logger.info("=" * 70)
        self.logger.info(f"STARTING INTAKE PRODUCER RUN (Source: {self.default_source}, Plugin: {self.plugin.__class__.__name__})")
        self.logger.info("=" * 70)
        self.logger.info(f"Drop Zone: {self.drop_zone}")
        self.logger.info(f"Landing Zone: {self.landing_zone_base}")
        self.logger.info(f"Orchestrator Directory: {self.orch_dir}")
        self.logger.info(f"Trigger Orchestrator: {self.trigger_orchestrator}")

    def acquire_concurrency_guards(self) -> ProcessLock:
        """Acquires `.feeder_<source>.pid` ProcessLock in drop_zone."""
        feeder_lock_file = os.path.join(self.drop_zone, f".feeder_{self.default_source}.pid")
        return ProcessLock(
            lock_file=feeder_lock_file,
            poll_interval_sec=self.poll_interval_sec,
            timeout_sec=self.lock_timeout_sec,
            logger=self.logger,
            label=f"{self.default_source} Intake Controller",
        )

    def discover_and_sort_batches(self) -> List[RawBatchCandidate]:
        """Discovers raw batches via plugin and returns them in ascending FIFO chronological order."""
        candidates = self.plugin.discover_raw_batches(self.drop_zone)
        candidates.sort(key=lambda c: c.sort_key)
        return candidates

    def verify_payload_stability(self, candidate: Union[RawBatchCandidate, Dict[str, Any]]) -> None:
        """Verifies that all files declared for candidate exist, are > 0 bytes, and sizes remain stable."""
        batch_id = candidate.batch_id if isinstance(candidate, RawBatchCandidate) else candidate["batch_id"]
        declared_files = candidate.declared_files if isinstance(candidate, RawBatchCandidate) else candidate["declared_files"]

        if not declared_files:
            raise BatchValidationError(f"Batch {batch_id} declared 0 files. Aborting under FAIL_STOP.")

        initial_sizes: Dict[str, int] = {}
        for fname in declared_files:
            f_path = os.path.join(self.drop_zone, fname) if not os.path.isabs(fname) else fname
            if not os.path.exists(f_path):
                raise BatchValidationError(f"File '{fname}' declared for batch {batch_id} is missing in drop zone.")
            size = os.path.getsize(f_path)
            if size == 0:
                raise BatchValidationError(f"File '{fname}' for batch {batch_id} is 0 bytes (empty upload). Aborting.")
            initial_sizes[fname] = size

        if self.settling_sec > 0:
            time.sleep(self.settling_sec)
            for fname, init_size in initial_sizes.items():
                f_path = os.path.join(self.drop_zone, fname) if not os.path.isabs(fname) else fname
                curr_size = os.path.getsize(f_path)
                if curr_size != init_size:
                    raise BatchValidationError(
                        f"Payload stability check failed for batch {batch_id}: "
                        f"File '{fname}' size changed during settling window ({init_size} -> {curr_size}). Upload in progress."
                    )

    def stage_and_publish_batch(self, candidate: Union[RawBatchCandidate, Dict[str, Any]]) -> str:
        """Stages files and publishes a self-contained Batch Capsule in LANDING_ZONE."""
        batch_id = candidate.batch_id if isinstance(candidate, RawBatchCandidate) else candidate["batch_id"]
        source = candidate.source if isinstance(candidate, RawBatchCandidate) else candidate.get("source", self.default_source)
        raw_ts = candidate.extract_timestamp_raw if isinstance(candidate, RawBatchCandidate) else candidate["extract_timestamp"]
        clean_ts = CapsulePathResolver.normalize_timestamp_token(raw_ts)
        declared_files = candidate.declared_files if isinstance(candidate, RawBatchCandidate) else candidate["declared_files"]
        raw_manifest_path = candidate.manifest_path if isinstance(candidate, RawBatchCandidate) else candidate.get("manifest_path")

        # Map files to target entities
        file_to_table: Dict[str, str] = {}
        entity_files: Dict[str, List[str]] = {}
        entity_rules: Dict[str, Any] = {}
        for fname in declared_files:
            f_full = os.path.join(self.drop_zone, fname) if not os.path.isabs(fname) else fname
            rule = self.mapper.match_file(fname, file_dir=self.drop_zone, source=source)
            if not rule:
                raise BatchValidationError(
                    f"Batch {batch_id} contains unmapped file '{fname}'. Ingestion blocked by EntityMapper."
                )
            tgt = rule.target_table
            file_to_table[fname] = tgt
            entity_files.setdefault(tgt, []).append(fname)
            entity_rules[tgt] = rule

        # In-memory header extraction and MD5 computation
        file_checksum_pairs: List[Tuple[str, str]] = []
        receipt_payload: List[Dict[str, Any]] = []
        entities_desc: Dict[str, Dict[str, Any]] = {}

        for tgt, files in entity_files.items():
            rule = entity_rules[tgt]
            header_chunk = select_header_chunk_file(files)
            header_chunk_path = os.path.join(self.drop_zone, header_chunk)
            cols = extract_csv_columns(header_chunk_path, delimiter=rule.delimiter)

            entities_desc[tgt] = {
                "target_table": tgt,
                "signature": rule.signature,
                "extension": rule.raw_extension,
                "inner_extension": rule.inner_extension,
                "delimiter": rule.delimiter,
                "load_mode": rule.load_mode,
                "skip_rows": rule.skip_rows,
                "header_mode": rule.header_mode,
                "header_columns": cols,
                "files": [],
                "data_files": files,
                "file_count": len(files),
            }
            self.logger.info(f"[{tgt}] Extracted {len(cols)} header column(s) in memory from '{header_chunk}'.")

        for fname in declared_files:
            f_path = os.path.join(self.drop_zone, fname)
            md5 = compute_file_checksum(f_path, algorithm="md5")
            size = os.path.getsize(f_path)
            file_checksum_pairs.append((fname, md5))
            tgt = file_to_table[fname]
            file_entry = {
                "filename": fname,
                "filesize_bytes": size,
                "md5": md5,
            }
            entities_desc[tgt]["files"].append(file_entry)
            receipt_payload.append({
                "filename": fname,
                "checksum": md5,
                "size_bytes": size,
                "target_table": tgt,
            })

        # Stage and publish capsule
        target_landing_zone = ConfigLoader.resolve_path(
            self.base_dir, self.landing_zone_base, source=source, ensure_exists=True
        )
        capsule_dir, descriptor = CapsulePathResolver.stage_and_publish_queue_capsule(
            landing_zone_dir=target_landing_zone,
            landing_zone_base=self.landing_zone_base,
            source=source,
            batch_id=batch_id,
            extract_timestamp=raw_ts,
            raw_manifest_path=raw_manifest_path,
            declared_files=declared_files,
            file_checksum_pairs=file_checksum_pairs,
            receipt_payload=receipt_payload,
            entities_descriptor=entities_desc,
            drop_zone_dir=self.drop_zone,
        )
        capsule_path = str(capsule_dir)

        self.logger.info(
            f"Published queued Batch Capsule '{capsule_path}' "
            f"(manifest='{descriptor.standardized_manifest}', files={len(declared_files)})."
        )
        return str(capsule_path)

    def _write_post_tasks_file(self) -> Optional[str]:
        """Writes source-specific post-ingestion tasks JSON for the Orchestrator."""
        if not self.source_post_tasks:
            return None
        clean_src = CapsulePathResolver.sanitize_token(self.default_source)
        target_dir = os.path.join(self.logs_dir, clean_src)
        os.makedirs(target_dir, exist_ok=True)
        post_tasks_file = os.path.join(target_dir, f".post_tasks_{clean_src}.json")
        try:
            with open(post_tasks_file, "w", encoding="utf-8") as ptf:
                json.dump(self.source_post_tasks, ptf, indent=2)
            self.logger.info(f"Generated source-specific post-tasks file for Orchestrator: '{post_tasks_file}'")
            return post_tasks_file
        except Exception as exc:
            self.logger.warning(f"Could not write post-tasks file '{post_tasks_file}': {exc}")
            return None

    def invoke_orchestration_stage(self) -> int:
        """Launches DATA_INGESTION_ORCHESTRATOR via subprocess and streams logs."""
        orch_script = os.path.join(self.orch_dir, "orchestrator.py")
        if not os.path.exists(orch_script):
            raise OrchestratorExecutionError(f"orchestrator.py not found at '{orch_script}'")

        cmd = [self.python_bin, orch_script, "--config", self.orch_config, "--source", self.default_source]
        if self.skip_post_tasks:
            cmd.append("--skip-post-tasks")

        post_tasks_file = self._write_post_tasks_file()
        if post_tasks_file:
            cmd.extend(["--post-tasks-file", post_tasks_file])

        extra_env = os.environ.copy()
        if "auto_migrate_ddl" in self.schema_cfg:
            extra_env["DL_AUTO_MIGRATE_DDL"] = "true" if self.schema_cfg.get("auto_migrate_ddl") else "false"

        self.logger.info(f"Invoking Orchestrator: {' '.join(cmd)} (cwd: '{self.orch_dir}')")
        proc = subprocess.Popen(
            cmd,
            cwd=self.orch_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=extra_env,
        )

        try:
            for line in iter(proc.stdout.readline, ""):
                if line:
                    self.logger.info(f"[ORCHESTRATOR] {line.rstrip()}")
        finally:
            if proc.stdout:
                proc.stdout.close()

        rc = proc.wait()
        if rc != 0:
            raise OrchestratorExecutionError(f"Orchestrator failed with non-zero exit code {rc} under FAIL_STOP.")
        self.logger.info(f"Orchestrator completed successfully with exit code 0.")
        return 0

    def run(self) -> int:
        """Executes the full intake producer lifecycle."""
        with self.acquire_concurrency_guards():
            candidates = self.discover_and_sort_batches()
            if not candidates:
                self.logger.info("Drop zone is empty. No batches to process.")
                if self.trigger_orchestrator and not self.enqueue_only:
                    self.logger.info("Checking Orchestrator for in-flight crash recovery or pending queue...")
                    try:
                        return self.invoke_orchestration_stage()
                    except OrchestratorExecutionError as oee:
                        self.logger.error(f"Orchestrator delegation failed: {oee}")
                        return 1
                return 0

            self.logger.info(
                f"Discovered {len(candidates)} batch(es) in drop zone. Enqueueing in FIFO order:"
            )
            for idx, c in enumerate(candidates, 1):
                self.logger.info(
                    f"  [{idx}/{len(candidates)}] Batch ID: {c.batch_id}, Extract TS: {c.extract_timestamp_raw}, Files: {len(c.declared_files)}"
                )

            try:
                for idx, candidate in enumerate(candidates, 1):
                    self.logger.info("-" * 70)
                    self.logger.info(
                        f"ENQUEUEING BATCH {idx}/{len(candidates)}: ID={candidate.batch_id} "
                        f"(Source={candidate.source}, TS={candidate.extract_timestamp_raw})"
                    )
                    self.logger.info("-" * 70)
                    self.verify_payload_stability(candidate)
                    self.stage_and_publish_batch(candidate)

                if self.enqueue_only:
                    self.logger.info(f"Enqueue-only mode active. All {len(candidates)} batch(es) staged in LANDING_ZONE.")
                    return 0

                if self.trigger_orchestrator:
                    self.invoke_orchestration_stage()

                self.logger.info("=" * 70)
                self.logger.info(f"ALL {len(candidates)} BATCHES PROCESSED WITH 100% SUCCESS!")
                self.logger.info("=" * 70)
                return 0
            except DataLoaderError as dle:
                self.logger.error(f"Intake pipeline error: {dle}")
                return 1
            except Exception as exc:
                self.logger.exception(f"FATAL: Unhandled exception during intake: {exc}")
                return 1
