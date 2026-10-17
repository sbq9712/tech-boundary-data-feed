import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.validate_feed import ValidationError, load_json, validate_repository


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'daily').mkdir()
        self.entries = []
        self.members = {}
        for day, version in [('2026-09-27', 1), ('2026-09-30', 2)]:
            records = json.dumps([{'t': 'Fixture', **({'id': 'a'} if version == 2 else {})}]).encode()
            manifest = {'schema': f'tech-boundary-feed-package/v{version}',
                        'generator': f'feed-pkg/v{version}', 'date': day,
                        'record_count': 1, 'records_sha256': hashlib.sha256(records).hexdigest()}
            entry = {'date': day, 'record_count': 1}
            members = {'records.json': records}
            if version == 2:
                counters = {'mode': 'changes', 'change_count': 1, 'added': 1, 'updated': 0, 'deleted': 0}
                manifest.update(counters)
                entry.update(counters, file=f'{day}.zip')
                members['changes.json'] = json.dumps([{'op': 'ADD', 'id': 'a', 'key': 'Fixture', 'v': 1}]).encode()
            members['manifest.json'] = json.dumps(manifest).encode()
            self.entries.append(entry)
            self.members[day] = members
            self.repack(day)
        self.index = {'schema': 'tech-boundary-feed-index/v1', 'generator': 'feed-pkg/v2',
                      'packages': self.entries, 'latest_date': '2026-09-30'}
        self.write_index()

    def write_index(self):
        (self.root / 'LATEST.json').write_text(json.dumps(self.index))

    def repack(self, day='2026-09-30'):
        path = self.root / 'daily' / f'{day}.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.members[day].items():
                archive.writestr(name, data)
        next(e for e in self.entries if e['date'] == day)['package_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def mutate_manifest(self, **values):
        members = self.members['2026-09-30']
        manifest = json.loads(members['manifest.json'])
        manifest.update(values)
        members['manifest.json'] = json.dumps(manifest).encode()
        self.repack()
        self.write_index()

    def rejects(self, message):
        with self.assertRaisesRegex(ValidationError, message):
            validate_repository(self.root)

    def test_mixed_versions_and_legacy_filename(self):
        self.assertEqual(validate_repository(self.root), {'packages': 2, 'records': 2, 'changes': 1})

    def test_package_hash_tampering(self):
        with (self.root / 'daily/2026-09-30.zip').open('ab') as stream:
            stream.write(b'tampered')
        self.rejects('package SHA-256 mismatch')

    def test_records_hash_after_resealing_zip(self):
        self.members['2026-09-30']['records.json'] = b'[]'
        self.repack()
        self.write_index()
        self.rejects('records SHA-256 mismatch')

    def test_counts_reject_wrong_values_and_booleans(self):
        self.mutate_manifest(record_count=2)
        self.rejects('record_count mismatch')
        self.mutate_manifest(record_count=True)
        self.rejects('invalid record_count')

    def test_changes_counter_and_identity(self):
        self.mutate_manifest(added=0)
        self.rejects('added mismatch')
        self.mutate_manifest(added=1)
        self.members['2026-09-30']['changes.json'] = b'[{"op":"ADD","id":"wrong"}]'
        self.repack()
        self.write_index()
        self.rejects('ids mismatch')

    def test_unsafe_filename(self):
        self.entries[-1]['file'] = '../2026-09-30.zip'
        self.write_index()
        self.rejects('date ZIP filename')

    def test_index_order_duplicates_and_latest(self):
        self.index['latest_date'] = '2026-09-29'
        self.write_index()
        self.rejects('latest_date mismatch')
        self.index['latest_date'] = '2026-09-30'
        self.entries.reverse()
        self.write_index()
        self.rejects('unique and ordered')
        self.entries.reverse()
        self.entries.append(self.entries[-1].copy())
        self.write_index()
        self.rejects('unique and ordered')

    def test_missing_and_unindexed_packages(self):
        extra = self.root / 'daily/2026-10-01.zip'
        extra.write_bytes(b'unindexed')
        self.rejects('unindexed')
        extra.unlink()
        (self.root / 'daily/2026-09-30.zip').unlink()
        self.rejects('No such file')

    def test_unknown_schema_and_zip_paths(self):
        self.mutate_manifest(schema='experimental/v0')
        self.rejects('unsupported package schema')
        self.mutate_manifest(schema='tech-boundary-feed-package/v2')
        self.members['2026-09-30']['../unexpected.json'] = b'{}'
        self.repack()
        self.write_index()
        self.rejects('unexpected ZIP members')

    def test_duplicate_zip_member(self):
        path = self.root / 'daily/2026-09-30.zip'
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            with zipfile.ZipFile(path, 'a') as archive:
                archive.writestr('manifest.json', b'{}')
        self.entries[-1]['package_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_index()
        self.rejects('duplicate ZIP member')

    def test_strict_json(self):
        for raw in [b'{"id":1,"id":2}', b'[NaN]', b'[Infinity]']:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                load_json(raw)

    def test_duplicate_and_unknown_changes(self):
        self.members['2026-09-30']['changes.json'] = b'[{"op":"upsert","id":"a"}]'
        self.repack()
        self.write_index()
        self.rejects('unknown change operation')
        self.members['2026-09-30']['changes.json'] = b'[{"op":"ADD","id":"a"},{"op":"ADD","id":"a"}]'
        self.repack()
        self.write_index()
        self.mutate_manifest(change_count=2)
        self.entries[-1]['change_count'] = 2
        self.write_index()
        self.rejects('duplicate change id')


if __name__ == '__main__':
    unittest.main()
