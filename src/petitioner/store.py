"""Persistence — SQLite system of record + raw payload retention + exports (spec §11).

Snapshot-latest (decision D1): petitions/comments/tags upsert by id; each fetch
appends an immutable Observation that retains a reference to the raw payload on disk
(NFR-2). Provides snapshot (default) + longitudinal views (FR-6.2) and Parquet/
CSV export (FR-5/§11.2).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import orjson
import polars as pl

from .models import Comment, Observation, Petition, Run

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    query_or_targets TEXT,
    adapter_version TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS petition (
    petition_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    signatures_total INTEGER,
    signatures_displayed INTEGER,
    signatures_displayed_localized TEXT,
    goal INTEGER,
    created_at TEXT,
    creator_name TEXT,
    creator_location TEXT,
    organization TEXT,
    is_verified_victory INTEGER,
    status TEXT,
    comment_total INTEGER,
    language TEXT,
    last_seen_run TEXT
);
CREATE TABLE IF NOT EXISTS comment (
    comment_id TEXT PRIMARY KEY,
    petition_id TEXT NOT NULL REFERENCES petition(petition_id),
    text TEXT,
    role TEXT,
    likes INTEGER,
    city TEXT,
    created_at TEXT,
    observed_in_run TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag (
    tag_id TEXT PRIMARY KEY,
    name TEXT,
    slug TEXT
);
CREATE TABLE IF NOT EXISTS petition_tag (
    petition_id TEXT NOT NULL REFERENCES petition(petition_id),
    tag_id TEXT NOT NULL REFERENCES tag(tag_id),
    PRIMARY KEY (petition_id, tag_id)
);
CREATE TABLE IF NOT EXISTS observation (
    observation_id TEXT PRIMARY KEY,
    petition_id TEXT NOT NULL REFERENCES petition(petition_id),
    run_id TEXT NOT NULL REFERENCES run(run_id),
    captured_at TEXT NOT NULL,
    raw_payload_ref TEXT NOT NULL,
    comment_completeness REAL NOT NULL,
    signatures_total INTEGER,
    comment_total INTEGER
);
CREATE TABLE IF NOT EXISTS comment_progress (
    petition_id TEXT PRIMARY KEY REFERENCES petition(petition_id),
    last_cursor TEXT,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_comment_petition ON comment(petition_id);
CREATE INDEX IF NOT EXISTS idx_obs_petition ON observation(petition_id, captured_at);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


class Store:
    """SQLite-backed store. Use as a context manager."""

    def __init__(self, db_path: Path, raw_payload_dir: Path) -> None:
        self._raw_dir = raw_payload_dir
        self._raw_dir.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # -- runs --------------------------------------------------------------- #
    def start_run(self, run: Run) -> None:
        self._conn.execute(
            "INSERT INTO run(run_id, started_at, finished_at, query_or_targets, "
            "adapter_version, status) VALUES (?,?,?,?,?,?)",
            (
                run.run_id,
                _iso(run.started_at),
                _iso(run.finished_at),
                run.query_or_targets,
                run.adapter_version,
                run.status.value,
            ),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str, finished_at: datetime) -> None:
        self._conn.execute(
            "UPDATE run SET status=?, finished_at=? WHERE run_id=?",
            (status, _iso(finished_at), run_id),
        )
        self._conn.commit()

    # -- raw payloads ------------------------------------------------------- #
    def save_raw_payload(
        self, petition_id: str, captured_at: datetime, payload: Any
    ) -> str:
        """Write a raw payload to disk keyed by id + timestamp; return its ref."""
        stamp = captured_at.strftime("%Y%m%dT%H%M%S%f")
        path = self._raw_dir / f"{petition_id}_{stamp}.json"
        path.write_bytes(orjson.dumps(payload))
        return str(path)

    # -- upserts ------------------------------------------------------------ #
    def upsert_petition(self, p: Petition, run_id: str) -> None:
        self._conn.execute(
            """
            INSERT INTO petition(petition_id, slug, url, title, description,
                signatures_total, signatures_displayed, signatures_displayed_localized,
                goal, created_at, creator_name, creator_location, organization,
                is_verified_victory, status, comment_total, language, last_seen_run)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(petition_id) DO UPDATE SET
                slug=excluded.slug, url=excluded.url, title=excluded.title,
                description=excluded.description,
                signatures_total=excluded.signatures_total,
                signatures_displayed=excluded.signatures_displayed,
                signatures_displayed_localized=excluded.signatures_displayed_localized,
                goal=excluded.goal, created_at=excluded.created_at,
                creator_name=excluded.creator_name,
                creator_location=excluded.creator_location,
                organization=excluded.organization,
                is_verified_victory=excluded.is_verified_victory,
                status=excluded.status,
                comment_total=excluded.comment_total, language=excluded.language,
                last_seen_run=excluded.last_seen_run
            """,
            (
                p.petition_id,
                p.slug,
                p.url,
                p.title,
                p.description,
                p.signatures_total,
                p.signatures_displayed,
                p.signatures_displayed_localized,
                p.goal,
                _iso(p.created_at),
                p.creator_name,
                p.creator_location,
                p.organization,
                int(p.is_verified_victory)
                if p.is_verified_victory is not None
                else None,
                p.status,
                p.comment_total,
                p.language,
                run_id,
            ),
        )
        for tag in p.tags:
            self._conn.execute(
                "INSERT INTO tag(tag_id, name, slug) VALUES (?,?,?) "
                "ON CONFLICT(tag_id) DO UPDATE SET "
                "name=excluded.name, slug=excluded.slug",
                (tag.tag_id, tag.name, tag.slug),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO petition_tag(petition_id, tag_id) VALUES (?,?)",
                (p.petition_id, tag.tag_id),
            )
        self._conn.commit()

    def upsert_comments(self, comments: list[Comment]) -> None:
        self._conn.executemany(
            """
            INSERT INTO comment(comment_id, petition_id, text, role, likes, city,
                created_at, observed_in_run)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(comment_id) DO UPDATE SET
                text=excluded.text, role=excluded.role, likes=excluded.likes,
                city=excluded.city, created_at=excluded.created_at,
                observed_in_run=excluded.observed_in_run
            """,
            [
                (
                    c.comment_id,
                    c.petition_id,
                    c.text,
                    c.role,
                    c.likes,
                    c.city,
                    _iso(c.created_at),
                    c.observed_in_run,
                )
                for c in comments
            ],
        )
        self._conn.commit()

    def insert_observation(
        self, obs: Observation, signatures_total: int | None, comment_total: int
    ) -> None:
        self._conn.execute(
            "INSERT INTO observation(observation_id, petition_id, run_id, captured_at, "
            "raw_payload_ref, comment_completeness, signatures_total, comment_total) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                obs.observation_id,
                obs.petition_id,
                obs.run_id,
                _iso(obs.captured_at),
                obs.raw_payload_ref,
                obs.comment_completeness,
                signatures_total,
                comment_total,
            ),
        )
        self._conn.commit()

    def count_comments(self, petition_id: str) -> int:
        """Count stored unique comments for a petition (across all runs)."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM comment WHERE petition_id=?", (petition_id,)
        ).fetchone()
        return int(row[0])

    # -- resume ------------------------------------------------------------- #
    def get_comment_progress(self, petition_id: str) -> tuple[str | None, bool]:
        row = self._conn.execute(
            "SELECT last_cursor, completed FROM comment_progress WHERE petition_id=?",
            (petition_id,),
        ).fetchone()
        if row is None:
            return None, False
        return row["last_cursor"], bool(row["completed"])

    def set_comment_progress(
        self, petition_id: str, last_cursor: str | None, completed: bool
    ) -> None:
        self._conn.execute(
            "INSERT INTO comment_progress(petition_id, last_cursor, completed) "
            "VALUES (?,?,?) ON CONFLICT(petition_id) DO UPDATE SET "
            "last_cursor=excluded.last_cursor, completed=excluded.completed",
            (petition_id, last_cursor, int(completed)),
        )
        self._conn.commit()

    # -- query views -------------------------------------------------------- #
    def snapshot(self) -> list[dict[str, Any]]:
        """Latest state per petition (the default view, FR-6.2)."""
        rows = self._conn.execute(
            "SELECT * FROM petition ORDER BY petition_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def longitudinal(self, petition_id: str) -> list[dict[str, Any]]:
        """Observation time series for one petition, with consecutive deltas."""
        rows = self._conn.execute(
            "SELECT captured_at, signatures_total, comment_total FROM observation "
            "WHERE petition_id=? ORDER BY captured_at",
            (petition_id,),
        ).fetchall()
        series: list[dict[str, Any]] = []
        prev: dict[str, Any] | None = None
        for r in rows:
            point = dict(r)
            if prev is not None:
                point["signatures_delta"] = _delta(
                    point["signatures_total"], prev["signatures_total"]
                )
                point["comment_delta"] = _delta(
                    point["comment_total"], prev["comment_total"]
                )
            series.append(point)
            prev = point
        return series

    # -- export ------------------------------------------------------------- #
    def export(self, export_dir: Path, fmt: str = "both") -> list[Path]:
        """Export petitions and comments to Parquet and/or CSV (§11.2)."""
        export_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for name, sql in (
            ("petitions", "SELECT * FROM petition"),
            ("comments", "SELECT * FROM comment"),
        ):
            rows = [dict(r) for r in self._conn.execute(sql).fetchall()]
            df = pl.DataFrame(rows) if rows else pl.DataFrame()
            if fmt in ("parquet", "both"):
                path = export_dir / f"{name}.parquet"
                df.write_parquet(path)
                written.append(path)
            if fmt in ("csv", "both"):
                path = export_dir / f"{name}.csv"
                df.write_csv(path)
                written.append(path)
        return written


def _delta(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous
