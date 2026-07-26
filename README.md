# petitioner

Petitioner collects Change.org petitions and their complete comment sets into a SQLite store with
Parquet/CSV export. It requires no login or API key.

## Installation

```bash
pip install petitioner
```

## Usage

```bash
petitioner collect --sitemap --limit 50    # discover + collect from the sitemap
petitioner export --format both            # write Parquet + CSV
petitioner show --petition-id 18514354     # show one petition's longitudinal series
```

## Documentation

Full documentation — configuration, the data model, and contributing — is at
[DOCUMENTATION.md](https://github.com/nniiicc/petitioner/blob/main/DOCUMENTATION.md).

## License

Released under the MIT License. See
[LICENSE](https://github.com/nniiicc/petitioner/blob/main/LICENSE).
