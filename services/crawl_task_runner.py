"""In-process execution runner for crawl and async background tasks."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Mapping

from core.db_manager import DatabaseManager
from core.redaction import redact_sensitive_text
from core.runtime_paths import app_root

logger = logging.getLogger("vse_toolbox.crawl_task_runner")

#: 统一工件保留期（天）：超过该期限的下载工件在清理时删除。
ARTIFACT_RETENTION_DAYS = 7

_EXACT_SENSITIVE_KEYS = {
    "password",
    "passwd",
    "domainpassword",
    "secret",
    "token",
    "cookie",
    "cookies",
    "set-cookie",
    "auth_cookie",
    "authcookie",
    "credential",
    "credentials",
    "credential_ref",
    "session",
    "sessionid",
    "sid",
    "jsessionid",
    "bearer",
    "jwt",
    "csrf",
    "csrftoken",
    "arasauth",
    "authorization",
    "key",
    "apikey",
    "api_key",
    "private_key",
    "secret_key",
    "access_key",
    "auth_key",
    "privatekey",
    "secretkey",
    "accesskey",
    "authkey",
}

_SENSITIVE_SUBSTRINGS = (
    "password",
    "passwd",
    "token",
    "secret",
    "cookie",
    "credential",
    "session",
    "bearer",
    "jwt",
    "csrf",
    "arasauth",
)


def _is_sensitive_key(key: str) -> bool:
    k = str(key).lower().replace("-", "_").strip()
    if k in _EXACT_SENSITIVE_KEYS:
        return True
    if any(s in k for s in _SENSITIVE_SUBSTRINGS):
        return True
    if k.endswith(("_key", "key")) and any(
        k.startswith(p) for p in ("api", "secret", "private", "access", "auth", "token", "enc")
    ):
        return True
    if k.startswith("auth_") or k.startswith("auth-") or k == "auth":
        return True
    if k.startswith("authorization"):
        return True
    return False


def sanitize_task_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Sanitize parameters before persisting to crawl_tasks.params_json.

    Ensures NO credentials, passwords, tokens, cookies or sensitive keys are saved,
    while preserving domain business keys like job_key, template_key, keyword, and author.
    """
    if not params or not isinstance(params, Mapping):
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        if _is_sensitive_key(str(key)):
            continue  # Strip completely: zero credential storage!

        if isinstance(value, str):
            sanitized[str(key)] = redact_sensitive_text(value, limit=500)
        elif isinstance(value, Mapping):
            sanitized[str(key)] = sanitize_task_params(value)
        elif isinstance(value, (int, float, bool)) or value is None:
            sanitized[str(key)] = value
        elif isinstance(value, (list, tuple)):
            clean_list = []
            for item in value:
                if isinstance(item, str):
                    clean_list.append(redact_sensitive_text(item, limit=200))
                elif isinstance(item, Mapping):
                    clean_list.append(sanitize_task_params(item))
                elif isinstance(item, (int, float, bool)) or item is None:
                    clean_list.append(item)
            sanitized[str(key)] = clean_list
        else:
            sanitized[str(key)] = redact_sensitive_text(str(value), limit=200)

    return sanitized


def prune_old_artifacts(directory: Path | str, *, max_age_days: int = ARTIFACT_RETENTION_DAYS) -> int:
    """
    Delete artifact files older than max_age_days (mtime-based, 7-day rotation).

    Only plain files directly inside `directory` are considered; subdirectories
    and undeletable entries are skipped silently. Returns the removed count.
    """
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        entries = list(Path(directory).iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed


class CrawlTaskContext:
    """Task context passed to the worker execution function."""

    def __init__(
        self,
        task_id: str,
        task_type: str,
        source: str,
        params: dict[str, Any],
        stop_event: threading.Event,
        db: DatabaseManager,
        downloads_dir: Path,
    ) -> None:
        self.task_id = task_id
        self.task_type = task_type
        self.source = source
        self.params = params
        self.stop_event = stop_event
        self._db = db
        self.downloads_dir = downloads_dir
        self.artifact_path: str | None = None

    @property
    def is_cancelled(self) -> bool:
        """Cooperative cancellation probe."""
        return self.stop_event.is_set()

    def update_progress(
        self,
        progress: Mapping[str, Any] | None = None,
        *,
        current: int | None = None,
        total: int | None = None,
        stage: str | None = None,
        percent: int | None = None,
    ) -> None:
        """Update progress in database if not cancelled."""
        if self.stop_event.is_set():
            return
        payload: dict[str, Any] = dict(progress) if progress else {}
        if current is not None:
            payload["current"] = current
        if total is not None:
            payload["total"] = total
        if stage is not None:
            payload["stage"] = stage
        if percent is not None:
            payload["percent"] = max(0, min(100, percent))
        elif current is not None and total is not None and total > 0:
            payload["percent"] = max(0, min(100, int((current / total) * 100)))

        progress_json = json.dumps(payload, ensure_ascii=False)
        self._db.update_crawl_task_progress(self.task_id, progress_json)

    def set_artifact(self, file_path: str | Path) -> str:
        """Record artifact path relative to downloads_dir."""
        p = Path(file_path)
        if p.is_absolute():
            try:
                rel = p.relative_to(self.downloads_dir)
                self.artifact_path = str(rel).replace("\\", "/")
            except ValueError:
                self.artifact_path = p.name
        else:
            self.artifact_path = str(p).replace("\\", "/")
        return self.artifact_path


class CrawlTaskRunner:
    """
    Lightweight in-process task runner with single concurrency per source
    and cooperative cancellation via threading.Event.
    """

    def __init__(
        self,
        db: DatabaseManager,
        downloads_dir: Path | str | None = None,
        max_workers: int = 2,
    ) -> None:
        self._db = db
        self._downloads_dir = (
            Path(downloads_dir) if downloads_dir else (app_root() / "data" / "downloads")
        )
        self._downloads_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="crawl-task-worker",
        )
        # Per-source mutual exclusion locks: Aras and TDC single concurrency!
        self._source_locks: dict[str, threading.Lock] = {
            "aras": threading.Lock(),
            "tdc": threading.Lock(),
        }
        self._active_sources: set[str] = set()
        self._source_queues: dict[
            str,
            deque[tuple[str, str, Callable[[CrawlTaskContext], Any], threading.Event, CrawlTaskContext]],
        ] = {}
        self._active_tasks: dict[str, tuple[Future[Any] | None, threading.Event, str]] = {}
        self._handlers: dict[str, Callable[[CrawlTaskContext], Any]] = {}
        self._lock = threading.Lock()

    @property
    def downloads_dir(self) -> Path:
        return self._downloads_dir

    def register_handler(
        self,
        task_type: str,
        handler_fn: Callable[[CrawlTaskContext], Any],
    ) -> None:
        """Register a default execution handler for a task type."""
        with self._lock:
            self._handlers[task_type] = handler_fn

    def has_handler(self, task_type: str) -> bool:
        """Whether a default handler is registered (retryable without request context)."""
        with self._lock:
            return task_type in self._handlers

    def startup_sweep(self) -> int:
        """
        Fail-closed startup sweep.

        Flips any orphan 'queued', 'leased', or 'running' tasks from prior process
        runs to 'interrupted'.
        """
        try:
            return self._db.sweep_interrupted_crawl_tasks()
        except Exception as exc:
            logger.critical("Fail-closed startup sweep failed: %s", exc)
            raise

    def _get_source_lock(self, source: str) -> threading.Lock:
        src = (source or "general").lower().strip()
        with self._lock:
            if src not in self._source_locks:
                self._source_locks[src] = threading.Lock()
            return self._source_locks[src]

    def submit_task(
        self,
        task_type: str,
        source: str,
        params: Mapping[str, Any] | None,
        worker_fn: Callable[[CrawlTaskContext], Any] | None = None,
        *,
        task_id: str | None = None,
    ) -> str:
        """
        Submit a new crawl/async task for execution.

        Returns task_id.
        """
        tid = task_id or f"crawl_{uuid.uuid4().hex[:12]}"
        clean_params = sanitize_task_params(params)
        params_json = json.dumps(clean_params, ensure_ascii=False)

        fn = worker_fn or self._handlers.get(task_type)
        if fn is None:
            raise ValueError(
                f"No worker_fn provided and no handler registered for task_type '{task_type}'"
            )

        # 1. Create DB row in queued state
        self._db.create_crawl_task(
            task_id=tid,
            task_type=task_type,
            source=source,
            params_json=params_json,
            progress_json="{}",
        )

        stop_event = threading.Event()
        context = CrawlTaskContext(
            task_id=tid,
            task_type=task_type,
            source=source,
            params=clean_params,
            stop_event=stop_event,
            db=self._db,
            downloads_dir=self._downloads_dir,
        )

        src = (source or "general").lower().strip()
        with self._lock:
            if src in self._active_sources:
                # Source is currently busy with another task.
                # Enqueue in source queue without occupying a thread pool worker!
                if src not in self._source_queues:
                    self._source_queues[src] = deque()
                self._source_queues[src].append((tid, src, fn, stop_event, context))
                self._active_tasks[tid] = (None, stop_event, src)
            else:
                self._active_sources.add(src)
                future = self._executor.submit(
                    self._run_task_wrapper,
                    tid,
                    src,
                    fn,
                    stop_event,
                    context,
                )
                self._active_tasks[tid] = (future, stop_event, src)

        return tid

    def _run_task_wrapper(
        self,
        task_id: str,
        source: str,
        worker_fn: Callable[[CrawlTaskContext], Any],
        stop_event: threading.Event,
        context: CrawlTaskContext,
    ) -> None:
        source_lock = self._get_source_lock(source)

        try:
            # Check early cancellation before acquiring lock
            if stop_event.is_set():
                self._db.update_crawl_task_status(
                    task_id, "cancelled", error_message="Cancelled before start"
                )
                return

            with source_lock:
                # Check cancellation after acquiring lock
                if stop_event.is_set():
                    self._db.update_crawl_task_status(
                        task_id, "cancelled", error_message="Cancelled by user"
                    )
                    return

                self._db.update_crawl_task_status(task_id, "running")

                try:
                    worker_fn(context)
                    if stop_event.is_set():
                        self._db.update_crawl_task_status(
                            task_id, "cancelled", error_message="Cancelled by user"
                        )
                    else:
                        self._db.update_crawl_task_status(
                            task_id,
                            "succeeded",
                            artifact_path=context.artifact_path,
                        )
                except Exception as exc:
                    if stop_event.is_set():
                        self._db.update_crawl_task_status(
                            task_id, "cancelled", error_message="Cancelled by user"
                        )
                    else:
                        logger.exception("Task %s failed: %s", task_id, exc)
                        safe_msg = redact_sensitive_text(str(exc), limit=1000)
                        self._db.update_crawl_task_status(
                            task_id, "failed", error_message=safe_msg
                        )
                if not stop_event.is_set():
                    # 统一工件 7 天轮换清理：任务完成后淘汰过期下载工件。
                    try:
                        removed = prune_old_artifacts(self._downloads_dir)
                        if removed:
                            logger.info("Pruned %d expired download artifacts", removed)
                    except Exception:
                        logger.exception("Artifact pruning failed after task %s", task_id)
        finally:
            with self._lock:
                self._active_tasks.pop(task_id, None)
                self._dispatch_next_for_source(source)

    def _dispatch_next_for_source(self, source: str) -> None:
        """Schedule the next waiting task for this source (must hold self._lock)."""
        q = self._source_queues.get(source)
        while q:
            next_tid, next_src, next_fn, next_stop_event, next_ctx = q.popleft()
            if next_stop_event.is_set():
                self._db.update_crawl_task_status(
                    next_tid, "cancelled", error_message="Cancelled by user"
                )
                self._active_tasks.pop(next_tid, None)
                continue
            future = self._executor.submit(
                self._run_task_wrapper,
                next_tid,
                next_src,
                next_fn,
                next_stop_event,
                next_ctx,
            )
            self._active_tasks[next_tid] = (future, next_stop_event, next_src)
            return

        # No further waiting tasks for this source
        self._active_sources.discard(source)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running or queued task."""
        clean_id = task_id
        with self._lock:
            # 1. If queued in a source waiting queue, cancel immediately
            for src, q in self._source_queues.items():
                for item in list(q):
                    if item[0] == clean_id:
                        q.remove(item)
                        item[3].set()  # set stop_event
                        self._active_tasks.pop(clean_id, None)
                        return self._db.cancel_crawl_task(clean_id)

            # 2. If active or running in executor
            active_info = self._active_tasks.get(clean_id)
            if active_info is not None:
                future, stop_event, src = active_info
                stop_event.set()
                if future is not None and future.cancel():
                    # The future was still pending in the executor and will
                    # never run, so _run_task_wrapper's finally block will not
                    # fire. Dispatch the next task for this source here, or the
                    # source would stay marked active forever.
                    self._active_tasks.pop(clean_id, None)
                    self._dispatch_next_for_source(src)

        # Update status in DB
        return self._db.cancel_crawl_task(clean_id)

    def retry_task(self, task_id: str) -> str:
        """Retry a failed or cancelled task by resubmitting with same parameters."""
        task = self._db.get_crawl_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")
        if task["status"] not in ("failed", "cancelled", "interrupted"):
            raise ValueError(f"Task '{task_id}' is not in a retriable state ({task['status']})")

        task_type = task["task_type"]
        handler = self._handlers.get(task_type)
        if not handler:
            raise RuntimeError(f"No execution handler registered for task type '{task_type}'")

        params = {}
        if task.get("params_json"):
            try:
                params = json.loads(task["params_json"])
            except Exception:
                pass

        return self.submit_task(
            task_type=task_type,
            source=task["source"],
            params=params,
            worker_fn=handler,
        )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._db.get_crawl_task(task_id)

    def list_tasks(
        self,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._db.list_crawl_tasks(status=status, source=source, limit=limit)

    def shutdown(self, wait: bool = False) -> None:
        """Signal all active tasks and shut down thread pool."""
        with self._lock:
            for q in self._source_queues.values():
                for item in q:
                    item[3].set()
                q.clear()
            self._active_sources.clear()
            for _, stop_event, _src in self._active_tasks.values():
                stop_event.set()
            self._active_tasks.clear()
        self._executor.shutdown(wait=wait, cancel_futures=True)
