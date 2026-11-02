import asyncio
from app.sample_register import _activate_sample_item

class FakeNode:
    def __init__(self, *, visible=False, on_click=None):
        self.visible = visible
        self.on_click = on_click
        self.clicks = 0
    @property
    def first(self): return self
    async def count(self): return 1
    async def is_visible(self): return self.visible
    async def click(self):
        self.clicks += 1
        if self.on_click: self.on_click()
    async def wait_for(self, *, state, timeout):
        assert state == 'visible'
        assert timeout == 5000
        if not self.visible: raise TimeoutError()

class FakePage:
    def __init__(self, item, active):
        self.item=item
        self.panel=FakeNode(visible=active)
        self.step=FakeNode(visible=True, on_click=lambda: setattr(self.panel,'visible',True))
    def locator(self, query):
        assert f'data-item="{self.item}"' in query
        return self.panel if query.startswith('.fieldset') else self.step


def test_activates_hidden_sample_type_working_panel():
    page=FakePage('389496',False)
    events=[]
    selected=asyncio.run(_activate_sample_item(page,'389496',events.append))
    assert selected is page.panel
    assert page.step.clicks==1
    assert any('SAMPLE ITEM ACTIVATE' in x for x in events)


def test_skips_click_if_qac_auto_advanced_to_item():
    page=FakePage('389496',True)
    asyncio.run(_activate_sample_item(page,'389496',lambda m: None))
    assert page.step.clicks==0


def test_rejects_bad_item_identity():
    page=FakePage('389496',True)
    try:
        asyncio.run(_activate_sample_item(page,'other',lambda m: None))
        assert False
    except RuntimeError as exc:
        assert 'ID' in str(exc)
