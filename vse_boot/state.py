# -*- coding: utf-8 -*-
"""Boot state: which app version is current, previous, or on trial.

Life cycle of an update::

    stage (verified package in state/staging/)
      → install_staged()   files move to app/<v>/, v becomes the trial
      → select_for_boot()  the trial gets one boot attempt (crash-safe counter)
      → commit()           healthy: trial becomes current, old current becomes previous
      → abandon(reason)    unhealthy or crashed: trial is dropped, current stays

A trial that is still marked as booting at the next start crashed the whole
process last time, so ``select_for_boot`` abandons it before trying again.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from vse_boot import dbsnap
from vse_boot.layout import InstallLayout, version_tuple

STATE_FORMAT = 2
MAX_TRIAL_BOOTS = 1
_MAX_EVENTS = 50


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BootStateError(RuntimeError):
    """The install has no runnable app version; the message is safe to show."""


class BootState:
    def __init__(self, layout: InstallLayout) -> None:
        self.layout = layout
        self.data: dict[str, Any] = self._read()

    # ── persistence ──────────────────────────────────────────────────

    def _read(self) -> dict[str, Any]:
        recovered = False
        try:
            raw = json.loads(self.layout.state_file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("boot.json is not an object")
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError):
            # 状态文件损坏（磁盘写满、被杀软隔离…）：留档后按已安装的目录重建，不能让程序再也打不开。
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            try:
                os.replace(self.layout.state_file, self.layout.state_file.with_name(f"boot.corrupt-{stamp}.json"))
            except OSError:
                pass
            installed = self.layout.installed_app_versions()
            raw = {"app": {"current": installed[-1] if installed else None, "previous": installed[-2] if len(installed) > 1 else None}}
            recovered = True
        raw.setdefault("format", STATE_FORMAT)
        app = raw.setdefault("app", {})
        for key in ("current", "previous", "trial", "trialSnapshot"):
            app.setdefault(key, None)
        app.setdefault("trialBoots", 0)
        raw.setdefault("events", [])
        if recovered:
            raw["events"].insert(0, {"at": _now(), "kind": "stateRecovered", "version": raw["app"]["current"]})
        return raw

    def save(self) -> None:
        self.layout.state_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.layout.state_dir, prefix=".boot-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp, self.layout.state_file)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @property
    def app(self) -> dict[str, Any]:
        return self.data["app"]

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.data["events"]

    def _event(self, kind: str, version: str | None, **extra: Any) -> None:
        self.events.insert(0, {"at": _now(), "kind": kind, "version": version, **extra})
        del self.events[_MAX_EVENTS:]

    def record(self, kind: str, version: str | None, **extra: Any) -> None:
        self._event(kind, version, **extra)
        self.save()

    # ── install ──────────────────────────────────────────────────────

    def install_staged(self) -> list[str]:
        """Move verified staged app versions into ``app/<v>/``; the newest becomes the trial."""
        staging = self.layout.staging_dir
        if not staging.is_dir():
            return []
        installed: list[str] = []
        for entry in sorted(staging.iterdir()):
            meta_file = entry / "staged.json"
            # ".tmp-" 开头的是写到一半的暂存目录（stage_app 写完才改名），不能安装。
            if entry.name.startswith(".") or not entry.is_dir() or not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                version = str(meta["version"])
                target = self.layout.app_dir(version)
                if not (entry / "files").is_dir():
                    raise ValueError("暂存目录缺少文件")
                if version in (self.app["current"], self.app["previous"]):
                    # 不覆盖正在使用或可回滚的版本目录。
                    raise ValueError("该版本已安装")
                if target.exists():
                    shutil.rmtree(target)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry / "files"), str(target))
                (target / "app.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except (OSError, ValueError, KeyError) as exc:
                # 一个坏的暂存包不能挡住当前版本启动：记录、丢弃，继续。
                self._event("installFailed", entry.name, reason=str(exc)[:200])
                shutil.rmtree(entry, ignore_errors=True)
                self.save()
                continue
            shutil.rmtree(entry, ignore_errors=True)
            installed.append(version)
            self._event("installed", version, notes=meta.get("notes", ""))
        if installed:
            newest = max(installed, key=version_tuple)
            current = self.app["current"]
            if current is None:
                # 首次安装没有可回退的版本，直接生效，不走试用。
                self.app["current"] = newest
                self._event("activated", newest)
            elif version_tuple(newest) != version_tuple(current):
                self.app["trial"] = newest
                self.app["trialBoots"] = 0
                self.app["trialSnapshot"] = None
            self.save()
        return installed

    # ── boot ─────────────────────────────────────────────────────────

    def select_for_boot(self) -> tuple[str, bool]:
        """Return ``(version, is_trial)`` for the next start and record the attempt."""
        trial = self.app["trial"]
        if trial is not None and self.app["trialBoots"] >= MAX_TRIAL_BOOTS:
            self.abandon(trial, reason="上次试用启动时程序意外退出")
            trial = None
        if trial is not None:
            if not self.layout.app_dir(trial).is_dir():
                self.abandon(trial, reason="试用版本的文件不存在")
            else:
                self.app["trialBoots"] += 1
                self.save()
                return trial, True
        current = self.app["current"]
        if current is None or not self.layout.app_dir(current).is_dir():
            raise BootStateError("没有可以运行的程序版本，请重新安装 VSE Toolbox")
        return current, False

    def set_trial_snapshot(self, snapshot: str | None) -> None:
        self.app["trialSnapshot"] = snapshot
        self.save()

    def commit(self, version: str) -> None:
        if self.app["trial"] != version:
            return
        old = self.app["current"]
        self.app.update(current=version, previous=old, trial=None, trialBoots=0, trialSnapshot=None)
        self._event("activated", version, previous=old)
        self.save()
        self._prune()

    def abandon(self, version: str, *, reason: str) -> None:
        """Drop a failed trial; restore the pre-trial database snapshot if one was taken.

        The app process must already be stopped (true both for the supervisor's
        health-check path and for the crash path in :meth:`select_for_boot`).
        """
        if self.app["trial"] != version:
            return
        snapshot = self.app.get("trialSnapshot")
        restored = False
        if snapshot and Path(snapshot).is_file():
            dbsnap.restore(Path(snapshot), self.layout.database)
            restored = True
        self.app.update(trial=None, trialBoots=0, trialSnapshot=None)
        if restored:
            self._event("databaseRestored", version, snapshot=Path(snapshot).name)
        self._event("rolledBack", version, reason=reason, keptVersion=self.app["current"])
        self.save()
        if version not in (self.app["current"], self.app["previous"]):
            shutil.rmtree(self.layout.app_dir(version), ignore_errors=True)

    def rollback(self) -> str:
        """User-initiated: swap current and previous; takes effect at the next start."""
        previous = self.app["previous"]
        if previous is None or not self.layout.app_dir(previous).is_dir():
            raise BootStateError("没有可以回滚的上一版本")
        current = self.app["current"]
        self.app.update(current=previous, previous=current, trial=None, trialBoots=0, trialSnapshot=None)
        self._event("manualRollback", previous, fromVersion=current)
        self.save()
        return previous

    def _prune(self) -> None:
        keep = {self.app["current"], self.app["previous"], self.app["trial"]}
        for version in self.layout.installed_app_versions():
            if version not in keep:
                shutil.rmtree(self.layout.app_dir(version), ignore_errors=True)

    def status(self) -> dict[str, Any]:
        return {
            "current": self.app["current"],
            "previous": self.app["previous"],
            "trial": self.app["trial"],
            "installed": self.layout.installed_app_versions(),
            "events": list(self.events),
        }
