# GiloDAM Catalog Benchmark — 24 August 2026

Synthetic catalogs were created against the release schema, including Assets, Locations, descriptive metadata, structured indexes, and FTS5 search rows. Each database passed `PRAGMA integrity_check` and returned the expected catalog count.

| Catalog | Seed time | Database size | Exact FTS search median | Browse 5,000 rows median | Count median | Verdict |
|---:|---:|---:|---:|---:|---:|---|
| 100,000 assets | 3.72 s | 121.0 MB | 0.0025 s | 0.2904 s | 0.0168 s | V1 interactive target passed |
| 1,000,000 assets | 40.68 s | 1.17 GB | 0.0117 s | 2.1204 s | 0.1661 s | Architecture stress passed |

The developer specification defines one million assets as an architectural target, not a V1 performance SLA. The million-record database remained valid and searchable without a schema or memory blocker. Loading 5,000 fully materialized UI rows was slightly above two seconds and is a clear future optimization target; exact search and aggregate counts remained comfortably fast.

Reproduce either run from the project root:

```bash
PYTHONPATH=. python scripts/benchmark_catalog.py --records 100000 --runs 5
PYTHONPATH=. python scripts/benchmark_catalog.py --records 1000000 --runs 3
```

Results depend on hardware and storage. These numbers validate this build environment; the Windows release still requires the specification's Windows benchmark/QA pass.

