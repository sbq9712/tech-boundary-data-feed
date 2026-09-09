#!/usr/bin/env python3
"""Read-only, standard-library validator for this public synthetic Feed."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "experimental/v0"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 100_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_FIELDS = {
    "schema_version", "feed_id", "generation", "batch_id", "from_version",
    "to_version", "generated_at", "record_count", "payload_path",
    "payload_bytes", "payload_sha256", "depends_on_batch_id",
    "min_consumer_version",
}
OPERATION_FIELDS = {
    "operation", "record_id", "source_namespace", "revision",
    "content_sha256", "record", "tombstone", "baseline_record_id",
}
PUBLIC_FIELDS = {
    "record_id", "source_namespace", "revision", "title", "content",
    "source_name", "source_url", "published_at", "categories", "tags",
    "topics", "summary", "score", "parameters", "provenance",
    "baseline_record_id",
}
FORBIDDEN_FIELDS = {
    "comment", "reviewer_comment", "internal_analysis", "created_by",
    "last_modified_by", "user_id", "password", "token", "secret",
    "api_key", "confidentiality", "uploaded_file", "local_path", "prompt",
    "system_prompt", "review", "review_data", "internal", "internal_comment",
    "user_data", "email", "phone", "file_path", "confidential",
}
SECRET_MARKERS = (
    "-----begin private key-----", "-----begin rsa private key-----",
    "github_pat_", "ghp_",
)


class ValidationError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ValidationError(f"invalid {name}")
    return value


def require_nonnegative_int(name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return value


def require_safe_filename(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or not FILENAME_RE.fullmatch(value)
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValidationError(f"{name} must be a safe filename")
    return value


def require_timestamp(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"invalid {name}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"invalid {name}") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{name} must include timezone")
    return value


def scan_public(value: Any, path: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_FIELDS:
                raise ValidationError(f"forbidden field at {path}.{key}")
            scan_public(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scan_public(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            raise ValidationError(f"secret-like content at {path}")


def validate_record(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValidationError("upsert record must be an object")
    scan_public(raw)
    unknown = set(raw) - PUBLIC_FIELDS
    if unknown:
        raise ValidationError(f"unapproved public fields: {sorted(unknown)}")
    require_id("record_id", raw.get("record_id"))
    require_id("source_namespace", raw.get("source_namespace"))
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValidationError("revision must be positive")
    for field in ("title", "content", "source_name"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise ValidationError(f"{field} is required")
    source_url = raw.get("source_url")
    if source_url is not None and (
        not isinstance(source_url, str) or not source_url.startswith(("https://", "http://"))
    ):
        raise ValidationError("source_url must be HTTP(S)")
    if raw.get("published_at") is not None:
        require_timestamp("published_at", raw["published_at"])
    for field in ("categories", "tags", "topics"):
        value = raw.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValidationError(f"{field} must be a string list")
    for field in ("parameters", "provenance"):
        if not isinstance(raw.get(field, {}), dict):
            raise ValidationError(f"{field} must be an object")
    if raw.get("baseline_record_id") is not None:
        require_id("baseline_record_id", raw["baseline_record_id"])
    return raw


def validate_operation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) - OPERATION_FIELDS:
        raise ValidationError("invalid operation fields")
    operation = raw.get("operation")
    record_id = require_id("record_id", raw.get("record_id"))
    namespace = require_id("source_namespace", raw.get("source_namespace"))
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ValidationError("revision must be positive")
    digest = raw.get("content_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise ValidationError("invalid content_sha256")
    if namespace != "synthetic":
        raise ValidationError("current public fixture permits only synthetic namespace")

    if operation == "upsert":
        if raw.get("tombstone") is not False:
            raise ValidationError("upsert must set tombstone=false")
        record = validate_record(raw.get("record"))
        if (record["record_id"], record["source_namespace"], record["revision"]) != (
            record_id, namespace, revision,
        ):
            raise ValidationError("operation identity differs from record")
        if raw.get("baseline_record_id") != record.get("baseline_record_id"):
            raise ValidationError("operation baseline identity differs from record")
        projected = {key: record.get(key) for key in sorted(PUBLIC_FIELDS)}
        if sha256(canonical_bytes(projected)) != digest:
            raise ValidationError("record content hash mismatch")
    elif operation == "delete":
        if raw.get("tombstone") is not True or raw.get("record") is not None:
            raise ValidationError("delete must be a data-free tombstone")
        tombstone = {
            "record_id": record_id,
            "source_namespace": namespace,
            "revision": revision,
            "tombstone": True,
        }
        if raw.get("baseline_record_id") is not None:
            tombstone["baseline_record_id"] = require_id(
                "baseline_record_id", raw["baseline_record_id"]
            )
        if sha256(canonical_bytes(tombstone)) != digest:
            raise ValidationError("tombstone content hash mismatch")
    else:
        raise ValidationError("operation must be upsert or delete")
    return raw


def validate_manifest(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = path.read_bytes()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValidationError(f"manifest too large: {path}")
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(f"invalid manifest JSON: {path}") from exc
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValidationError(f"manifest field mismatch: {path}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("unsupported schema version")
    feed_id = require_id("feed_id", manifest["feed_id"])
    generation = require_id("generation", manifest["generation"])
    require_id("batch_id", manifest["batch_id"])
    require_timestamp("generated_at", manifest["generated_at"])
    if not isinstance(manifest["min_consumer_version"], str):
        raise ValidationError("min_consumer_version must be a string")
    if not feed_id.endswith("-synthetic") or not generation.startswith("test-"):
        raise ValidationError("production Feed identities are not approved")
    if path.parent.name != generation or path.parent.parent.name != feed_id:
        raise ValidationError("Feed directory differs from manifest identity")
    for field in ("from_version", "to_version", "record_count", "payload_bytes"):
        require_nonnegative_int(field, manifest[field])
    if manifest["to_version"] != manifest["from_version"] + 1:
        raise ValidationError("batch must advance exactly one version")
    if manifest["record_count"] > MAX_RECORDS or manifest["payload_bytes"] > MAX_PAYLOAD_BYTES:
        raise ValidationError("package limit exceeded")
    if manifest["depends_on_batch_id"] is not None:
        require_id("depends_on_batch_id", manifest["depends_on_batch_id"])
    payload_name = require_safe_filename("payload_path", manifest["payload_path"])
    if not isinstance(manifest["payload_sha256"], str) or not SHA256_RE.fullmatch(manifest["payload_sha256"]):
        raise ValidationError("invalid payload SHA-256")

    payload_path = path.parent / payload_name
    try:
        payload = payload_path.read_bytes()
    except OSError as exc:
        raise ValidationError(f"missing payload: {payload_path}") from exc
    if len(payload) != manifest["payload_bytes"]:
        raise ValidationError("payload size mismatch")
    if sha256(payload) != manifest["payload_sha256"]:
        raise ValidationError("payload SHA-256 mismatch")
    operations = []
    for number, line in enumerate(payload.splitlines(), 1):
        if not line.strip():
            raise ValidationError(f"blank payload line {number}")
        try:
            operations.append(validate_operation(json.loads(line)))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError(f"invalid payload JSON line {number}") from exc
    if len(operations) != manifest["record_count"]:
        raise ValidationError("record_count mismatch")
    identities = [(op["source_namespace"], op["record_id"]) for op in operations]
    if len(identities) != len(set(identities)):
        raise ValidationError("duplicate stable identity within batch")
    return manifest, operations


def validate_repository(root: Path | str) -> dict[str, int]:
    root = Path(root).resolve()
    schema_path = root / "schema" / "manifest.experimental-v0.schema.json"
    try:
        schema = json.loads(schema_path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError("manifest schema file is missing or invalid") from exc
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        raise ValidationError("manifest schema does not describe experimental/v0")

    manifests = sorted((root / "feeds").glob("*/*/manifest-*.json"))
    if not manifests:
        raise ValidationError("no Feed manifests found")
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], list[dict[str, Any]]]]] = defaultdict(list)
    referenced_payloads = set()
    operation_count = 0
    for path in manifests:
        manifest, operations = validate_manifest(path)
        groups[(manifest["feed_id"], manifest["generation"])].append((manifest, operations))
        referenced_payloads.add((path.parent / manifest["payload_path"]).resolve())
        operation_count += len(operations)
    actual_payloads = {path.resolve() for path in (root / "feeds").glob("*/*/*.jsonl")}
    if actual_payloads != referenced_payloads:
        raise ValidationError("orphaned or multiply referenced payload files")

    for identity, batches in groups.items():
        batches.sort(key=lambda item: item[0]["from_version"])
        cursor = 0
        previous_batch = None
        revisions: dict[tuple[str, str], int] = {}
        seen_batch_ids = set()
        for manifest, operations in batches:
            if manifest["batch_id"] in seen_batch_ids:
                raise ValidationError(f"duplicate batch_id for {identity}")
            if manifest["from_version"] != cursor:
                raise ValidationError(f"batch continuity error for {identity}")
            if manifest["depends_on_batch_id"] != previous_batch:
                raise ValidationError(f"batch dependency error for {identity}")
            for operation in operations:
                key = (operation["source_namespace"], operation["record_id"])
                prior = revisions.get(key, 0)
                if operation["revision"] <= prior:
                    raise ValidationError(f"non-monotonic revision for {key}")
                revisions[key] = operation["revision"]
            seen_batch_ids.add(manifest["batch_id"])
            previous_batch = manifest["batch_id"]
            cursor = manifest["to_version"]
    return {"feeds": len(groups), "batches": len(manifests), "operations": operation_count}


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    try:
        result = validate_repository(root)
    except ValidationError as exc:
        print(f"Feed validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps({"status": "valid", **result}, sort_keys=True))


if __name__ == "__main__":
    main()
