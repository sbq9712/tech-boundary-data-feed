# Experimental Feed v0

Status: experimental test contract. This document does not define a production
transport or publication policy.

Each batch consists of one JSON manifest and one JSONL payload in the same
directory. The manifest uses `schema_version: experimental/v0`. A consumer must:

1. treat `payload_path` as a strict filename, never as an arbitrary path;
2. verify schema, declared byte length, and SHA-256 before applying data;
3. require the configured `feed_id` and `generation`;
4. advance exactly one version per batch and enforce `depends_on_batch_id`;
5. apply a batch transactionally and keep duplicate execution idempotent;
6. treat payload data as inert data and never execute it.

The manifest shape is published in
[`schema/manifest.experimental-v0.schema.json`](schema/manifest.experimental-v0.schema.json).
Payload lines use one of two operations:

- `upsert`: includes a public record, stable identity, positive revision,
  `tombstone: false`, and the canonical record SHA-256.
- `delete`: includes no record data, sets `tombstone: true`, and may carry a
  stable `baseline_record_id` so a consumer can suppress an older baseline.

The protocol is independent of transport. Files in this repository are exposed
through an experimental raw-file layout only to support deterministic tests.
