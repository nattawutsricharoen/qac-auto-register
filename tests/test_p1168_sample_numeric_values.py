from app.sample_register import _slot_matches_expected, _validate_registration_slot


def field(saved, expected, kind='2', input_format='1'):
    return dict(item='460925', label='Weld Current (kA)', type=kind, input_format=input_format,
                value=expected, slots=[dict(index=8, empty=False, disabled=True, value=saved, persisted=True)])


def test_saved_numeric_trailing_zeros_are_equal():
    for actual, wanted in [('21.60', '21.6'), ('0.000', '0'), ('001.50', '1.5'), ('-2.500', '-2.5')]:
        f = field(actual, wanted)
        assert _slot_matches_expected(f, 8, wanted)
        assert _validate_registration_slot([f], [f], 8) == {'460925': 'SKIP'}


def test_real_numeric_mismatch_still_stops():
    f = field('21.61', '21.6')
    assert not _slot_matches_expected(f, 8, '21.6')


def test_text_identifier_keeps_leading_zero_significance():
    f = field('00120', '120', kind='7')
    assert not _slot_matches_expected(f, 8, '120')


def test_numeric_does_not_accept_units_or_embedded_text():
    f = field('21.60 kA', '21.6')
    assert not _slot_matches_expected(f, 8, '21.6')
