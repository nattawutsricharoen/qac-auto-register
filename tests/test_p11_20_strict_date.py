import unittest
from unittest.mock import AsyncMock
from app.daily_slot_schema import _normalise_qac_date, verify_daily_measure_identity

class StrictDateTests(unittest.IsolatedAsyncioTestCase):
    def test_date_formats(self):
        self.assertEqual(_normalise_qac_date('22-10-2026'),'2026-10-22')
        self.assertEqual(_normalise_qac_date('21-Oct-26'),'2026-10-21')
        self.assertEqual(_normalise_qac_date('unknown'),'')

    async def test_wrong_day_fails_closed(self):
        page=type('Page',(),{'evaluate':AsyncMock(return_value={'text':'Document No. DOC-1 Document name: TEST','productionDate':'22-10-2026','itemCount':6})})()
        with self.assertRaisesRegex(RuntimeError,'DAILY PRODUCTION DATE MISMATCH'):
            await verify_daily_measure_identity(page,{'document_name':'TEST','document_no':'DOC-1','_daily_production_date':'2026-10-21'})

    async def test_correct_day_passes(self):
        page=type('Page',(),{'evaluate':AsyncMock(return_value={'text':'Document No. DOC-1 Document name: TEST','productionDate':'21-10-2026','itemCount':6})})()
        await verify_daily_measure_identity(page,{'document_name':'TEST','document_no':'DOC-1','_daily_production_date':'2026-10-21'})

    async def test_missing_date_fails_closed(self):
        page=type('Page',(),{'evaluate':AsyncMock(return_value={'text':'Document No. DOC-1 Document name: TEST','productionDate':'','itemCount':6})})()
        with self.assertRaisesRegex(RuntimeError,'DAILY PRODUCTION DATE UNKNOWN'):
            await verify_daily_measure_identity(page,{'document_name':'TEST','document_no':'DOC-1','_daily_production_date':'2026-10-21'})
