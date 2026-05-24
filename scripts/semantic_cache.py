"""Disk-backed semantic cache.

LRU + SHA-256 keys + 7-day TTL + gzip storage. See V2 §15 / V1 §15.

Cache hits expected for:
- Repeat queries with same tier (user switches tier but reuses query string)
- Citation expansion: shared references across seeds
- Cross-session re-runs of the same query

NOT cached:
- LLM RCS classification (stochastic)
- User file reads

The cache is keyed by canonical JSON of (query, tier, source, **kwargs) so
field order does not affect the hash.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


class SemanticCache:
    """LRU + SHA-256 key + TTL disk cache.

    Files are stored as ``<key>.json.gz`` under ``cache_dir``. mtime is used
    as both the TTL clock and the LRU ordering signal. Reading a file
    refreshes its mtime (LRU touch).
    """

    def __init__(
        self,
        cache_dir: str,
        max_size_mb: int = 500,
        ttl_days: int = 7,
    ):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_mb = max_size_mb
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl = timedelta(days=ttl_days)

    # ------------------------------------------------------------------ #
    # Keys
    # ------------------------------------------------------------------ #

    def _key(self, query: str, tier: str, source: str, **kwargs: Any) -> str:
        payload = {"q": query, "t": tier, "s": source, **kwargs}
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _path_for(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json.gz"

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #

    def get(
        self,
        query: str,
        tier: str,
        source: str,
        **kwargs: Any,
    ) -> Optional[Any]:
        """Return cached value or None. Misses include TTL expiry."""
        key = self._key(query, tier, source, **kwargs)
        path = self._path_for(key)
        if not path.exists():
            return None
        try:
            age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return None
        if age > self.ttl:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        try:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
            try:
                path.unlink()
            except OSError:
                pass
            return None
        # LRU touch: refresh mtime so frequently used entries survive eviction.
        try:
            os.utime(path, None)
        except OSError:
            pass
        return data

    def set(
        self,
        query: str,
        tier: str,
        source: str,
        data: Any,
        **kwargs: Any,
    ) -> None:
        """Store value under (query, tier, source, **kwargs). Auto-evicts."""
        key = self._key(query, tier, source, **kwargs)
        path = self._path_for(key)
        tmp_path = path.with_suffix(".tmp")
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)
        self._maybe_evict()

    # ------------------------------------------------------------------ #
    # Eviction
    # ------------------------------------------------------------------ #

    def _total_size_bytes(self) -> int:
        total = 0
        for p in self.cache_dir.glob("*.json.gz"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def _maybe_evict(self) -> None:
        """LRU eviction by mtime when total bytes > max_size_bytes."""
        total = self._total_size_bytes()
        if total <= self.max_size_bytes:
            return
        files = []
        for p in self.cache_dir.glob("*.json.gz"):
            try:
                files.append((p.stat().st_mtime, p.stat().st_size, p))
            except OSError:
                continue
        files.sort(key=lambda t: t[0])  # oldest mtime first
        for _, size, p in files:
            if total <= self.max_size_bytes:
                break
            try:
                p.unlink()
                total -= size
            except OSError:
                continue

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #

    def stats(self) -> dict:
        entries = list(self.cache_dir.glob("*.json.gz"))
        return {
            "entries": len(entries),
            "size_bytes": self._total_size_bytes(),
            "max_size_bytes": self.max_size_bytes,
            "ttl_days": self.ttl.days,
        }

    def clear(self) -> int:
        """Remove all cache entries. Returns count of files deleted."""
        n = 0
        for p in self.cache_dir.glob("*.json.gz"):
            try:
                p.unlink()
                n += 1
            except OSError:
                continue
        return n
