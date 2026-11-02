from app.daily_document_register import qac_numeric_values_equal

def test_qac_blur_normalization():
    assert qac_numeric_values_equal('.51', '0.5100')
    assert qac_numeric_values_equal('0.5530', '0.553')
    assert qac_numeric_values_equal('-36.8', '-36.8000')
    assert qac_numeric_values_equal('12.10', '12.1000')

def test_qac_mismatch_is_still_rejected():
    assert not qac_numeric_values_equal('.51', '0.5200')
    assert not qac_numeric_values_equal('.51', '')
    assert not qac_numeric_values_equal('NaN', 'NaN')
    assert not qac_numeric_values_equal('Infinity', 'Infinity')

def test_numeric_save_flow_keeps_confirmation():
    import inspect
    from app import daily_document_register, qac_measure_actions
    src = inspect.getsource(daily_document_register._register_daily_document_on_page) if hasattr(daily_document_register, '_register_daily_document_on_page') else inspect.getsource(daily_document_register)
    assert 'qac_numeric_values_equal(selection[6:]' in src
    assert '_click_save(page, fieldset, progress)' in src
    save_src = inspect.getsource(qac_measure_actions._click_save)
    assert 'acknowledge_visible_modal' in save_src
