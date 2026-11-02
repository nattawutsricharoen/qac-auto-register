import asyncio
from unittest.mock import AsyncMock, patch
from app.qac_sync import sync_events_incremental

class CacheStub:
    path = 'test.db'
    def __init__(self):
        self.reconciled = None
        self.existing = [{'result_id': 'old', 'topic_value': 'a', 'category_value': 'b', 'start': '1'}]
    def get_events(self, key): return list(self.existing)
    def reconcile_result_ids(self, key, ids):
        self.reconciled = set(ids)
        self.existing = [x for x in self.existing if x['result_id'] in ids]
        return 0
    def upsert_events(self, *a): pass
    def touch_document(self, *a, **kw): pass
    def cleanup_keep_today_yesterday(self): pass

def run_case(sequence):
    cache = CacheStub()
    async def fake_ids(_): return sequence.pop(0)
    ident = {'production_date':'2026-10-13','line':'TS1','shift':'1','document_no':'x','url':'a'}
    with patch('app.qac_sync.read_document_identity', AsyncMock(return_value=ident)), \
         patch('app.qac_sync.timeline_result_ids', side_effect=fake_ids), \
         patch('app.qac_sync.visible_form_events', AsyncMock(return_value=[])), \
         patch('app.qac_sync.read_result_detail', AsyncMock(return_value=None)), \
         patch('app.qac_sync.asyncio.sleep', AsyncMock()):
        result = asyncio.run(sync_events_incremental(object(), cache=cache))
    return cache, result

def test_transient_empty_recovers_without_purging():
    c,r=run_case([[],['old']])
    assert c.reconciled == {'old'}
    assert len(r[2])==1

def test_confirmed_empty_still_purges_deleted_qac_results():
    c,r=run_case([[],[]])
    assert c.reconciled == set()
    assert r[2]==[]
