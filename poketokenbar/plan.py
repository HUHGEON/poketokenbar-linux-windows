"""Read the local Codex account through its supported app-server protocol.

No login, logout, token refresh, usage request, or credential export. Only the
plan name leaves the reader; account identifiers and email are discarded.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from .processes import background_options

MULTIPLIERS = {"go": 1, "plus": 1, "pro": 5, "pro_5x": 5, "pro_20x": 5}


def executable() -> str | None:
    found = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if found:
        return found
    # Desktop's bundled native CLI need not be on a tray app's inherited PATH.
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        candidates = list((Path(local) / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"))
        if candidates:
            return str(max(candidates, key=lambda path: path.stat().st_mtime))
    return None


def read_plan(command: str, timeout: float = 8) -> str | None:
    """Bounded handshake; terminate the private helper on success or failure."""
    process = subprocess.Popen(
        [command, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        **background_options(),
    )
    messages = queue.Queue()

    def collect():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            messages.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def response(request_id):
        while True:
            if time.monotonic() >= deadline:
                raise queue.Empty
            message = messages.get(timeout=max(0, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError("account helper exited")
            if isinstance(message, dict) and message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("account query unavailable")
                result = message.get("result")
                return result if isinstance(result, dict) else {}

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "poketokenbar", "version": "0.1.0"}}})
        response(1)
        send({"method": "initialized"})
        send({"id": 2, "method": "account/read", "params": {"refreshToken": False}})
        account = response(2).get("account")
        if not isinstance(account, dict) or account.get("type") != "chatgpt":
            return None
        value = account.get("planType")
        return value.lower() if isinstance(value, str) and value.lower() in MULTIPLIERS else None
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        reader.join(timeout=1)
        process.stdin.close()
        process.stdout.close()


def read_rate_limits(command: str, timeout: float = 12) -> dict | None:
    """Read Codex account limits without starting a model turn."""
    process = subprocess.Popen(
        [command, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        **background_options(),
    )
    messages = queue.Queue()

    def collect():
        try:
            for line in process.stdout:
                try:
                    messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            messages.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(payload):
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

    def response(request_id):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty
            message = messages.get(timeout=remaining)
            if message is None:
                raise RuntimeError("account helper exited")
            if isinstance(message, dict) and message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("rate limit query unavailable")
                result = message.get("result")
                return result if isinstance(result, dict) else {}

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "poketokenbar", "title": "PokeTokenBar",
                           "version": "0.1.0"},
            "capabilities": {"experimentalApi": True},
        }})
        response(1)
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        result = response(2)
        return result if isinstance(result.get("rateLimits"), dict) else None
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        reader.join(timeout=1)
        process.stdin.close()
        process.stdout.close()


def parse_rate_limits(raw: dict | None) -> dict | None:
    """Normalize app-server snapshots into a small, UI-safe structure."""
    if not isinstance(raw, dict) or not isinstance(raw.get("rateLimits"), dict):
        return None
    primary = raw["rateLimits"]
    snapshots = [primary]
    seen = {primary.get("limitId") or "codex"}
    by_id = raw.get("rateLimitsByLimitId")
    if isinstance(by_id, dict):
        for key in sorted(by_id):
            snapshot = by_id[key]
            if not isinstance(snapshot, dict):
                continue
            identity = snapshot.get("limitId") or key
            if identity in seen:
                continue
            seen.add(identity)
            snapshots.append(snapshot)

    buckets = []
    for snapshot in snapshots:
        windows = []
        for kind in ("primary", "secondary"):
            item = snapshot.get(kind)
            if not isinstance(item, dict) or not isinstance(item.get("usedPercent"), (int, float)):
                continue
            resets = item.get("resetsAt")
            resets_at = None
            if isinstance(resets, (int, float)):
                from datetime import datetime, timezone
                resets_at = datetime.fromtimestamp(resets, timezone.utc).isoformat()
            windows.append({
                "kind": kind,
                "utilization": max(0.0, min(100.0, float(item["usedPercent"]))),
                "duration_minutes": item.get("windowDurationMins"),
                "resets_at": resets_at,
            })
        individual = snapshot.get("individualLimit")
        if not windows and not isinstance(individual, dict):
            continue
        raw_name = snapshot.get("limitName") or snapshot.get("limitId") or "codex"
        buckets.append({
            "id": snapshot.get("limitId") or "codex",
            "name": str(raw_name).replace("_", " ").capitalize(),
            "plan": snapshot.get("planType"),
            "windows": windows,
            "individual": individual if isinstance(individual, dict) else None,
        })
    return {"buckets": buckets} if buckets else None


class PlanSource:
    """Poll off-thread so a missing or slow Codex cannot freeze purchases."""

    def __init__(self):
        self._results = queue.Queue()
        self._limit_results = queue.Queue()
        self._worker = None
        self._limit_worker = None
        self._next_check = 0.0
        self._next_limit_check = 0.0
        self.current: str | None = None
        self.current_limits: dict | None = None
        self.status = "checking"

    def _read(self):
        result = None
        try:
            command = executable()
            result = read_plan(command) if command else None
        except (OSError, ValueError, RuntimeError, queue.Empty, subprocess.SubprocessError):
            pass
        self._results.put(result)

    def _read_limits(self):
        rate_limits = None
        try:
            command = executable()
            rate_limits = parse_rate_limits(read_rate_limits(command)) if command else None
        except (OSError, ValueError, RuntimeError, queue.Empty, subprocess.SubprocessError):
            pass
        self._limit_results.put(rate_limits)

    def get(self) -> str | None:
        try:
            self.current = self._results.get_nowait()
            self.status = "detected" if self.current else "unavailable"
        except queue.Empty:
            pass
        try:
            self.current_limits = self._limit_results.get_nowait()
        except queue.Empty:
            pass
        if time.monotonic() >= self._next_check and (
            self._worker is None or not self._worker.is_alive()
        ):
            self._next_check = time.monotonic() + 120
            self._worker = threading.Thread(target=self._read, daemon=True)
            self._worker.start()
        if time.monotonic() >= self._next_limit_check and (
            self._limit_worker is None or not self._limit_worker.is_alive()
        ):
            self._next_limit_check = time.monotonic() + 300
            self._limit_worker = threading.Thread(target=self._read_limits, daemon=True)
            self._limit_worker.start()
        return self.current

    @property
    def ready(self) -> bool:
        return not self._results.empty() or not self._limit_results.empty()
