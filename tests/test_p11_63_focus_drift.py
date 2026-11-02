import asyncio
import pytest
from app.sample_qac_navigation import select_sample_item, assert_sample_item_context

class Node:
    def __init__(self, page, kind): self.page, self.kind = page, kind
    @property
    def first(self): return self
    async def count(self): return 1
    async def is_visible(self): return self.page.current == '389500' if self.kind == 'panel' else True
    async def click(self): self.page.clicks += 1; self.page.current = '389500'
    async def wait_for(self, *, state, timeout): pass

class Page:
    def __init__(self, stolen=False): self.current='task'; self.clicks=0; self.stolen=stolen
    def locator(self, selector): return Node(self, 'panel' if selector.startswith('.fieldset') else 'step')
    async def evaluate(self, js, item):
        active = self.current
        if self.stolen and active == item:
            active = 'task'; self.current = 'task'; self.stolen = False
        return dict(panel=active == item, step=True,
                    selected=[active] if active != 'task' else [],
                    displayed=[active] if active != 'task' else [],
                    taskInfo=active == 'task', focusItem='')
    async def wait_for_timeout(self, ms): pass

def test_sample_navigation_recovers_focus_drift():
    page=Page(stolen=True)
    asyncio.run(select_sample_item(page,'389500',lambda _:None))
    assert page.current == '389500' and page.clicks >= 2

def test_sample_navigation_reselects_before_write():
    page=Page(); page.current='task'
    asyncio.run(assert_sample_item_context(page,'389500',lambda _:None))
    assert page.current == '389500'

class BrokenPage(Page):
    async def evaluate(self, js, item):
        return dict(panel=False,step=True,selected=[],displayed=[],taskInfo=True,focusItem='')

def test_sample_navigation_fails_closed_on_unrecoverable_focus():
    with pytest.raises(RuntimeError, match='CONTEXT LOST'):
        asyncio.run(select_sample_item(BrokenPage(),'389500',lambda _:None))
