import asyncio
from app.sample_qac_navigation import reselect_after_sample_save

class Node:
    def __init__(self, visible=False, on_click=None):
        self.visible=visible; self.on_click=on_click; self.clicks=0
    @property
    def first(self): return self
    async def count(self): return 1
    async def is_visible(self): return self.visible
    async def click(self):
        self.clicks+=1
        if self.on_click: self.on_click()
    async def wait_for(self, *, state, timeout):
        assert state == 'visible' and timeout == 5000
        assert self.visible

class Page:
    def __init__(self, in_task_info=True):
        self.panel=Node(visible=not in_task_info)
        self.info=Node(visible=in_task_info)
        def navigate():
            self.info.visible=False; self.panel.visible=True
        self.step=Node(visible=True,on_click=navigate)
        self.waits=0
    def locator(self, selector):
        if selector=='.task-infomation.fieldset': return self.info
        if selector=='.fieldset[data-item="389499"]': return self.panel
        if selector=='.f1-step[data-item="389499"]': return self.step
        raise AssertionError(selector)
    async def wait_for_timeout(self, millis):
        self.waits+=1


def test_sample_reselects_from_task_information_after_save():
    page=Page(True); events=[]
    panel=asyncio.run(reselect_after_sample_save(page,'389499',events.append))
    assert panel is page.panel and page.step.clicks==1
    assert any('RETURNED TASK INFO' in x for x in events)


def test_sample_forces_reselection_even_when_previous_panel_visible():
    page=Page(False)
    asyncio.run(reselect_after_sample_save(page,'389499',lambda _:None))
    assert page.step.clicks==1
