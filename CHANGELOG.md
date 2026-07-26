# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
