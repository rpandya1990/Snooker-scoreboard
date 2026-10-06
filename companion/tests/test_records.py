import tempfile
import unittest
from pathlib import Path
from ai_scoring.dao.jsonl import JsonlSessionStore, IdentityConflict, StorageFault

class RecordsTests(unittest.TestCase):
    def test_duplicate_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlSessionStore(directory, 's')
            record = {'id': 'one', 'type': 'test', 'payload': {'x': 1}}
            self.assertEqual(store.append(record), store.append(record))
            with self.assertRaises(IdentityConflict):
                store.append(dict(record, payload={'x': 2}))
            self.assertEqual(len(store.records), 1)
            store.close()

    def test_partial_recovery_and_complete_fault(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlSessionStore(directory, 's')
            store.append({'id': 'one'})
            path = store.path
            store.close()
            with path.open('ab') as stream:
                stream.write(b'{"id":')
            store = JsonlSessionStore(directory, 's')
            self.assertEqual(len(store.records), 1)
            self.assertTrue(path.read_bytes().endswith(b'\n'))
            store.close()
            with path.open('ab') as stream:
                stream.write(b'{bad}\n')
            with self.assertRaises(StorageFault):
                JsonlSessionStore(directory, 's')

    def test_second_writer_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlSessionStore(directory, 's')
            with self.assertRaises(StorageFault):
                JsonlSessionStore(directory, 's')
            store.close()
    def test_write_failure_poisoning(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            store=JsonlSessionStore(directory,'s')
            with patch('ai_scoring.dao.jsonl.os.fsync',side_effect=OSError('disk')):
                with self.assertRaises(StorageFault):
                    store.append({'id':'one'})
            with self.assertRaises(StorageFault):
                store.append({'id':'two'})
            store.close()
    def test_untrusted_session_and_log_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'data'
            outside=Path(directory)/'outside'
            root.mkdir()
            outside.mkdir()
            (root/'sessions').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(StorageFault):
                JsonlSessionStore(root,'s')
            self.assertFalse((outside/'s').exists())
            (root/'sessions').unlink()
            (root/'sessions').mkdir()
            (root/'sessions'/'s').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(StorageFault):
                JsonlSessionStore(root,'s')
            self.assertFalse((outside/'session.jsonl').exists())
            (root/'sessions'/'s').unlink()
            (root/'sessions'/'s').mkdir()
            target=outside/'secret'
            target.write_bytes(b'unchanged')
            (root/'sessions'/'s'/'session.jsonl').symlink_to(target)
            with self.assertRaises(StorageFault):
                JsonlSessionStore(root,'s')
            self.assertEqual(target.read_bytes(),b'unchanged')
    def test_session_permissions_and_explicit_root_alias(self):
        import stat
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'data'
            root.mkdir()
            alias=Path(directory)/'explicit-root'
            alias.symlink_to(root,target_is_directory=True)
            store=JsonlSessionStore(alias,'s')
            self.assertTrue(store.path.is_relative_to(root.resolve()))
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(store.path.parent.stat().st_mode),0o700)
            store.close()
