#!/usr/bin/env python3
"""Read-only integrity checks for the published index and v1/v2 ZIP packages."""
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValidationError(f"non-finite JSON number: {value}")


def load_json(data):
    return json.loads(data, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def count(obj, field):
    value = obj.get(field)
    require(type(value) is int and value >= 0, f"invalid {field}")
    return value


def digest_matches(actual, expected, label):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
            f"invalid {label} SHA-256")
    require(actual == expected, f"{label} SHA-256 mismatch")


def validate_package(path, entry):
    require(not path.is_symlink(), "package must not be a symlink")
    with path.open("rb") as stream:
        digest_matches(hashlib.file_digest(stream, "sha256").hexdigest(),
                       entry.get("package_sha256"), "package")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "duplicate ZIP member")
        require({"manifest.json", "records.json"} <= set(names), "missing ZIP member")
        manifest = load_json(archive.read("manifest.json"))
        require(isinstance(manifest, dict), "manifest must be an object")
        version = {"tech-boundary-feed-package/v1": 1,
                   "tech-boundary-feed-package/v2": 2}.get(manifest.get("schema"))
        require(version is not None, "unsupported package schema")
        require(manifest.get("generator") == f"feed-pkg/v{version}", "generator mismatch")
        expected_names = {"manifest.json", "records.json"}
        if version == 2:
            expected_names.add("changes.json")
        require(set(names) == expected_names, "unexpected ZIP members")
        require(manifest.get("date") == entry["date"], "package date mismatch")
        records_bytes = archive.read("records.json")
        digest_matches(hashlib.sha256(records_bytes).hexdigest(),
                       manifest.get("records_sha256"), "records")
        records = load_json(records_bytes)
        require(isinstance(records, list) and all(isinstance(r, dict) for r in records),
                "records must be an object array")
        require(count(manifest, "record_count") == count(entry, "record_count") == len(records),
                "record_count mismatch")
        if version == 2:
            require(manifest.get("mode") == entry.get("mode") == "changes", "mode mismatch")
            changes = load_json(archive.read("changes.json"))
            require(isinstance(changes, list) and all(isinstance(c, dict) for c in changes),
                    "changes must be an object array")
            require(count(manifest, "change_count") == count(entry, "change_count") == len(changes),
                    "change_count mismatch")
            operations = Counter()
            change_ids = []
            for change in changes:
                op = change.get("op")
                require(op in ("ADD", "UPDATE", "DELETE"), "unknown change operation")
                identity = change.get("id")
                require(isinstance(identity, str) and bool(identity), "invalid change id")
                change_ids.append(identity)
                operations[op] += 1
            require(len(change_ids) == len(set(change_ids)), "duplicate change id")
            for op, field in (("ADD", "added"), ("UPDATE", "updated"), ("DELETE", "deleted")):
                require(count(manifest, field) == count(entry, field) == operations[op],
                        f"{field} mismatch")
            record_ids = [r.get("id") for r in records]
            require(all(isinstance(i, str) and bool(i) for i in record_ids), "invalid record id")
            require(len(record_ids) == len(set(record_ids)), "duplicate record id")
            # Only the ADD-only relation is evidenced by current published packages.
            # Do not invent UPDATE/DELETE replay, key hashing, or revision semantics.
            if not operations["UPDATE"] and not operations["DELETE"]:
                require(set(record_ids) == set(change_ids), "ADD record/change ids mismatch")
    return len(records), len(changes) if version == 2 else 0


def validate_repository(root):
    root = Path(root).resolve()
    try:
        index = load_json((root / "LATEST.json").read_bytes())
        require(isinstance(index, dict), "index must be an object")
        require(index.get("schema") == "tech-boundary-feed-index/v1", "unsupported index schema")
        require(index.get("generator") == "feed-pkg/v2", "unsupported index generator")
        packages = index.get("packages")
        require(isinstance(packages, list) and bool(packages), "packages must be a nonempty array")
        dates, files = [], set()
        totals = {"packages": 0, "records": 0, "changes": 0}
        for entry in packages:
            require(isinstance(entry, dict), "index entry must be an object")
            day = entry.get("date")
            require(isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day),
                    "invalid package date")
            date.fromisoformat(day)
            dates.append(day)
            filename = entry.get("file", f"{day}.zip")
            require(filename == f"{day}.zip", "package file must be the date ZIP filename")
            files.add(filename)
            records, changes = validate_package(root / "daily" / filename, entry)
            totals["packages"] += 1
            totals["records"] += records
            totals["changes"] += changes
        require(dates == sorted(set(dates)), "package dates must be unique and ordered")
        require(index.get("latest_date") == dates[-1], "latest_date mismatch")
        require({p.name for p in (root / "daily").glob("*.zip")} == files, "unindexed ZIP package")
        return totals
    except (OSError, ValueError, TypeError, KeyError, RecursionError, zipfile.BadZipFile,
            NotImplementedError, RuntimeError) as exc:
        raise ValidationError(str(exc)) from exc


if __name__ == "__main__":
    try:
        result = validate_repository(sys.argv[1] if len(sys.argv) > 1 else Path.cwd())
    except ValidationError as exc:
        print(f"Feed validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"status": "valid", **result}, sort_keys=True))
