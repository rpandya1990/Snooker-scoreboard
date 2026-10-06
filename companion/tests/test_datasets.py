import hashlib
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from ai_scoring.services.datasets import DatasetStore, DatasetError

class DatasetTests(unittest.TestCase):
    def fixture(self, root, session='capture-one', alignment='estimated'):
        folder = root / session
        (folder / 'video').mkdir(parents=True)
        video = folder / 'video' / 'one.mkv'
        video.write_bytes(b'recorded-footage')
        records = [
            {'id':'session','type':'session_opened','timestamp':'2026-10-05T00:00:00+00:00','payload':{'sessionId':session}},
            {'id':'asset','type':'segment_closed','timestamp':'2026-10-05T00:01:00+00:00','payload':{
                'assetId':'asset', 'relativePath':'video/one.mkv', 'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
                'sizeBytes':len(video.read_bytes()),'mediaStart':0,'mediaDuration':60,'captureStartUtc':'2026-10-05T00:00:00+00:00',
                'alignmentStatus':alignment,'utcUncertaintyMs':100}},
            {'id':'entry','type':'event','timestamp':'2026-10-05T00:00:10+00:00','payload':{'event':{
                'type':'break_committed','entryId':'entry','frameId':'frame','runId':'run',
                'inputStartedAt':'2026-10-05T00:00:10+00:00','committedAt':'2026-10-05T00:00:12+00:00',
                'submittedPoints':15,'predictionId':'original-prediction'}}}]
        (folder/'session.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        return folder
    def test_import_preserves_source_and_duplicate_assets_cannot_cross_cohort(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=self.fixture(root); before=(source/'session.jsonl').read_bytes()
            store=DatasetStore(root/'datasets'); first=store.import_session(source)
            store.assign_cohort(first,'tuning')
            second=store.import_session(source)
            with self.assertRaises(DatasetError): store.assign_cohort(second,'held-out')
            self.assertEqual((source/'session.jsonl').read_bytes(),before)
            self.assertEqual(store.metadata(first)['cohort'],'tuning')
    def test_traversal_and_invalid_hash_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=self.fixture(root); path=source/'session.jsonl'
            records=[json.loads(line) for line in path.read_text().splitlines()]
            records[1]['payload']['relativePath']='../outside.mkv'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            with self.assertRaises(DatasetError): DatasetStore(root/'datasets').import_session(source)
    def test_unknown_alignment_imported_but_not_review_eligible(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=self.fixture(root,alignment='unknown'); store=DatasetStore(root/'datasets')
            dataset=store.import_session(source)
            self.assertFalse(store.metadata(dataset)['evidenceComplete'])
            self.assertIn('timeline_alignment_unknown',store.metadata(dataset)['qualityReasons'])

    def test_symlink_assets_and_active_writer_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=self.fixture(root); video=source/'video/one.mkv'
            outside=root/'outside.mkv'; video.rename(outside); video.symlink_to(outside)
            with self.assertRaises(DatasetError): DatasetStore(root/'datasets').import_session(source)
            video.unlink(); outside.rename(video)
            with (source/'session.jsonl').open('a') as writer:
                fcntl.flock(writer,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(DatasetError): DatasetStore(root/'datasets').import_session(source)
    def test_checksum_missing_invalid_timestamp_and_registry_partial_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); source=self.fixture(root); path=source/'session.jsonl'
            records=[json.loads(x) for x in path.read_text().splitlines()]
            records[1]['payload'].pop('sha256')
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            store=DatasetStore(root/'datasets')
            with self.assertRaises(DatasetError): store.import_session(source)
            records[1]['payload']['sha256']=hashlib.sha256((source/'video/one.mkv').read_bytes()).hexdigest()
            records[0]['timestamp']='not-a-date'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            with self.assertRaises(DatasetError): store.import_session(source)
    def test_amended_session_name_same_asset_cannot_reassign_cohort(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); store=DatasetStore(root/'datasets')
            first=store.import_session(self.fixture(root)); store.assign_cohort(first,'held-out')
            second=store.import_session(self.fixture(root,'renamed-capture'))
            with self.assertRaises(DatasetError): store.assign_cohort(second,'tuning')
            with store.registry.open('a') as stream: stream.write('{')
            with self.assertRaises(DatasetError): store.metadata(first)
    def test_review_must_follow_locked_cohort_and_blind_export_has_no_answers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); store=DatasetStore(root/'datasets'); dataset=store.import_session(self.fixture(root))
            review={'entryId':'entry','reviewer':'person','independent':True,'eligible':True,'evidenceSufficient':True,'actualPoints':8}
            with self.assertRaises(DatasetError): store.review(dataset,review)
            store.assign_cohort(dataset,'held-out'); store.review(dataset,review)
            blind=json.dumps(store.blind_entries(dataset))
            self.assertNotIn('submittedPoints',blind); self.assertNotIn('predictionId',blind); self.assertNotIn('actualPoints',blind)
            self.assertEqual(store.reviews(dataset)[0]['payload']['actualPoints'],8)

    def test_private_dataset_files_and_fixed_metadata_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve(); store=DatasetStore(root/'datasets'); dataset=store.import_session(self.fixture(root))
            folder=store.path(dataset)
            self.assertEqual(folder.stat().st_mode & 0o777,0o700)
            for path in (folder/'session.jsonl',folder/'dataset.json',folder/'video/one.mkv',store.registry):
                self.assertEqual(path.stat().st_mode & 0o777,0o600)
            metadata=folder/'dataset.json'; other=root/'metadata.json'; metadata.rename(other); metadata.symlink_to(other)
            with self.assertRaises(DatasetError): store.metadata(dataset)
