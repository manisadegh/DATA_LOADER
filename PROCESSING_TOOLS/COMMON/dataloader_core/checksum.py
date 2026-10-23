"""
dataloader_core/checksum.py - Streaming Cryptographic File Hashing

Provides memory-efficient 64 KB block-streaming MD5 and SHA256 calculation
for multi-gigabyte BICC and enterprise flat-file extracts.
"""

from __future__ import annotations

import hashlib

CHUNK_SIZE_BYTES = 65536


def compute_file_checksum(file_path: str, algorithm: str = "md5") -> str:
    """
    Computes the cryptographic hash (MD5 or SHA256) of `file_path` by reading
    in 64 KB chunks. Returns lowercase hexadecimal digest.
    """
    algo_norm = (algorithm or "md5").strip().lower()
    if algo_norm == "sha256":
        hasher = hashlib.sha256()
    elif algo_norm in ("md5", "auto"):
        hasher = hashlib.md5()
    else:
        raise ValueError(f"Unsupported checksum algorithm '{algorithm}'. Expected 'md5' or 'sha256'.")

    with open(file_path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE_BYTES):
            hasher.update(chunk)

    return hasher.hexdigest().lower()
