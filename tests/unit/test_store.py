"""Unit tests for the SQLite store (idempotency, observations, deltas, export)."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl

from petitioner.models import (
    Comment,
    Observation,
    Petition,
    Run,
    RunStatus,
    Tag,
)
from petitioner.store import Store


def _petition(sig: int, comment_total: int) -> Petition:
    return Petition(
        petition_id="p1",
        slug="s",
        url="u",
        title="t",
        description=None,
        signatures_total=sig,
        signatures_displayed=sig,
        signatures_displayed_localized=str(sig),
        goal=100,
        created_at=None,
        creator_name=None,
        creator_location=None,
        organization=None,
        is_verified_victory=None,
        status="PUBLISHED",
        comment_total=comment_total,
        language="en",
        tags=[Tag(tag_id="t1", name="Env", slug="env")],
    )


def _run(run_id: str) -> Run:
    return Run(
        run_id=run_id,
        started_at=datetime.now(UTC),
        finished_at=None,
        query_or_targets="x",
        adapter_version="v",
        status=RunStatus.RUNNING,
    )


def _comment(cid: str, run: str) -> Comment:
    return Comment(
        comment_id=cid,
        petition_id="p1",
        text="hi",
        role="SUPPORTER_COMMENT",
        likes=1,
        city=None,
        created_at=None,
        observed_in_run=run,
    )


def test_idempotent_upsert_and_observation_append(tmp_path):
    with Store(tmp_path / "db.sqlite", tmp_path / "raw") as store:
        for i, run_id in enumerate(["r1", "r2"]):
            store.start_run(_run(run_id))
            store.upsert_petition(_petition(100 + i, 3), run_id)
            store.upsert_comments([_comment("c1", run_id), _comment("c2", run_id)])
            ref = store.save_raw_payload("p1", datetime.now(UTC), {"x": i})
            store.insert_observation(
                Observation(
                    observation_id=f"o{i}",
                    petition_id="p1",
                    run_id=run_id,
                    captured_at=datetime.now(UTC),
                    raw_payload_ref=ref,
                    comment_completeness=1.0,
                ),
                signatures_total=100 + i,
                comment_total=3,
            )
        snap = store.snapshot()
        assert len(snap) == 1  # one petition row despite two runs (upsert)
        assert snap[0]["signatures_total"] == 101  # latest wins
        # Comments upserted, not duplicated.
        long = store.longitudinal("p1")
        assert len(long) == 2  # two observations
        assert long[1]["signatures_delta"] == 1  # 101 - 100
        assert long[1]["comment_delta"] == 0


def test_comment_progress_resume(tmp_path):
    with Store(tmp_path / "db.sqlite", tmp_path / "raw") as store:
        store.start_run(_run("r1"))
        store.upsert_petition(_petition(10, 0), "r1")
        assert store.get_comment_progress("p1") == (None, False)
        store.set_comment_progress("p1", "CURSOR==", completed=False)
        assert store.get_comment_progress("p1") == ("CURSOR==", False)


def test_count_comments(tmp_path):
    with Store(tmp_path / "db.sqlite", tmp_path / "raw") as store:
        store.start_run(_run("r1"))
        store.upsert_petition(_petition(10, 2), "r1")
        assert store.count_comments("p1") == 0
        store.upsert_comments([_comment("c1", "r1"), _comment("c2", "r1")])
        assert store.count_comments("p1") == 2
        # Re-upsert same ids -> still 2 (dedup by primary key).
        store.upsert_comments([_comment("c1", "r1")])
        assert store.count_comments("p1") == 2


def test_export(tmp_path):
    with Store(tmp_path / "db.sqlite", tmp_path / "raw") as store:
        store.start_run(_run("r1"))
        store.upsert_petition(_petition(10, 1), "r1")
        store.upsert_comments([_comment("c1", "r1")])
        written = store.export(tmp_path / "exports", fmt="both")
    names = {p.name for p in written}
    assert names == {
        "petitions.parquet",
        "petitions.csv",
        "comments.parquet",
        "comments.csv",
    }
    df = pl.read_parquet(tmp_path / "exports" / "comments.parquet")
    assert df.height == 1
