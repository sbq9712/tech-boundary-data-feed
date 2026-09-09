from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_feed import (
    PUBLIC_FIELDS, ValidationError, canonical_bytes, sha256, validate_repository,
)


REPOSITORY = Path(__file__).parents[1]
FEED_PATH = Path("feeds/tech-boundary-synthetic/test-v0")


class ValidatorTests(unittest.TestCase):
    def copy_repository(self):
        # Keep the copy beside the repository so copytree cannot recurse into it.
        temporary = tempfile.TemporaryDirectory(dir=REPOSITORY.parent)
        target = Path(temporary.name) / "repository"
        shutil.copytree(REPOSITORY, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return temporary, target

    def test_current_synthetic_feed_is_valid(self):
        self.assertEqual(
            validate_repository(REPOSITORY),
            {"feeds": 1, "batches": 2, "operations": 5},
        )

    def test_sha_tampering_is_rejected(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        payload = root / FEED_PATH / "batch-synthetic-001.jsonl"
        payload.write_bytes(payload.read_bytes() + b"tampered\n")
        with self.assertRaisesRegex(ValidationError, "size mismatch|SHA-256 mismatch"):
            validate_repository(root)

    def test_batch_continuity_is_rejected(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / FEED_PATH / "manifest-synthetic-002.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["from_version"] = 4
        manifest["to_version"] = 5
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, "continuity"):
            validate_repository(root)

    def test_unsafe_path_and_production_identity_are_rejected(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        manifest_path = root / FEED_PATH / "manifest-synthetic-001.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["payload_path"] = "../private.jsonl"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, "safe filename"):
            validate_repository(root)

        manifest["payload_path"] = "batch-synthetic-001.jsonl"
        manifest["feed_id"] = "tech-boundary-production"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, "production Feed identities"):
            validate_repository(root)

    def mutate_payload_and_reseal_manifest(self, root, mutate):
        payload_path = root / FEED_PATH / "batch-synthetic-001.jsonl"
        operations = [json.loads(line) for line in payload_path.read_text().splitlines()]
        mutate(operations[0]["record"])
        payload = b"".join(
            json.dumps(operation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for operation in operations
        )
        payload_path.write_bytes(payload)
        manifest_path = root / FEED_PATH / "manifest-synthetic-001.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["payload_bytes"] = len(payload)
        manifest["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        manifest_path.write_text(json.dumps(manifest))

    def test_forbidden_fields_and_secret_markers_are_rejected(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        self.mutate_payload_and_reseal_manifest(root, lambda record: record.update(prompt="private"))
        with self.assertRaisesRegex(ValidationError, "forbidden field"):
            validate_repository(root)

        temporary2, root2 = self.copy_repository()
        self.addCleanup(temporary2.cleanup)
        self.mutate_payload_and_reseal_manifest(
            root2, lambda record: record.update(content="github_pat_synthetic_marker")
        )
        with self.assertRaisesRegex(ValidationError, "secret-like"):
            validate_repository(root2)

    def test_nested_allowlist_and_text_limit_are_fail_closed(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        self.mutate_payload_and_reseal_manifest(
            root, lambda record: record["parameters"].update(access_token="hidden")
        )
        with self.assertRaisesRegex(ValidationError, "unapproved public fields at parameters"):
            validate_repository(root)

        temporary2, root2 = self.copy_repository()
        self.addCleanup(temporary2.cleanup)
        self.mutate_payload_and_reseal_manifest(
            root2, lambda record: record.update(summary="x" * 2_000_001)
        )
        with self.assertRaisesRegex(ValidationError, "bounded string"):
            validate_repository(root2)

    def test_baseline_identity_is_stable_across_batches(self):
        temporary, root = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        payload_path = root / FEED_PATH / "batch-synthetic-002.jsonl"
        operations = [json.loads(line) for line in payload_path.read_text().splitlines()]
        operation = next(item for item in operations if item["record_id"] == "A")
        operation.pop("baseline_record_id")
        operation["record"].pop("baseline_record_id")
        projected = {key: operation["record"].get(key) for key in sorted(PUBLIC_FIELDS)}
        operation["content_sha256"] = sha256(canonical_bytes(projected))
        payload = b"".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            for item in operations
        )
        payload_path.write_bytes(payload)
        manifest_path = root / FEED_PATH / "manifest-synthetic-002.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["payload_bytes"] = len(payload)
        manifest["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValidationError, "baseline_record_id changed or disappeared"):
            validate_repository(root)


if __name__ == "__main__":
    unittest.main()
