"""Offline safety regressions: a tab index never proves document identity."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from app import register_engine as engine

IDENTITY = {
    'production_date': '2026-10-27', 'line': 'TS1-Sub',
    'shift': 'DAY', 'document_no': '2026-10-27-A',
    'url': 'http://qac.example/document/1',
}

class WriteGuardTest(unittest.TestCase):
    def test_matching_identity(self):
        with patch.object(engine, 'read_document_identity', new=AsyncMock(return_value=dict(IDENTITY))):
            self.assertEqual(asyncio.run(engine._assert_document_identity(object(), dict(IDENTITY))), IDENTITY)

    def test_swapped_document_rejected(self):
        other = dict(IDENTITY, document_no='DIFFERENT')
        with patch.object(engine, 'read_document_identity', new=AsyncMock(return_value=other)):
            with self.assertRaisesRegex(RuntimeError, 'DOCUMENT_CHANGED'):
                asyncio.run(engine._assert_document_identity(object(), dict(IDENTITY)))

    def test_missing_expected_identity_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'MISSING_DOCUMENT_IDENTITY'):
            asyncio.run(engine._assert_document_identity(object(), None))

    def test_missing_observed_field_rejected(self):
        with patch.object(engine, 'read_document_identity', new=AsyncMock(return_value=dict(IDENTITY, document_no=''))):
            with self.assertRaisesRegex(RuntimeError, 'DOCUMENT_CHANGED'):
                asyncio.run(engine._assert_document_identity(object(), dict(IDENTITY)))

    def test_ambiguous_results_fail_closed(self):
        class Locator:
            async def count(self): return 0
        class Page:
            def locator(self, selector): return Locator()
            async def wait_for_timeout(self, ms): pass
        with patch.object(engine, '_result_ids', new=AsyncMock(return_value={'9','10'})):
            with self.assertRaisesRegex(RuntimeError, 'AMBIGUOUS_SAVE_RESULT'):
                asyncio.run(engine._wait_complete(Page(), set(), 0))

    def test_single_result_accepted(self):
        class Locator:
            async def count(self): return 0
        class Page:
            def locator(self, selector): return Locator()
            async def wait_for_timeout(self, ms): pass
        with patch.object(engine, '_result_ids', new=AsyncMock(return_value={'10'})):
            self.assertEqual(asyncio.run(engine._wait_complete(Page(), set(), 0)), '10')

if __name__ == '__main__': unittest.main()
