import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import qac_interaction as interaction


class TestQACDiagnosticsP06(unittest.TestCase):
    def test_sensitive_values_masked(self):
        result = interaction._sanitize_log('password=secret token:abc cookie=xyz task=44')
        self.assertNotIn('secret', result)
        self.assertNotIn('abc', result)
        self.assertNotIn('xyz', result)
        self.assertIn('task=44', result)

    def test_file_is_written_without_ui_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            original = interaction._technical_logger
            try:
                # The logger is process-global, so point a fresh instance to this test file.
                import logging
                from logging.handlers import RotatingFileHandler
                logger = logging.getLogger('qac.diag.test')
                logger.setLevel(logging.INFO)
                logger.propagate = False
                handler = RotatingFileHandler(Path(directory)/'diag.log', encoding='utf-8')
                logger.addHandler(handler)
                interaction._technical_logger = logger
                interaction._log(None, 'QAC SAVE CLICK START | task=77')
                handler.flush()
                self.assertIn('task=77', (Path(directory)/'diag.log').read_text(encoding='utf-8'))
            finally:
                interaction._technical_logger = original
                logger.removeHandler(handler)
                handler.close()

    def test_modal_transition_has_both_states(self):
        self.assertIn('INFO -> NONE', interaction.describe_modal_transition('INFO', 'NONE'))
