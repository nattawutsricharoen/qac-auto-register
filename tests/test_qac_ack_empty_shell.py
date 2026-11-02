"""Regression for 2026-10-21 QAC Complete! OK -> empty SweetAlert teardown."""
import asyncio
from types import SimpleNamespace
import pytest
import app.qac_interaction as q

class Page:
    async def wait_for_timeout(self, ms):
        return None

class Button:
    async def inner_text(self, timeout=800):
        return 'OK'
    async def scroll_into_view_if_needed(self, timeout=10000):
        return None
    async def click(self, **kwargs):
        return None

def state(kind, text='', confirm=False, cancel=False):
    return q.QACModalState(kind=kind, text=text, has_confirm=confirm, has_cancel=cancel)

def run_case(monkeypatch, states, expect_error=False):
    seen = iter(states)
    last = states[-1]
    async def inspect(page):
        return next(seen, last)
    async def install(page, progress):
        return None
    async def find(s, page):
        return Button()
    monkeypatch.setattr(q, 'inspect_visible_qac_modal', inspect)
    monkeypatch.setattr(q, 'install_native_dialog_guard', install)
    monkeypatch.setattr(q, '_find_affirmative_button', find)
    messages=[]
    async def execute():
        return await q.acknowledge_visible_modal(Page(), messages.append, wait_ms=100, max_rounds=4)
    if expect_error:
        with pytest.raises(RuntimeError, match='popup'):
            asyncio.run(execute())
    else:
        assert asyncio.run(execute()) == 2
        assert 'QAC ACK EMPTY SHELL CLEARED' in messages

def test_ack_empty_shell_disappears(monkeypatch):
    run_case(monkeypatch, [
        state('CONFIRM', 'Do you want to save it ?', True, True),
        state('INFO', 'Complete !', True),
        state('UNKNOWN'), state('UNKNOWN'), state('NONE')
    ])

def test_ack_unknown_empty_shell_persists_must_stop(monkeypatch):
    run_case(monkeypatch, [
        state('CONFIRM', 'Do you want to save it ?', True, True),
        state('INFO', 'Complete !', True),
        state('UNKNOWN')
    ], expect_error=True)

def test_unknown_before_success_must_stop(monkeypatch):
    run_case(monkeypatch, [state('UNKNOWN')], expect_error=True)
