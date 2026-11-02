"""Static navigation wiring contract, runs even without PySide6 installed."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_main_wires_modern_shell_without_replacing_business_workers():
    src = (ROOT / 'main.py').read_text(encoding='utf-8')
    ast.parse(src)
    assert 'self.modern_shell = ModernShell(' in src
    assert 'self.setCentralWidget(self.modern_shell)' in src
    assert 'self.tab_register.layout().insertWidget(0, connection)' in src
    assert 'self.tabs.currentChanged.connect(self._on_main_tab_changed)' in src

def test_modern_shell_navigation_does_not_call_qac_automation():
    src = (ROOT / 'app' / 'modern_shell.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    assert 'self.tabs.setCurrentIndex(index)' in src
    assert 'self.access_checker(index)' in src
    for forbidden in ('launch_browser(', 'connect_qac_session(', 'ensure_qac_module(', 'page.goto(', 'playwright.'):
        assert forbidden not in src
