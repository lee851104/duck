import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from app.cloud_excel import CloudExcelSync
from app.common import Problem
from app.storage import LocalStorage
import test_excel_sync


class CloudExcelTest(unittest.TestCase):
    rows = test_excel_sync.ExcelSyncTest.rows
    def setUp(self):
        test_excel_sync.ExcelSyncTest.setUp(self)
        self.local_sync = self.sync
        self.cloud_sync = CloudExcelSync(self.app)

    def test_private_chunks_restore_exact_template_and_detect_corruption(self):
        content = self.template.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        storage = LocalStorage(self.root/'objects')
        keys = [f'templates/{digest}/000.part', f'templates/{digest}/001.part']
        storage.put(keys[0], content[:100])
        storage.put(keys[1], content[100:])
        marker = json.dumps({'sha256':digest,'chunks':keys})
        self.conn.execute("INSERT INTO metadata VALUES('excel_template',?)", (marker,))
        with self.app.app_context(), patch('app.cloud_excel.get_storage', return_value=storage):
            restored = self.cloud_sync.template()
            self.assertEqual(restored.read_bytes(), content)
            restored.unlink()
            storage.path(keys[1]).write_bytes(b'broken')
            with self.assertRaises(Problem):
                self.cloud_sync.template()
            self.assertFalse(restored.exists())

    def test_bundle_regenerates_after_edit_and_hides_server_paths(self):
        with patch.object(self.cloud_sync, 'snapshot', side_effect=self.local_sync.snapshot), patch.object(self.cloud_sync, 'template', return_value=self.template):
            first = self.cloud_sync.bundle()
            with ZipFile(first) as archive:
                self.assertEqual(set(archive.namelist()), {'庫存管理.xlsx','商品價目表.xlsx','發票系統.xlsx','snapshot.json'})
            self.conn.execute("UPDATE products SET price='88'")
            self.cloud_sync.request()
            state = self.cloud_sync.status()
            self.assertFalse(state['pending'])
            self.assertTrue(state['stale'])
            self.assertNotIn('folder', state['last'])
            second = self.cloud_sync.bundle()
            self.assertNotEqual(first, second)
            self.assertFalse(first.exists())
            self.assertEqual(self.rows(second.parent, 'invoice')[1][3], 88)
            self.assertEqual(len(list(self.cloud_sync.root.glob('*/snapshot.json'))), 1)

    def test_cloud_downloads_require_authentication(self):
        client = self.app.test_client()
        self.assertEqual(client.get('/api/excel-backup/download').status_code,401)

    def test_bundle_response_streams_without_content_length(self):
        from app.cloud_excel import stream_download
        path = self.root/'download.zip'
        path.write_bytes(b'Z'*(2*64*1024+19))
        response = stream_download(path, '每日Excel備援.zip')
        self.assertTrue(response.is_streamed)
        self.assertNotIn('Content-Length', response.headers)
        chunks = list(response.response)
        self.assertEqual([len(c) for c in chunks], [65536,65536,19])
        self.assertEqual(b''.join(chunks), path.read_bytes())
        response.close()
