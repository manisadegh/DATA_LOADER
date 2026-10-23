"""
dataloader_core/locking.py - Atomic POSIX Advisory File Locking & PID Liveness Polling

Eliminates duplicated PID polling loops across BICC_INTAKE_CONTROLLER and
DATA_INGESTION_ORCHESTRATOR, and prevents TOCTOU race conditions via POSIX
advisory file locks (fcntl.flock) combined with PID metadata files.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import Generator, Optional, Set, Tuple

from .exceptions import LockTimeoutError

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows local import fallback
    fcntl = None  # type: ignore[assignment]


def is_pid_alive(pid: int) -> bool:
    """Checks if a given process ID is actively running (POSIX os.kill(pid, 0), excluding defunct zombies)."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, ProcessLookupError):
        return False

    # On Linux, an unreaped child process in zombie ('Z') state still responds to kill(pid, 0)
    proc_stat = f"/proc/{pid}/stat"
    if os.path.exists(proc_stat):
        try:
            with open(proc_stat, "r", encoding="utf-8", errors="replace") as sf:
                stat_content = sf.read()
            after_comm = stat_content.rsplit(")", 1)
            if len(after_comm) == 2:
                fields = after_comm[1].split()
                if fields and fields[0] == "Z":
                    return False
        except Exception:
            pass
    return True


def read_pid_file(lock_file_path: str) -> Tuple[Optional[str], int]:
    """
    Reads (host, pid) from `lock_file_path`.
    Supports new format '<hostname>:<pid>' and legacy format '<pid>'.
    Returns (None, -1) if missing or unparseable.
    """
    if not lock_file_path or not os.path.exists(lock_file_path):
        return (None, -1)
    try:
        with open(lock_file_path, "r", encoding="utf-8") as pf:
            content = pf.read().strip()
            if not content:
                return (None, -1)
            if ":" in content:
                parts = content.split(":", 1)
                return (parts[0].strip(), int(parts[1].strip()))
            else:
                return (None, int(content))
    except Exception:
        return (None, -1)


def wait_for_pid_completion(
    pid: int,
    poll_interval_sec: float = 5,
    timeout_sec: float = 7200,
    logger: Optional[logging.Logger] = None,
    context_label: str = "Process",
    initial_message: Optional[str] = None,
    poll_message: Optional[str] = None,
    completion_message: Optional[str] = None,
    lock_file_path: Optional[str] = None,
    host: Optional[str] = None,
) -> None:
    """
    Polls until the process on host terminates (or releases `lock_file_path`) or `timeout_sec` expires.
    If host is foreign, liveness cannot be verified locally, so lock is considered held until released or timeout.
    """
    current_host = socket.gethostname()
    is_same_host = host is None or host == current_host

    if is_same_host and (not is_pid_alive(pid) or pid == os.getpid()):
        return

    host_info = f" on host {host}" if host and not is_same_host else ""
    init_msg = initial_message or (
        f"Another {context_label} is currently active (PID {pid}{host_info}). "
        f"Entering active waiting loop (polling every {poll_interval_sec}s, timeout: {timeout_sec}s)..."
    )
    if logger:
        logger.info(init_msg)

    start_time = time.time()

    def still_held() -> bool:
        if not lock_file_path:
            return is_pid_alive(pid) if is_same_host else True
        h, p = read_pid_file(lock_file_path)
        if p != pid or (h is not None and host is not None and h != host):
            return False
        return is_pid_alive(pid) if is_same_host else True

    while still_held():
        if time.time() - start_time > timeout_sec:
            timeout_msg = f"FATAL: Timeout ({timeout_sec}s) exceeded waiting for active {context_label} (PID {pid}{host_info})."
            if logger:
                logger.critical(timeout_msg)
            raise LockTimeoutError(timeout_msg)
        time.sleep(poll_interval_sec)
        if still_held() and logger:
            p_msg = poll_message or f"{context_label} PID {pid}{host_info} still running. Waiting {poll_interval_sec}s..."
            logger.info(p_msg)

    done_msg = completion_message or f"Active {context_label} (PID {pid}{host_info}) has completed. Resuming execution."
    if logger:
        logger.info(done_msg)


class ProcessLock:
    """
    Context manager providing mutual exclusion via POSIX `fcntl.flock` + PID file tracking.
    Supports active polling wait loops when another instance is alive, and automatic
    cleanup of stale locks left by crashed processes (dead PIDs).
    """

    is_pid_alive = staticmethod(is_pid_alive)
    wait_for_pid = staticmethod(wait_for_pid_completion)

    def __init__(
        self,
        lock_file: str,
        poll_interval_sec: float = 5,
        timeout_sec: float = 7200,
        logger: Optional[logging.Logger] = None,
        label: str = "Process",
        initial_wait_message: Optional[str] = None,
        poll_wait_message: Optional[str] = None,
        completion_wait_message: Optional[str] = None,
    ) -> None:
        self.lock_file = os.path.abspath(lock_file)
        self.poll_interval_sec = poll_interval_sec
        self.timeout_sec = timeout_sec
        self.logger = logger
        self.label = label
        self.initial_wait_message = initial_wait_message
        self.poll_wait_message = poll_wait_message
        self.completion_wait_message = completion_wait_message
        self._fd: Optional[int] = None
        self._acquired: bool = False

    def acquire(self) -> "ProcessLock":
        parent_dir = os.path.dirname(self.lock_file)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        start_wait = time.time()
        logged_wait = False

        # 1. Check existing PID file for an active or stale PID
        existing_host, existing_pid = read_pid_file(self.lock_file)
        current_host = socket.gethostname()
        is_same_host = existing_host is None or existing_host == current_host

        if existing_pid > 0 and (not is_same_host or existing_pid != os.getpid()):
            if not is_same_host or is_pid_alive(existing_pid):
                host_info = f" on host {existing_host}" if existing_host and not is_same_host else ""
                init_msg = self.initial_wait_message or (
                    f"Another {self.label} is currently active (PID {existing_pid}{host_info}). "
                    f"Entering active waiting loop (polling every {self.poll_interval_sec}s, timeout: {self.timeout_sec}s)..."
                )
                poll_msg = self.poll_wait_message or (
                    f"{self.label} PID {existing_pid}{host_info} still running. Waiting {self.poll_interval_sec}s..."
                )
                done_msg = self.completion_wait_message or (
                    f"Active {self.label} PID {existing_pid}{host_info} has completed. Resuming execution."
                )
                wait_for_pid_completion(
                    pid=existing_pid,
                    poll_interval_sec=self.poll_interval_sec,
                    timeout_sec=self.timeout_sec,
                    logger=self.logger,
                    context_label=self.label,
                    initial_message=init_msg,
                    poll_message=poll_msg,
                    completion_message=done_msg,
                    lock_file_path=self.lock_file,
                    host=existing_host,
                )
                logged_wait = True

        # 2. Acquire OS-level exclusive flock + verify inode stability
        while True:
            fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
            try:
                if fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

                # Verify the locked fd still matches the path on disk (not unlinked by previous owner)
                try:
                    st_fd = os.fstat(fd)
                    st_path = os.stat(self.lock_file)
                    if st_fd.st_ino != st_path.st_ino:
                        if fcntl is not None:
                            try:
                                fcntl.flock(fd, fcntl.LOCK_UN)
                            except OSError:
                                pass
                        os.close(fd)
                        continue
                except FileNotFoundError:
                    if fcntl is not None:
                        try:
                            fcntl.flock(fd, fcntl.LOCK_UN)
                        except OSError:
                            pass
                    os.close(fd)
                    continue

                # Write current host:PID atomically into the locked descriptor (F2.8)
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, f"{socket.gethostname()}:{os.getpid()}\n".encode("utf-8"))
                try:
                    os.fsync(fd)
                except OSError:
                    pass

                self._fd = fd
                self._acquired = True
                atexit.register(self.release)
                return self

            except (BlockingIOError, IOError, OSError):
                os.close(fd)
                holder_host, holder_pid = read_pid_file(self.lock_file)
                host_info = f" on host {holder_host}" if holder_host and holder_host != current_host else ""
                if not logged_wait and self.logger:
                    init_msg = self.initial_wait_message or (
                        f"Another {self.label} is currently active (PID {holder_pid}{host_info}). "
                        f"Entering active waiting loop (polling every {self.poll_interval_sec}s, timeout: {self.timeout_sec}s)..."
                    )
                    self.logger.info(init_msg)
                    logged_wait = True

                if time.time() - start_wait > self.timeout_sec:
                    timeout_msg = (
                        f"FATAL: Timeout ({self.timeout_sec}s) exceeded waiting for active "
                        f"{self.label} (PID {holder_pid}{host_info})."
                    )
                    if self.logger:
                        self.logger.critical(timeout_msg)
                    raise LockTimeoutError(timeout_msg)

                time.sleep(self.poll_interval_sec)
                if self.logger:
                    p_msg = self.poll_wait_message or (
                        f"{self.label} PID {holder_pid}{host_info} still running. Waiting {self.poll_interval_sec}s..."
                    )
                    self.logger.info(p_msg)

    def release(self) -> None:
        if not self._acquired:
            return
        self._acquired = False
        try:
            if os.path.exists(self.lock_file):
                stored_host, stored_pid = read_pid_file(self.lock_file)
                if stored_pid in (os.getpid(), -1) and stored_host in (socket.gethostname(), None):
                    try:
                        os.remove(self.lock_file)
                    except OSError:
                        pass
        finally:
            if self._fd is not None:
                if fcntl is not None:
                    try:
                        fcntl.flock(self._fd, fcntl.LOCK_UN)
                    except OSError:
                        pass
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None

    def __enter__(self) -> "ProcessLock":
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()


class UtilitySlotGovernor:
    """
    Cross-process & cross-thread Teradata utility slot governor.
    Uses non-blocking POSIX `fcntl.flock` on bounded slot lock files:
    `slot_01.lock` .. `slot_<max_slots>.lock` inside `slot_dir`.
    Caps total concurrent `tbuild` FastLoad / MultiLoad executions
    across all sources and processes to `max_slots` (default 8),
    preventing Teradata Error 2633 (Too many load/unload tasks running).
    """

    def __init__(
        self,
        slot_dir: str,
        max_slots: int = 8,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.slot_dir = os.path.abspath(slot_dir)
        self.max_slots = max(1, int(max_slots))
        self.logger = logger or logging.getLogger("dataloader_core.locking.slot_governor")
        os.makedirs(self.slot_dir, exist_ok=True)
        self._thread_lock = threading.Lock()
        self._mock_locked_slots: Set[int] = set()

    @contextmanager
    def acquire_slot(
        self,
        entity: str,
        source: str = "UNKNOWN",
        poll_interval_sec: float = 2.0,
        timeout_sec: float = 3600.0,
    ) -> Generator[int, None, None]:
        start_time = time.time()
        acquired_slot: Optional[int] = None
        acquired_fd: Optional[int] = None
        logged_wait = False

        while acquired_slot is None:
            for slot_idx in range(1, self.max_slots + 1):
                slot_file = os.path.join(self.slot_dir, f"slot_{slot_idx:02d}.lock")
                if fcntl is not None:
                    fd = os.open(slot_file, os.O_CREAT | os.O_RDWR, 0o644)
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        try:
                            st_fd = os.fstat(fd)
                            st_path = os.stat(slot_file)
                            if st_fd.st_ino != st_path.st_ino:
                                try:
                                    fcntl.flock(fd, fcntl.LOCK_UN)
                                except OSError:
                                    pass
                                os.close(fd)
                                continue
                        except FileNotFoundError:
                            try:
                                fcntl.flock(fd, fcntl.LOCK_UN)
                            except OSError:
                                pass
                            os.close(fd)
                            continue

                        os.ftruncate(fd, 0)
                        os.lseek(fd, 0, os.SEEK_SET)
                        meta = json.dumps({
                            "pid": os.getpid(),
                            "source": source,
                            "entity": entity,
                            "slot": slot_idx,
                            "acquired_at": time.time(),
                        })
                        os.write(fd, f"{meta}\n".encode("utf-8"))
                        try:
                            os.fsync(fd)
                        except OSError:
                            pass

                        acquired_slot = slot_idx
                        acquired_fd = fd
                        break
                    except (BlockingIOError, IOError, OSError):
                        os.close(fd)
                        continue
                else:
                    # Windows / non-POSIX fallback using thread-lock
                    with self._thread_lock:
                        if slot_idx not in self._mock_locked_slots:
                            self._mock_locked_slots.add(slot_idx)
                            acquired_slot = slot_idx
                            acquired_fd = None
                            break

            if acquired_slot is not None:
                break

            if time.time() - start_time > timeout_sec:
                timeout_msg = (
                    f"FATAL: Timeout ({timeout_sec}s) exceeded waiting for Teradata utility slot "
                    f"for [{source}] {entity} (all {self.max_slots} slots busy)."
                )
                self.logger.critical(timeout_msg)
                raise LockTimeoutError(timeout_msg)

            if not logged_wait:
                self.logger.info(
                    f"All {self.max_slots} Teradata utility slots are busy. "
                    f"Waiting {poll_interval_sec}s for [{source}] {entity}..."
                )
                logged_wait = True

            time.sleep(poll_interval_sec)

        self.logger.info(f"Granted Teradata Utility Slot #{acquired_slot:02d}/{self.max_slots:02d} for [{source}] {entity}.")
        try:
            yield acquired_slot
        finally:
            if fcntl is not None and acquired_fd is not None:
                try:
                    os.ftruncate(acquired_fd, 0)
                    fcntl.flock(acquired_fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                try:
                    os.close(acquired_fd)
                except OSError:
                    pass
            else:
                with self._thread_lock:
                    self._mock_locked_slots.discard(acquired_slot)

            self.logger.info(f"Released Teradata Utility Slot #{acquired_slot:02d}/{self.max_slots:02d} for [{source}] {entity}.")
