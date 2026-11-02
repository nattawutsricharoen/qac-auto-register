"""Guard requested Sample behavior: QAC Complete! is final save acknowledgement."""
import inspect
from app import sample_register


def test_sample_fill_requires_confirmation_and_complete_without_readback():
    src = inspect.getsource(sample_register._fill_field_at_master_slot)
    ack = inspect.getsource(sample_register._sample_save_until_complete)
    assert '_sample_save_until_complete(' in src
    assert 'SAMPLE SAVE CONFIRM' in ack
    assert 'SAMPLE SAVE COMPLETE ACK' in ack
    assert 'SAMPLE SAVE COMPLETE' in ack
    assert 'reselect_after_sample_save(' not in src
    assert '_live_schema(' not in src
    assert 'SAMPLE SAVE PENDING' not in src


def test_register_keeps_live_prewrite_check_but_no_final_audit():
    src = inspect.getsource(sample_register.execute_sample_registration_async)
    assert '_validate_registration_slot(' in src
    assert '_slot_matches_expected(' in src
    assert 'SAMPLE REGISTER ACK SUMMARY' in src
    assert 'SAMPLE FINAL AUDIT' not in src
    assert '_post_sample_trace_comment(' in src
