"""
dataloader_core/config.py - Configuration Loading, Environment Variable Expansion & Path Resolution

Centralizes recursive environment variable interpolation (${VAR} and $VAR),
JSON configuration loading, and source-partitioned zone path resolution.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

from .exceptions import ConfigurationError

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env_vars(data: Any, env: Optional[Dict[str, str]] = None) -> Any:
    """
    Recursively expands ${VAR} or $VAR environment variables in configuration strings,
    dictionaries, and lists. If custom `env` dict is provided, expands against `env`
    (with fallback to `os.environ` only if `env` is None).
    """
    if isinstance(data, str):
        if env is None:
            return os.path.expandvars(data)

        def _replacer(match: re.Match) -> str:
            var_name = match.group(1) or match.group(2)
            if var_name in env:
                return str(env[var_name])
            return match.group(0)

        return _ENV_VAR_PATTERN.sub(_replacer, data)
    if isinstance(data, dict):
        return {k: expand_env_vars(v, env=env) for k, v in data.items()}
    if isinstance(data, list):
        return [expand_env_vars(v, env=env) for v in data]
    return data


def resolve_zone_path(
    base_dir: str,
    configured_path: str,
    source: Optional[str] = None,
    ensure_exists: bool = True,
) -> str:
    """
    Resolves a configured path (relative to `base_dir` or absolute) and optionally
    partitions it by `source` if the terminal path segment (`os.path.basename`)
    does not already match `source` (case-insensitive).
    """
    if not configured_path:
        raise ConfigurationError("Cannot resolve an empty configured_path.")

    if os.path.isabs(configured_path):
        resolved = os.path.normpath(configured_path)
    else:
        resolved = os.path.normpath(os.path.join(base_dir, configured_path))

    if source and str(source).strip():
        clean_src = str(source).strip()
        if os.path.basename(resolved).lower() != clean_src.lower():
            resolved = os.path.join(resolved, clean_src)

    if ensure_exists:
        os.makedirs(resolved, exist_ok=True)

    return resolved


def load_json_config(config_path: str, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Validates configuration file existence, parses JSON content, and recursively
    expands environment variables.
    """
    if not config_path or not os.path.exists(config_path):
        raise ConfigurationError(f"Configuration file not found: {config_path}")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except Exception as exc:
        raise ConfigurationError(f"Failed to parse configuration file '{config_path}': {exc}") from exc

    return expand_env_vars(raw_data, env=env)


class ConfigLoader:
    """Facade class for configuration loading, env expansion, and path resolution."""

    load_json_config = staticmethod(load_json_config)
    expand_env_vars = staticmethod(expand_env_vars)
    resolve_path = staticmethod(resolve_zone_path)
    resolve_zone_path = staticmethod(resolve_zone_path)
