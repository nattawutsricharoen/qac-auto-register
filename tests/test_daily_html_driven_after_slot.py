"""Offline regression for HTML-driven decisions after each selected QAC slot."""
import asyncio
import pytest
from app.daily_document_register import _inspect_after_slot

class FakeFieldset:
    def __init__(self, values):
        self.values = values
        self.calls = 0
    async def evaluate(self, script):
        assert 'tr[data-result-no]' in script
        val = self.values[min(self.calls, len(self.values)-1)]
        self.calls += 1
        return val

def state(*, save=0, ok=1, ng=1, item='411400', visible=True):
    return {'item': item, 'visible': visible, 'save': save, 'ok': ok, 'ng': ng, 'results': []}

def check(values, remaining):
    logs=[]
    field=FakeFieldset(values)
    ret=asyncio.run(_inspect_after_slot(field, item_id='411400', slot_no=5-remaining,
                                        remaining=remaining, progress=logs.append))
    return ret, logs, field.calls

def test_next_slot_when_save_absent():
    val, logs, calls=check([state(save=0)], remaining=4)
    assert calls == 1 and 'CHECK_NEXT_SLOT' in logs[0]

def test_save_only_after_last_slot():
    val, logs, calls=check([state(save=1, ok=0, ng=0)], remaining=0)
    assert calls == 1 and 'next=SAVE' in logs[0]

def test_early_save_does_not_skip_remaining_selections():
    val, logs, calls=check([state(save=1)], remaining=2)
    assert 'CHECK_NEXT_SLOT' in logs[0]

def test_missing_item_fails_closed():
    with pytest.raises(RuntimeError, match='DAILY ITEM LOST'):
        check([state(item='wrong')], remaining=0)

def test_multiple_save_buttons_fails_closed():
    with pytest.raises(RuntimeError, match='DAILY SAVE AMBIGUOUS'):
        check([state(save=2)], remaining=0)
