import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from app.backups import create_backup, restore_backup
from app.common import Problem
from app.db import connect_db, init_db


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        conn=connect_db(self.root/'db.sqlite')
        init_db(conn)
        conn.execute("INSERT INTO metadata VALUES('test','保留')")
        conn.close()
        (self.root/'media').mkdir()
        (self.root/'media'/'photo.jpg').write_bytes(b'original-image')

    def test_restore_database_and_images(self):
        (self.root/'exports').mkdir()
        (self.root/'exports'/'invoice.xlsx').write_bytes(b'original-invoice-export')
        archive=create_backup(self.root/'db.sqlite',self.root/'media',self.root/'backups')
        restore_backup(archive,self.root/'restored')
        conn=connect_db(self.root/'restored'/'inventory.sqlite3')
        self.assertEqual(conn.execute('SELECT value FROM metadata').fetchone()[0],'保留')
        conn.close()
        self.assertEqual((self.root/'restored'/'media'/'photo.jpg').read_bytes(),b'original-image')
        self.assertEqual((self.root/'restored'/'exports'/'invoice.xlsx').read_bytes(),b'original-invoice-export')

    def test_traversal_rejected(self):
        archive=self.root/'evil.zip'
        with ZipFile(archive,'w') as z:
            z.writestr('../escape','bad')
        with self.assertRaises(Problem):
            restore_backup(archive,self.root/'restored')
        self.assertFalse((self.root/'escape').exists())

    def test_missing_source_not_successful(self):
        with self.assertRaises((Problem,FileNotFoundError)):
            create_backup(self.root/'missing.db',self.root/'media',self.root/'backups')

    def test_restore_refuses_nonempty_target(self):
        archive=create_backup(self.root/'db.sqlite',self.root/'media',self.root/'backups')
        target=self.root/'existing'
        target.mkdir()
        (target/'keep').write_text('keep')
        with self.assertRaises(Problem):
            restore_backup(archive,target)
