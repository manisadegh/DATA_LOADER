"""
dataloader_core/db.py - Teradata Credential Resolution, SQL Validation & Connection Pooling

Consolidates all 4 copies of Teradata authentication resolution into a single
module and provides a thread-safe connection pool (`TeradataConnectionManager`)
to eliminate per-query TCP logon/logoff churn in multi-entity batch runs.
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import re
import threading
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger("dataloader_core.db")

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")


def validate_sql_identifier(identifier: str) -> str:
    """
    Validates that a SQL identifier (database, table, column, or character set)
    contains only safe alphanumeric and underscore characters (SEC-01).
    """
    cleaned = str(identifier).strip() if identifier is not None else ""
    if not cleaned or not _SQL_IDENTIFIER_RE.match(cleaned):
        raise ValueError(f"Invalid SQL identifier: '{identifier}'")
    return cleaned


def resolve_teradata_credentials(td_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Resolves Teradata Vantage connection parameters (`host`, `user`, `logmech`, `password`)
    following strict precedence:
      1. Explicit `key_file` and `pass_file` in `td_cfg` -> ENCRYPTED_PASSWORD(file:...,file:...)
      2. Explicit `password` in `td_cfg`
      3. Auto-discovered `~/.dbt/{user}_Key.properties` & `{user}_Pass.properties` (or `$DBT_PROFILE_DIR`)
      4. `TD_PASSWORD` environment variable
    """
    if td_cfg is None:
        td_cfg = {}

    host = (
        td_cfg.get("host")
        or td_cfg.get("server")
        or td_cfg.get("tdpid")
        or os.environ.get("TDPID")
    )
    if not host:
        raise ValueError(
            "Teradata host/server not configured. Provide 'host' in config.json or export TDPID."
        )

    env_user = (
        f"{os.environ.get('TDENV', '')}{os.environ.get('SID_ADM_USER', '')}"
        if os.environ.get("SID_ADM_USER")
        else os.environ.get("USER")
    )
    user = td_cfg.get("user") or td_cfg.get("username") or env_user
    if not user:
        raise ValueError(
            "Teradata user not configured. Provide 'user' in config.json or export TDENV and SID_ADM_USER."
        )

    kwargs: Dict[str, Any] = {
        "host": host,
        "user": user,
        "logmech": td_cfg.get("logmech", "TD2"),
    }

    if td_cfg.get("key_file") and td_cfg.get("pass_file"):
        kwargs["password"] = f"ENCRYPTED_PASSWORD(file:{td_cfg['key_file']},file:{td_cfg['pass_file']})"
    elif td_cfg.get("password"):
        kwargs["password"] = td_cfg["password"]
    else:
        dbt_dir = os.environ.get("DBT_PROFILE_DIR") or os.path.expanduser("~/.dbt")
        auto_key = os.path.join(dbt_dir, f"{user}_Key.properties")
        auto_pass = os.path.join(dbt_dir, f"{user}_Pass.properties")
        if os.path.exists(auto_key) and os.path.exists(auto_pass):
            kwargs["password"] = f"ENCRYPTED_PASSWORD(file:{auto_key},file:{auto_pass})"
        elif os.environ.get("TD_PASSWORD"):
            kwargs["password"] = os.environ.get("TD_PASSWORD")

    return kwargs


def build_tpt_environment(
    td_cfg: Optional[Dict[str, Any]] = None,
    base_env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Constructs the environment variable dictionary (`TDPID`, `TD_PASSWORD`, `SID_ADM_USER`, `USER`)
    for TPT_LOADER subprocess execution without mutating global `os.environ`.
    """
    if td_cfg is None:
        td_cfg = {}

    tpt_env = dict(base_env) if base_env is not None else os.environ.copy()

    host = (
        td_cfg.get("host")
        or td_cfg.get("server")
        or td_cfg.get("tdpid")
        or tpt_env.get("TDPID")
    )
    if host:
        tpt_env["TDPID"] = str(host)

    pwd = td_cfg.get("password", "")
    if pwd and not str(pwd).startswith("ENCRYPTED_PASSWORD"):
        tpt_env["TD_PASSWORD"] = str(pwd)
    elif "TD_PASSWORD" in tpt_env and str(pwd).startswith("ENCRYPTED_PASSWORD"):
        del tpt_env["TD_PASSWORD"]

    env_user = (
        f"{tpt_env.get('TDENV', '')}{tpt_env.get('SID_ADM_USER', '')}"
        if tpt_env.get("SID_ADM_USER")
        else tpt_env.get("USER")
    )
    user = td_cfg.get("user") or td_cfg.get("username") or env_user
    if user:
        tpt_env["TD_LOGON_USER"] = str(user)

    return tpt_env


def get_teradata_connection(td_cfg: Optional[Dict[str, Any]] = None):
    """Creates a direct Teradata connection using resolved credentials."""
    import teradatasql

    connect_kwargs = resolve_teradata_credentials(td_cfg)
    return teradatasql.connect(**connect_kwargs)


class TeradataConnectionManager:
    """
    Thread-safe Teradata connection pool manager.
    Maintains up to `max_connections` persistent connections in a queue so
    concurrent worker threads in `ThreadPoolExecutor` reuse live sessions
    instead of opening a new TCP connection on every state query.
    """

    resolve_credentials = staticmethod(resolve_teradata_credentials)
    build_tpt_env = staticmethod(build_tpt_environment)
    validate_identifier = staticmethod(validate_sql_identifier)

    def __init__(
        self,
        td_cfg: Optional[Dict[str, Any]] = None,
        max_connections: Optional[int] = None,
    ) -> None:
        self.td_cfg = dict(td_cfg) if td_cfg else {}
        self.connect_kwargs = resolve_teradata_credentials(self.td_cfg)
        pool_size = (
            max_connections
            if max_connections is not None
            else self.td_cfg.get("connection_pool_size", 6)
        )
        self.max_connections = max(1, int(pool_size))
        self._idle_pool: "queue.Queue[Any]" = queue.Queue(maxsize=self.max_connections)
        self._lock = threading.Lock()
        self._all_connections: List[Any] = []
        self._in_use_count = 0
        self._total_created = 0
        self._closed = False

    @property
    def total_connections_created(self) -> int:
        """Returns the total number of physical connections created by this pool."""
        return self._total_created

    def _create_new_connection(self) -> Any:
        import teradatasql

        conn = teradatasql.connect(**self.connect_kwargs)
        self._total_created += 1
        self._all_connections.append(conn)
        return conn

    def _is_healthy(self, conn: Any) -> bool:
        """Validates a borrowed connection with SELECT 1 before lending (F2.12)."""
        if conn is None:
            return False
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            _ = cur.fetchone()
            if hasattr(cur, "close"):
                cur.close()
            return True
        except Exception:
            return False

    def _discard(self, conn: Any) -> None:
        """Closes and unregisters a failing or discarded connection from the pool (F2.12)."""
        if conn is None:
            return
        with self._lock:
            if conn in self._all_connections:
                self._all_connections.remove(conn)
        try:
            conn.close()
        except Exception:
            pass

    @contextlib.contextmanager
    def acquire_connection(self) -> Generator[Any, None, None]:
        """
        Borrows a live TeradataConnection from the pool (creating one if under capacity)
        and returns it to the pool upon context exit without closing the session.
        Enforces health check on borrow and discards on borrower error (F2.12).
        """
        if self._closed:
            raise RuntimeError("TeradataConnectionManager has already been closed.")

        conn = None
        while conn is None:
            try:
                candidate = self._idle_pool.get_nowait()
                if not self._is_healthy(candidate):
                    self._discard(candidate)
                    continue
                conn = candidate
            except queue.Empty:
                with self._lock:
                    if len(self._all_connections) < self.max_connections:
                        conn = self._create_new_connection()
                        self._in_use_count += 1
                if conn is None:
                    candidate = self._idle_pool.get(timeout=300)
                    if not self._is_healthy(candidate):
                        self._discard(candidate)
                        continue
                    conn = candidate
                    with self._lock:
                        self._in_use_count += 1
            else:
                with self._lock:
                    self._in_use_count += 1

        discarded = False
        try:
            try:
                yield conn
            except BaseException:
                discarded = True
                self._discard(conn)
                raise
        finally:
            with self._lock:
                self._in_use_count = max(0, self._in_use_count - 1)
                is_closed = self._closed
            if not is_closed and not discarded and conn is not None:
                try:
                    self._idle_pool.put_nowait(conn)
                except queue.Full:
                    self._discard(conn)
            elif not discarded and conn is not None:
                self._discard(conn)

    @contextlib.contextmanager
    def cursor(self) -> Generator[Any, None, None]:
        """
        Borrows a pooled connection and yields a database cursor, closing the cursor
        on exit while returning the underlying connection to the pool.
        """
        with self.acquire_connection() as conn:
            cur_obj = conn.cursor()
            if hasattr(cur_obj, "__enter__"):
                with cur_obj as cur:
                    yield cur
            else:
                try:
                    yield cur_obj
                finally:
                    if hasattr(cur_obj, "close"):
                        cur_obj.close()

    def close_all(self) -> None:
        """Closes all pooled Teradata connections cleanly."""
        with self._lock:
            self._closed = True
            while not self._idle_pool.empty():
                try:
                    self._idle_pool.get_nowait()
                except queue.Empty:
                    break
            conns = list(self._all_connections)
            self._all_connections.clear()

        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        """Alias for close_all()."""
        self.close_all()
