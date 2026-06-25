"""Orchestrator — sequences a run, owns the manifest, handles resume (spec §7.1).

For each discovered petition: fetch metadata, gate by language, pull all comments
(resuming from any stored cursor), normalize, retain the raw payload, and persist one
Observation plus upserted rows. Bot challenges halt the run; per-petition faults are
recorded and the run continues (spec §9).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from . import adapter, client, comments, discovery, manifest, normalize
from .comments import CommentBatch
from .manifest import PetitionOutcome
from .models import Observation, Run, RunStatus
from .store import Store
from .transport import (
    BotChallengeError,
    InvalidClientError,
    Transport,
    TransportError,
)

# Errors that are systemic (affect every petition) and must halt the whole run rather
# than be recorded as a per-petition fault: a bot challenge, or a rejected client header
# (adapter drift). Everything else is isolated to the one petition.
_FATAL = (BotChallengeError, InvalidClientError)
# Per-petition faults: recorded, the run continues (spec §9).
_PER_PETITION = (client.ParseError, client.GraphQLError, TransportError)

log = structlog.get_logger(__name__)


@dataclass
class RunMetrics:
    """Per-run counters emitted in the manifest (spec §13)."""

    discovered: int = 0
    collected: int = 0
    excluded_language: int = 0
    not_found: int = 0
    parse_errors: int = 0
    comments_collected: int = 0
    incomplete_petitions: int = 0
    exclusions: list[dict[str, str]] = field(default_factory=list)
    outcomes: list[PetitionOutcome] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Scalar counters for the manifest and logs (excludes list fields)."""
        return {
            "discovered": self.discovered,
            "collected": self.collected,
            "excluded_language": self.excluded_language,
            "not_found": self.not_found,
            "parse_errors": self.parse_errors,
            "comments_collected": self.comments_collected,
            "incomplete_petitions": self.incomplete_petitions,
        }


def _new_id() -> str:
    return uuid.uuid4().hex


class Orchestrator:
    """Drives one collection run over a set of petition identifiers."""

    def __init__(self, tx: Transport, store: Store, settings: Any) -> None:
        self._tx = tx
        self._store = store
        self._settings = settings

    def run(self, identifiers: list[str], query_or_targets: str) -> RunMetrics:
        run = Run(
            run_id=_new_id(),
            started_at=datetime.now(UTC),
            finished_at=None,
            query_or_targets=query_or_targets,
            adapter_version=adapter.ADAPTER_VERSION,
            status=RunStatus.RUNNING,
        )
        self._store.start_run(run)
        metrics = RunMetrics(discovered=len(identifiers))
        status = RunStatus.COMPLETE
        try:
            for ident in identifiers:
                self._collect_one(ident, run.run_id, metrics)
        except _FATAL as exc:
            log.error("run_halted", reason=type(exc).__name__, error=str(exc))
            status = RunStatus.PARTIAL
        finally:
            finished_at = datetime.now(UTC)
            self._store.finish_run(run.run_id, status.value, finished_at)
            manifest_path = manifest.write_manifest(
                self._settings.manifest_dir,
                manifest.build_manifest(
                    run,
                    status=status,
                    finished_at=finished_at,
                    counts=metrics.counts(),
                    outcomes=metrics.outcomes,
                    exclusions=metrics.exclusions,
                ),
            )
        log.info("run_complete", manifest=str(manifest_path), **metrics.counts())
        return metrics

    def _collect_one(self, ident: str, run_id: str, metrics: RunMetrics) -> None:
        """Collect one petition. Systemic errors (in _FATAL) propagate to halt the run;
        per-petition faults are recorded and the method returns."""
        # 1. Metadata. ParseError retains the raw payload for diagnosis (FR-7.4).
        try:
            fields, petition_raw = client.fetch_petition(self._tx, ident)
        except client.PetitionNotFoundError:
            log.warning("petition_not_found", identifier=ident)
            metrics.not_found += 1
            return
        except client.ParseError as exc:
            self._store.save_raw_payload(ident, datetime.now(UTC), exc.raw)
            log.error("petition_parse_failure", identifier=ident, error=str(exc))
            metrics.parse_errors += 1
            return
        except _PER_PETITION as exc:
            log.error("petition_fetch_failed", identifier=ident, error=str(exc))
            metrics.parse_errors += 1
            return

        # 2. Language gate (FR-1.5; language is detected from petition text).
        language = discovery.detect_language(
            " ".join(filter(None, [fields.get("title"), fields.get("description")]))
        )
        if (
            self._settings.exclude_non_allowed_languages
            and language is not None
            and language not in self._settings.language_allowlist
        ):
            log.info("excluded_non_english", identifier=ident, language=language)
            metrics.excluded_language += 1
            metrics.exclusions.append({"identifier": ident, "language": language})
            return

        # 3. Persist the petition first so incremental comment upserts satisfy the FK.
        petition = normalize.normalize_petition(fields, language)
        pid = petition.petition_id
        self._store.upsert_petition(petition, run_id)

        # 4. Walk comments, persisting each page + cursor as it arrives (FR-4.4 resume,
        #    FR-5.2 raw). A fault after some pages leaves progress checkpointed.
        stored_before = self._store.count_comments(pid)
        start_cursor, already_done = self._store.get_comment_progress(pid)
        raw_pages: list[dict[str, Any]] = []
        reported_total = petition.comment_total

        def on_batch(batch: CommentBatch) -> None:
            models = [
                normalize.normalize_comment(c, pid, run_id) for c in batch.comments
            ]
            self._store.upsert_comments(models)
            self._store.set_comment_progress(
                pid, batch.end_cursor, completed=not batch.has_next
            )

        fault: Exception | None = None
        try:
            result = comments.collect_comments(
                self._tx,
                ident,
                start_cursor=None if already_done else start_cursor,
                on_batch=on_batch,
            )
            raw_pages = result.raw_pages
            reported_total = result.reported_total or reported_total
        except client.PetitionNotFoundError as exc:
            fault = exc  # became unavailable mid-pull
        except _PER_PETITION as exc:
            fault = exc
        if fault is not None:
            log.error("comment_pull_failed", identifier=ident, error=str(fault))
            metrics.parse_errors += 1

        # 5. Completeness reconciles STORED unique comments against the reported total
        #    (correct across a resumed multi-run pull), not just this run's slice.
        stored_after = self._store.count_comments(pid)
        completeness = (
            1.0 if reported_total <= 0 else min(1.0, stored_after / reported_total)
        )

        # 6. Retain the full raw payload (petition + comment pages) and record the
        #    Observation, even on a partial pull, so the run state is auditable.
        captured_at = datetime.now(UTC)
        raw_ref = self._store.save_raw_payload(
            pid, captured_at, {"petition": petition_raw, "comments": raw_pages}
        )
        self._store.insert_observation(
            Observation(
                observation_id=_new_id(),
                petition_id=pid,
                run_id=run_id,
                captured_at=captured_at,
                raw_payload_ref=raw_ref,
                comment_completeness=completeness,
            ),
            petition.signatures_total,
            petition.comment_total,
        )

        metrics.collected += 1
        metrics.comments_collected += stored_after - stored_before
        if completeness < 1.0:
            metrics.incomplete_petitions += 1
        metrics.outcomes.append(
            PetitionOutcome(
                petition_id=pid,
                identifier=ident,
                comments_collected=stored_after,
                comment_total=petition.comment_total,
                completeness=round(completeness, 4),
            )
        )
        log.info(
            "petition_collected",
            identifier=ident,
            comments=stored_after,
            completeness=round(completeness, 4),
        )
