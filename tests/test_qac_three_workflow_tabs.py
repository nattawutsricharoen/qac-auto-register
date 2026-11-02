"""Regression tests: no workflow may steal another QAC browser tab."""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from app.qac_session import QAC_MODULES, _get_or_create_menu_page, _is_module_page

class FakePage:
    def __init__(self, tag='', url='http://159.228.251.234:8077/measure.html'):
        self.tag=tag
        self.url=url
        self.goto=AsyncMock()
    async def evaluate(self, query):
        return self.tag

class Tests(unittest.TestCase):
    def test_distinct_tags(self):
        tags=[m.window_tag for m in QAC_MODULES.values()]
        self.assertEqual(len(tags), 3)
        self.assertEqual(len(set(tags)), 3)

    def test_active_tabs_not_repurposed(self):
        pages=[FakePage(m.window_tag) for m in QAC_MODULES.values()]
        fresh=FakePage('', 'about:blank')
        ctx=MagicMock()
        ctx.pages=pages
        ctx.new_page=AsyncMock(return_value=fresh)
        with patch('app.qac_session._is_login_page', new=AsyncMock(return_value=False)), \
             patch('app.qac_session._has_visible', new=AsyncMock(return_value=False)):
            chosen=asyncio.run(_get_or_create_menu_page(ctx, 'http://159.228.251.234:8077/'))
        self.assertIs(chosen, fresh)
        fresh.goto.assert_awaited_once()
        for p in pages: p.goto.assert_not_awaited()

    def test_sample_never_claims_daily_tab(self):
        daily=FakePage(QAC_MODULES['daily_document'].window_tag)
        with patch('app.qac_session._is_login_page', new=AsyncMock(return_value=False)), \
             patch('app.qac_session._has_daily_document_ui', new=AsyncMock(return_value=True)):
            got=asyncio.run(_is_module_page(daily,QAC_MODULES['sample_register']))
        self.assertFalse(got)

    def test_sample_reuses_its_own_tag(self):
        sample=FakePage(QAC_MODULES['sample_register'].window_tag)
        with patch('app.qac_session._is_login_page', new=AsyncMock(return_value=False)), \
             patch('app.qac_session._has_daily_document_ui', new=AsyncMock(return_value=True)):
            got=asyncio.run(_is_module_page(sample,QAC_MODULES['sample_register']))
        self.assertTrue(got)

if __name__=='__main__': unittest.main()
