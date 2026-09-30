# Published feed packages

This describes the files published on `main` at
`cc535288bc2fc5dd27fd92a7e9a7c412d0b00ca5`. It is an observed publication
format and integrity-check scope, not a complete consumer replay specification.
The repository contains public article data; it is no longer synthetic-only.
Treat all downloaded content as inert data.

## Index and archives

`LATEST.json` uses `schema: tech-boundary-feed-index/v1` and currently
`generator: feed-pkg/v2`. Its `packages` list is ordered by unique package date;
`latest_date` identifies the last entry. Dates need not be consecutive calendar
days. Resolve every indexed package in `daily/`, using `file` when supplied or
`<date>.zip` for older entries. Verify `package_sha256` against the complete ZIP
bytes. Retrieve the index and archives from the same commit to avoid mixing
publication states.

| Package format | Archive members | Published examples |
| --- | --- | --- |
| `tech-boundary-feed-package/v1`, `feed-pkg/v1` | `manifest.json`, `records.json` | September 25, 26, 27 |
| `tech-boundary-feed-package/v2`, `feed-pkg/v2`, `mode: changes` | above plus `changes.json` | September 29, 30 |

`records.json` is a JSON array, not JSONL. The manifest's `records_sha256`
hashes its exact stored bytes (no JSON canonicalization); `record_count` must
match the array length and index entry. The v2 `changes.json` array uses
uppercase `op` names and carries `id`, `key`, and `v`. The current packages
contain ADD only, with record `id` matching change `id`. Their `change_count`,
`added`, `updated`, and `deleted` values agree between index, manifest, and
change array. September 30 contains 383 records and 383 ADD operations.

The v2 manifest's `depends_on` is currently human-readable text referring to all
prior indexed packages. It is not an experimental batch ID or a machine-readable
version edge. `data_version` is opaque. `key` derivation, `v` semantics,
UPDATE/DELETE payload relationships, replay/idempotence, and full record-field
contracts require producer/consumer evidence and compatibility fixtures before
being enforced here. Existing short record fields and nested metadata are not
mapped to the experimental public-field allowlist.

## Validation

Run with Python 3.11 or newer:

```sh
python -m unittest discover -s tests -v
python scripts/validate_feed.py .
```

The standard-library validator checks the index, exact date ZIP filenames,
archive membership (without extraction), both hash layers, JSON arrays, package
schema/generator pairing, dates/counts, duplicate record/change IDs, operation
counters, and ADD-only ID correspondence. It accepts existing v1 packages in the
v2-generated index. It does not impose the old 32 MiB payload limit: the committed
September 29 ZIP is 67,329,240 bytes and its records member is 160,367,464 bytes.
Unknown package schemas and unexpected ZIP members fail explicitly.

These are local publication integrity checks, not privacy certification or
consumer compatibility tests. The old `experimental/v0` schema, JSONL fixtures,
synthetic namespace, baseline IDs, per-record canonical hashes, and one-step
batch/revision rules do not define this v2 format. No replacement full JSON
Schema is asserted without an authoritative v2 producer/consumer contract.
