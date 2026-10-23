"""
dataloader_core/intake/plugin.py - Pluggable Source Intake Plugin Framework

Defines the contract for raw batch discovery, metadata extraction, and payload
preparation across heterogeneous source extract patterns (BICC, Standard Manifest,
Manifestless Drop, etc.).
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from dataloader_core.manifest import (
    MANIFEST_PATTERNS,
    ManifestMetadata,
    extract_batch_id_from_filenames,
    parse_manifest_filename,
    read_manifest_entries,
)

logger = logging.getLogger("dataloader_core.intake.plugin")


@dataclass
class RawBatchCandidate:
    """Represents a discovered raw batch candidate in DROP_ZONE prior to capsule staging."""

    batch_id: str
    source: str
    extract_timestamp_raw: str
    sort_key: Tuple[float, Any]
    manifest_path: Optional[str]
    declared_files: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "source": self.source,
            "extract_timestamp": self.extract_timestamp_raw,
            "extract_timestamp_raw": self.extract_timestamp_raw,
            "sort_key": self.sort_key,
            "manifest_path": self.manifest_path,
            "manifest_filename": os.path.basename(self.manifest_path) if self.manifest_path else "",
            "declared_files": list(self.declared_files),
            "metadata": dict(self.metadata),
        }

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


class SourceIntakePlugin(ABC):
    """Abstract base class for source intake plugins."""

    source_code: str = ""

    def __init__(self, source_code: Optional[str] = None) -> None:
        if source_code:
            self.source_code = source_code

    @abstractmethod
    def discover_raw_batches(self, drop_zone: str) -> List[RawBatchCandidate]:
        """Discovers raw batches in drop_zone and returns candidates."""
        pass

    def preprocess_candidate(self, candidate: RawBatchCandidate, drop_zone: str) -> None:
        """Optional hook to validate or transform candidate before staging."""
        pass

    def prepare_payload_files(
        self, candidate: RawBatchCandidate, drop_zone: str
    ) -> List[Tuple[str, str]]:
        """Returns list of (source_path, dest_filename) for the payload."""
        pairs = []
        for fname in candidate.declared_files:
            src = os.path.join(drop_zone, fname) if not os.path.isabs(fname) else fname
            pairs.append((src, os.path.basename(fname)))
        return pairs


class BICCIntakePlugin(SourceIntakePlugin):
    """
    Intake plugin for Oracle Fusion Cloud BICC extracts.
    Discovers MANIFEST*.MF files, resolves batch IDs from filenames if omitted,
    and sorts FIFO chronologically.
    """

    source_code = "ORACLE_FUSION"

    def discover_raw_batches(self, drop_zone: str) -> List[RawBatchCandidate]:
        if not os.path.exists(drop_zone):
            return []

        candidates: List[RawBatchCandidate] = []
        for f in os.listdir(drop_zone):
            if f.upper().endswith(".MF") and not f.startswith("."):
                full_path = os.path.join(drop_zone, f)
                meta = parse_manifest_filename(f, default_source=self.source_code)
                try:
                    entries = read_manifest_entries(full_path, require_non_empty=False)
                    declared_files = [e.filename for e in entries]
                except Exception as e:
                    logger.error(f"Failed to read manifest '{f}': {e}")
                    continue

                payload_batch_id = extract_batch_id_from_filenames(declared_files)
                b_id = payload_batch_id or meta.batch_id
                s_key = (meta.sort_key[0], b_id) if payload_batch_id else meta.sort_key

                if s_key[0] == 0.0:
                    mtime = os.path.getmtime(full_path)
                    dt_mtime = datetime.fromtimestamp(mtime)
                    s_key = (mtime, s_key[1])
                    extract_ts = dt_mtime.strftime("%Y%m%d_%H%M%S")
                else:
                    extract_ts = meta.extract_timestamp_raw

                candidates.append(
                    RawBatchCandidate(
                        batch_id=str(b_id),
                        source=meta.source,
                        extract_timestamp_raw=extract_ts,
                        sort_key=s_key,
                        manifest_path=full_path,
                        declared_files=declared_files,
                        metadata=meta.to_dict(),
                    )
                )

        return sorted(candidates, key=lambda c: c.sort_key)


class StandardManifestIntakePlugin(SourceIntakePlugin):
    """
    Intake plugin for standard external sources (e.g. CRM, SAP_ERP, TREASURY)
    that deposit standardized manifests (MANIFEST_<SOURCE>_<TS>_<ID>.MF or *.ctl / *.mf).
    """

    source_code = "STANDARD"

    def discover_raw_batches(self, drop_zone: str) -> List[RawBatchCandidate]:
        if not os.path.exists(drop_zone):
            return []

        candidates: List[RawBatchCandidate] = []
        for f in os.listdir(drop_zone):
            upper_f = f.upper()
            if (upper_f.endswith(".MF") or upper_f.endswith(".CTL")) and not f.startswith("."):
                full_path = os.path.join(drop_zone, f)
                meta = parse_manifest_filename(f, default_source=self.source_code)
                try:
                    entries = read_manifest_entries(full_path, require_non_empty=False)
                    declared_files = [e.filename for e in entries]
                except Exception as e:
                    logger.error(f"Failed to read manifest '{f}': {e}")
                    continue

                payload_batch_id = extract_batch_id_from_filenames(declared_files)
                b_id = payload_batch_id or meta.batch_id
                s_key = (meta.sort_key[0], b_id) if payload_batch_id else meta.sort_key

                if s_key[0] == 0.0:
                    mtime = os.path.getmtime(full_path)
                    dt_mtime = datetime.fromtimestamp(mtime)
                    s_key = (mtime, s_key[1])
                    extract_ts = dt_mtime.strftime("%Y%m%d_%H%M%S")
                else:
                    extract_ts = meta.extract_timestamp_raw

                candidates.append(
                    RawBatchCandidate(
                        batch_id=str(b_id),
                        source=meta.source or self.source_code,
                        extract_timestamp_raw=extract_ts,
                        sort_key=s_key,
                        manifest_path=full_path,
                        declared_files=declared_files,
                        metadata=meta.to_dict(),
                    )
                )

        return sorted(candidates, key=lambda c: c.sort_key)


class ManifestlessDropIntakePlugin(SourceIntakePlugin):
    """
    Intake plugin for ad-hoc / standalone data drops lacking a manifest.
    Discovers all .csv / .zip / .gz files in DROP_ZONE, derives batch metadata
    from filename tokens or modification times, and groups them into batches.
    """

    source_code = "MANIFESTLESS"

    def discover_raw_batches(self, drop_zone: str) -> List[RawBatchCandidate]:
        if not os.path.exists(drop_zone):
            return []

        candidates: List[RawBatchCandidate] = []
        data_files = [
            f
            for f in os.listdir(drop_zone)
            if not f.startswith(".")
            and not f.upper().endswith((".MF", ".PID", ".TMP", ".LOCK"))
            and os.path.isfile(os.path.join(drop_zone, f))
        ]

        if not data_files:
            return []

        batch_groups: Dict[str, List[str]] = {}
        for fname in data_files:
            b_id = extract_batch_id_from_filenames([fname])
            if b_id:
                group_key = b_id
            else:
                f_path = os.path.join(drop_zone, fname)
                group_key = "ADHOC_" + datetime.fromtimestamp(os.path.getmtime(f_path)).strftime("%Y%m%d_%H%M%S")
            batch_groups.setdefault(group_key, []).append(fname)

        for group_id, files in batch_groups.items():
            first_file = os.path.join(drop_zone, files[0])
            mtime = os.path.getmtime(first_file)
            ts_str = datetime.fromtimestamp(mtime).strftime("%Y%m%d_%H%M%S")
            candidates.append(
                RawBatchCandidate(
                    batch_id=group_id,
                    source=self.source_code,
                    extract_timestamp_raw=ts_str,
                    sort_key=(mtime, group_id),
                    manifest_path=None,
                    declared_files=sorted(files),
                    metadata={"source": self.source_code, "batch_id": group_id, "manifestless": True},
                )
            )

        return sorted(candidates, key=lambda c: c.sort_key)


class PluginRegistry:
    """Registry mapping source codes or plugin identifiers to SourceIntakePlugin classes."""

    _registry: Dict[str, Type[SourceIntakePlugin]] = {}

    @classmethod
    def register(cls, name_or_source: str, plugin_cls: Type[SourceIntakePlugin]) -> None:
        cls._registry[name_or_source.strip().upper()] = plugin_cls

    @classmethod
    def get_plugin(
        cls,
        name_or_source: Optional[str] = None,
        default_source: Optional[str] = None,
    ) -> SourceIntakePlugin:
        effective_source = default_source or "ORACLE_FUSION"
        lookup_key = (name_or_source or effective_source).strip().upper()

        if lookup_key in cls._registry:
            plugin_cls = cls._registry[lookup_key]
            return plugin_cls(source_code=effective_source)

        if lookup_key in ("BICC", "ORACLE_FUSION", "BICC_INTAKE", "BICCINTAKEPLUGIN"):
            return BICCIntakePlugin(source_code=effective_source)
        if lookup_key in ("STANDARD", "STANDARD_MANIFEST", "STANDARDMANIFESTINTAKEPLUGIN", "CRM", "SAP_ERP", "TREASURY"):
            return StandardManifestIntakePlugin(source_code=effective_source)
        if lookup_key in ("MANIFESTLESS", "ADHOC", "DROPS", "MANIFESTLESSDROPINTAKEPLUGIN"):
            return ManifestlessDropIntakePlugin(source_code=effective_source)

        return BICCIntakePlugin(source_code=effective_source)


PluginRegistry.register("BICC", BICCIntakePlugin)
PluginRegistry.register("ORACLE_FUSION", BICCIntakePlugin)
PluginRegistry.register("STANDARD_MANIFEST", StandardManifestIntakePlugin)
PluginRegistry.register("CRM", StandardManifestIntakePlugin)
PluginRegistry.register("MANIFESTLESS", ManifestlessDropIntakePlugin)
