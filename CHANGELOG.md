# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Opt-in live end-to-end smoke test (`PETITIONER_LIVE=1`) that drives the full pipeline — metadata
  fetch, streamed raw capture, comment walk, observation, export, manifest — against a real petition.

### Changed

- Raw payload capture now streams to a JSON-lines file per petition (`<petition_id>_<stamp>.jsonl`:
  petition payload on line 1, one raw comment page per subsequent line), replacing the single
  combined JSON file. Memory stays bounded regardless of comment count, and an interrupted capture
  retains every page fetched up to the interruption.
- Reduced per-request and per-write overhead: the transport builds its retry policy once instead of
  per call, petition upserts batch tag and decision-maker writes, and exports read tables directly
  into polars without materializing rows as Python dicts.

### Fixed

- Adapter tracks Change.org's rename of the decision-maker `state` field to `stateCode`
  (`ADAPTER_VERSION` bumped to `+dm2`); stored and exported data keep the `state` column unchanged.

## [0.1.0] - 2026-07-26

### Added

- Authentication-free collection of Change.org petitions and their complete comment sets.
- Petition discovery via sitemap, keyword filter over sitemap slugs, and caller-supplied URL/id
  lists, with English-language gating.
- Formal decision makers (petition targets, including politicians) captured per petition and
  exported in a `decision_makers` table.
- SQLite store with snapshot-latest semantics, immutable per-fetch observations, raw payload
  retention, and cross-run comment resume.
- Parquet/CSV export and per-run JSON manifests.
- `petitioner` command-line interface (`collect`, `export`, `show`).

[Unreleased]: https://github.com/nniiicc/petitioner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nniiicc/petitioner/releases/tag/v0.1.0
