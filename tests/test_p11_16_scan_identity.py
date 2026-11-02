import unittest
from unittest.mock import AsyncMock
from app.daily_slot_schema import verify_daily_measure_identity

class MeasureIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_expected_measure_name(self):
        page=type('Page', (), {'evaluate': AsyncMock(return_value={'text':'Task Information Document No. FOPI-X Document name: TS1-Sub_S91_Interlock & master check Production date: 22-09-2026', 'itemCount':36})})()
        got=await verify_daily_measure_identity(page, {'document_name':'TS1-Sub_S91_Interlock & master check','document_no':'FOPI-X'})
        self.assertEqual(got['itemCount'],36)
    async def test_wrong_document_prevents_write(self):
        page=type('Page', (), {'evaluate': AsyncMock(return_value={'text':'Document name: Wrong sheet', 'itemCount':36})})()
        with self.assertRaisesRegex(RuntimeError, 'IDENTITY MISMATCH'):
            await verify_daily_measure_identity(page, {'document_name':'TS1-Sub_S91_Interlock & master check'})
    async def test_no_measure_items_prevents_write(self):
        page=type('Page', (), {'evaluate': AsyncMock(return_value={'text':'Other page', 'itemCount':0})})()
        with self.assertRaisesRegex(RuntimeError, 'IDENTITY UNKNOWN'):
            await verify_daily_measure_identity(page, {'document_name':'Anything'})

if __name__ == '__main__': unittest.main()
