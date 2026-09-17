"""Fetches Pokémon details and localized names off the daemon's thread.

A detail page needs one request for the species and one per type, ability and
move it names, which can be a hundred requests on first open. Made on the
daemon's own thread, those would freeze every click in the popup until they
finished. Here they run in the background: the daemon publishes what is
cached at once, and publishes again when `take_changed` says more arrived.

Only the PokeAPI caches are written from this thread. Profiles and the save are
changed by the daemon, on its own thread, from those caches.
"""

from __future__ import annotations

import queue
import threading

from .pokeapi import PokeAPI, PokeAPIError


class DetailLoader:
    def __init__(self, api: PokeAPI, start: bool = True) -> None:
        self.api = api
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._pending: set[tuple] = set()
        self._failed_details: set[int] = set()
        self._failed_names: set[tuple[str, str]] = set()
        self._changed = threading.Event()
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="poketokenbar-details",
                                            daemon=True)
            self._thread.start()

    # --- asking ----------------------------------------------------------------

    def request_details(self, species_id: int, retry: bool = False) -> None:
        """Queue one species. A failed one is only asked again on retry.

        Failures are remembered because every arrival triggers a publish, and a
        publish asks again for whatever is missing: offline, re-queueing a
        failure would be a loop of requests that never ends.
        """
        with self._lock:
            if species_id in self._failed_details and not retry:
                return
            if retry:
                # A retry is for the whole page, names included.
                self._failed_names.clear()
            self._failed_details.discard(species_id)
            key = ("details", species_id)
            if key in self._pending:
                return
            self._pending.add(key)
        self._queue.put(key)

    def request_names(self, kind: str, names) -> None:
        for name in names:
            key = ("names", kind, name)
            with self._lock:
                if key in self._pending or (kind, name) in self._failed_names:
                    continue
                self._pending.add(key)
            self._queue.put(key)

    # --- answering -------------------------------------------------------------

    def is_loading(self, species_id: int) -> bool:
        with self._lock:
            return ("details", species_id) in self._pending

    def has_failed(self, species_id: int) -> bool:
        with self._lock:
            return species_id in self._failed_details

    def is_loading_names(self, kind: str, name: str) -> bool:
        with self._lock:
            return ("names", kind, name) in self._pending

    def names_failed(self, kind: str, name: str) -> bool:
        with self._lock:
            return (kind, name) in self._failed_names

    def take_changed(self) -> bool:
        """Whether anything arrived since the last call."""
        if self._changed.is_set():
            self._changed.clear()
            return True
        return False

    def drain(self) -> None:
        """Do all queued work on the calling thread. For tests."""
        while True:
            try:
                key = self._queue.get_nowait()
            except queue.Empty:
                return
            self._work(key)

    # --- the thread ------------------------------------------------------------

    def _run(self) -> None:
        while True:
            self._work(self._queue.get())

    def _work(self, key: tuple) -> None:
        try:
            if key[0] == "details":
                try:
                    self.api.details(key[1])
                except PokeAPIError:
                    with self._lock:
                        self._failed_details.add(key[1])
            else:
                try:
                    self.api.resource_names(key[1], key[2])
                except PokeAPIError:
                    # The page falls back to a formatted name until a retry.
                    with self._lock:
                        self._failed_names.add((key[1], key[2]))
        except Exception:  # never let one bad response stop the thread
            pass
        finally:
            with self._lock:
                self._pending.discard(key)
            self._changed.set()
