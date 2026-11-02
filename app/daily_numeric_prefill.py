"""Resolve numeric UI prefill without discarding verified QAC Measure reference."""


def resolve_numeric_prefill(reference_value: str, preset_choice: str) -> tuple[str, bool]:
    """Return editable text and whether an explicit numeric preset was applied.

    Empty presets are absence of an override, *not* a request to skip.
    Explicit opt-out is represented in the user-facing widget by entering '-'.
    """
    reference = str(reference_value or '').strip()
    choice = str(preset_choice or '').strip()
    if choice.startswith('VALUE:'):
        return choice[6:], True
    return reference, False
