"""
dataloader_core/mapping.py - Entity Mapping & Archive Inner-Extension Inspector

Centralizes `entity_mapping.csv` loading, `.zip`/`.gz` inner-extension inspection
(`.csv` payload vs `.pecsv` primary-key extract), and the 2-pass entity matching
algorithm shared between BICC_INTAKE_CONTROLLER and DATA_INGESTION_ORCHESTRATOR.
"""

from __future__ import annotations

import csv
import logging
import os
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("dataloader_core.mapping")


@dataclass
class EntityRule:
    """Represents a single row from entity_mapping.csv with dict-compatible access."""

    source: str
    target_table: str
    signature: str
    extensions: List[str] = field(default_factory=lambda: [".csv"])
    inner_extension: str = ".csv"
    raw_extension: str = ".csv"
    delimiter: str = ","
    load_mode: str = "replace"
    skip_rows: int = 1
    header_mode: str = "first_chunk_only"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target_table": self.target_table,
            "signature": self.signature,
            "extension": self.raw_extension,
            "extensions": list(self.extensions),
            "inner_extension": self.inner_extension,
            "delimiter": self.delimiter,
            "load_mode": self.load_mode,
            "skip_rows": self.skip_rows,
            "header_mode": self.header_mode,
        }

    def __getitem__(self, key: str) -> Any:
        mapping = self.to_dict()
        if key in mapping:
            return mapping[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


def inspect_file_inner_extension(file_path: str) -> str:
    """
    Returns the effective inner extension of a file.
    If the file is a .zip archive, inspects its members in memory:
      - Returns '.pecsv' if any member ends in .pecsv (Active Keys)
      - Returns '.csv' if any member ends in .csv (Data Payload)
      - Falls back to the extension of the first member
    If .gz compressed, strips .gz and returns '.csv' or '.pecsv'.
    If uncompressed, returns the file's own extension (e.g. '.csv', '.pecsv').
    """
    lower_p = file_path.lower()
    if lower_p.endswith(".zip") and os.path.exists(file_path):
        try:
            with zipfile.ZipFile(file_path, "r") as z:
                names = [n.lower() for n in z.namelist()]
                if any(n.endswith(".pecsv") for n in names):
                    return ".pecsv"
                if any(n.endswith(".csv") for n in names):
                    return ".csv"
                if names:
                    return os.path.splitext(names[0])[1]
        except Exception as exc:
            logger.warning(f"Unable to inspect ZIP archive '{file_path}': {exc}")
    if lower_p.endswith(".gz"):
        base = lower_p[:-3]
        inner_ext = os.path.splitext(base)[1]
        if inner_ext in (".csv", ".pecsv"):
            return inner_ext
        return ".csv"
    return os.path.splitext(file_path)[1].lower()


class EntityMapper:
    """
    Loads and caches `entity_mapping.csv` rules and resolves data filenames
    to target staging tables using a 2-pass matching algorithm.
    """

    inspect_inner_extension = staticmethod(inspect_file_inner_extension)

    def __init__(
        self,
        mapping_file: Optional[str] = None,
        default_source: Optional[str] = None,
    ) -> None:
        self.mapping_file = mapping_file
        self.default_source = default_source
        self._cached_all_rules: Optional[List[EntityRule]] = None
        self._cached_file_path: Optional[str] = None
        if mapping_file and os.path.exists(mapping_file):
            self.load_rules(mapping_file)

    @staticmethod
    def _source_matches(rule_source: str, filter_source: Optional[str]) -> bool:
        if not filter_source:
            return True
        clean_rule_src = (rule_source or "").strip()
        if not clean_rule_src or clean_rule_src == "*":
            return True
        allowed = [s.strip().upper() for s in clean_rule_src.split(",") if s.strip()]
        return filter_source.strip().upper() in allowed

    @staticmethod
    def _extension_matches(filename_lower: str, rule: EntityRule) -> bool:
        raw_ext = (rule.raw_extension or "").strip().lower()
        if not raw_ext or raw_ext == "*":
            return True
        return filename_lower.endswith(raw_ext) or any(
            filename_lower.endswith(ext) for ext in rule.extensions if ext
        )

    def load_rules(
        self,
        mapping_file: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[EntityRule]:
        """
        Loads `EntityRule` definitions from `mapping_file` (caching the full rule set)
        and optionally filters by `source`.
        """
        target_file = mapping_file or self.mapping_file
        if not target_file:
            raise ValueError("mapping_file path is required to load entity mapping rules.")

        abs_file = os.path.abspath(target_file)
        if self._cached_all_rules is None or self._cached_file_path != abs_file:
            all_rules: List[EntityRule] = []
            with open(abs_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    normalized = {k.strip().upper(): v.strip() for k, v in row.items() if k and v}
                    tgt = normalized.get("TARGET_TABLE", "")
                    sig = normalized.get("FILE_SIGNATURE", "")
                    raw_ext = normalized.get("EXTENSION", ".csv").lower()
                    inner_ext = normalized.get("INNER_EXTENSION", "").lower() or ".csv"
                    src = normalized.get("SOURCE", "")

                    if tgt and sig:
                        ext_list = [e.strip().lower() for e in raw_ext.split(",") if e.strip()]
                        delm = normalized.get("DELIMITER", ",") or ","
                        lmode = (normalized.get("LOAD_MODE", "replace") or "replace").lower()
                        if lmode not in ("replace", "append"):
                            lmode = "replace"

                        skip_rows_raw = normalized.get("SKIP_ROWS", "1") or "1"
                        try:
                            skip_rows_val = max(0, int(skip_rows_raw))
                        except ValueError:
                            skip_rows_val = 1

                        hmode = (normalized.get("HEADER_MODE", "") or "").lower()
                        if not hmode:
                            sref = (normalized.get("SKIP_ROWS_EVERY_FILE", "") or "").upper()
                            if sref in ("Y", "YES", "TRUE", "1"):
                                hmode = "every_file"
                            else:
                                hmode = "first_chunk_only"
                        if hmode not in ("first_chunk_only", "every_file", "none"):
                            hmode = "first_chunk_only"

                        all_rules.append(
                            EntityRule(
                                source=src,
                                target_table=tgt,
                                signature=sig.lower(),
                                extensions=ext_list or [".csv"],
                                inner_extension=inner_ext,
                                raw_extension=raw_ext,
                                delimiter=delm,
                                load_mode=lmode,
                                skip_rows=skip_rows_val,
                                header_mode=hmode,
                            )
                        )
            self._cached_all_rules = all_rules
            self._cached_file_path = abs_file

        filter_src = source if source is not None else self.default_source
        if not filter_src:
            return list(self._cached_all_rules)

        return [r for r in self._cached_all_rules if self._source_matches(r.source, filter_src)]

    def match_file(
        self,
        filename: str,
        file_dir: Optional[str] = None,
        source: Optional[str] = None,
        rules: Optional[List[ Any ]] = None,
    ) -> Optional[EntityRule]:
        """
        Executes 2-pass matching for `filename`:
          - Pass 1: Matches source + signature + outer extension + inner_extension (.csv vs .pecsv)
          - Pass 2: Fallback match on source + signature + outer extension (ignoring inner_extension)
        Returns the matched `EntityRule` or `None`.
        """
        fn_lower = filename.lower()
        full_path = os.path.join(file_dir, filename) if file_dir else filename
        actual_inner_ext = inspect_file_inner_extension(full_path)

        filter_src = source if source is not None else self.default_source
        if rules is not None:
            candidate_rules: List[EntityRule] = []
            for r in rules:
                if isinstance(r, EntityRule):
                    candidate_rules.append(r)
                elif isinstance(r, dict):
                    raw_ext = str(r.get("extension", ".csv")).lower()
                    candidate_rules.append(
                        EntityRule(
                            source=str(r.get("source", "")),
                            target_table=str(r["target_table"]),
                            signature=str(r["signature"]).lower(),
                            extensions=[e.strip() for e in raw_ext.split(",") if e.strip()],
                            inner_extension=str(r.get("inner_extension", ".csv")).lower(),
                            raw_extension=raw_ext,
                            delimiter=str(r.get("delimiter", ",")),
                            load_mode=str(r.get("load_mode", "replace")).lower(),
                            skip_rows=int(r.get("skip_rows", 1)),
                            header_mode=str(r.get("header_mode", "first_chunk_only")).lower(),
                        )
                    )
        else:
            candidate_rules = self.load_rules(source=filter_src)

        # Pass 1: Exact match including inner_extension
        for rule in candidate_rules:
            if not self._source_matches(rule.source, filter_src):
                continue
            if rule.signature in fn_lower and self._extension_matches(fn_lower, rule):
                if rule.inner_extension and rule.inner_extension == actual_inner_ext:
                    return rule

        # Pass 2: Fallback match without inner_extension
        for rule in candidate_rules:
            if not self._source_matches(rule.source, filter_src):
                continue
            if rule.signature in fn_lower and self._extension_matches(fn_lower, rule):
                return EntityRule(
                    source=rule.source,
                    target_table=rule.target_table,
                    signature=rule.signature,
                    extensions=list(rule.extensions),
                    inner_extension=actual_inner_ext,
                    raw_extension=rule.raw_extension,
                    delimiter=rule.delimiter,
                    load_mode=rule.load_mode,
                    skip_rows=rule.skip_rows,
                    header_mode=rule.header_mode,
                )

        return None
