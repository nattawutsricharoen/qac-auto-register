import asyncio
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app import register_engine as eng

class CriticalIdentityTests(unittest.TestCase):
    def test_real_measure_document_labels(self):
        html = Path('/mnt/data/Pasted text(20261027-220409).txt').read_text(encoding='utf-8')
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        def after(label):
            for e in soup.select('h5'):
                if e.get_text(' ', strip=True).strip(' :.').lower() == label.lower():
                    sibling = e.find_next_sibling()
                    if sibling: return sibling.get_text(' ', strip=True)
            return ''
        self.assertEqual(after('Document No'), 'FOPI-M09-TS1-001-007-20')
        self.assertEqual(after('Production date'), '27-10-2026')
        self.assertEqual(after('Line'), 'TS1-Sub')

    def test_live_identity_normalizes_date(self):
        page=object()
        expected={'production_date':'2026-10-27','line':'TS1-Sub','document_no':'FOPI-M09-TS1-001-007-20','url':'http://qac/measure'}
        actual={'production_date':'27-10-2026','line':'TS1-Sub','shift':'','document_no':expected['document_no'],'url':expected['url']}
        with patch.object(eng, 'read_document_identity', new=AsyncMock(return_value=actual)):
            asyncio.run(eng._assert_document_identity(page,expected))

    def test_wrong_document_blocks_write(self):
        expected={'production_date':'2026-10-27','line':'TS1-Sub','document_no':'A'}
        actual={'production_date':'27-10-2026','line':'TS1-Sub','document_no':'B'}
        with patch.object(eng,'read_document_identity',new=AsyncMock(return_value=actual)):
            with self.assertRaisesRegex(RuntimeError,'DOCUMENT_CHANGED'):
                asyncio.run(eng._assert_document_identity(object(),expected))

    def test_no_identity_blocks_write(self):
        with self.assertRaisesRegex(RuntimeError,'MISSING_DOCUMENT_IDENTITY'):
            asyncio.run(eng._assert_document_identity(object(),{}))

class SerialWorkerLockTests(unittest.TestCase):
    def test_same_endpoint_is_serialized(self):
        from app.browser_operation_lock import _serialize_qac_browser_run
        active=0; peak=0; state=threading.Lock()
        class Worker:
            cdp_url='http://127.0.0.1:9222'
            def run(self):
                nonlocal active,peak
                with state:
                    active+=1;peak=max(peak,active)
                time.sleep(.035)
                with state: active-=1
        w=Worker()
        guarded=_serialize_qac_browser_run(Worker.run)
        threads=[threading.Thread(target=guarded,args=(w,)) for _ in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(peak,1)

if __name__=='__main__': unittest.main()
