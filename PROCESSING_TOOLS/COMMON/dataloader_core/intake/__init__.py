"""
dataloader_core.intake - Pluggable Multi-Source Intake Framework

Provides generic, reusable flat-file intake mechanics decoupled from source-specific
extract patterns, supporting BICC, Standard Manifests, and Manifestless Drops.
"""

from .base_controller import BaseIntakeController
from .plugin import (
    BICCIntakePlugin,
    ManifestlessDropIntakePlugin,
    PluginRegistry,
    RawBatchCandidate,
    SourceIntakePlugin,
    StandardManifestIntakePlugin,
)

__all__ = [
    "BaseIntakeController",
    "BICCIntakePlugin",
    "ManifestlessDropIntakePlugin",
    "PluginRegistry",
    "RawBatchCandidate",
    "SourceIntakePlugin",
    "StandardManifestIntakePlugin",
]
