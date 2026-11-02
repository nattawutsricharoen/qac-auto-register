"""Production date publication: defaults only, per-module edits stay isolated."""
from datetime import date

class ReferenceDateHub:
    def __init__(self):
        self._reference = None
        self._module_dates = {}
        self._overrides = set()

    @staticmethod
    def _validate(value):
        if isinstance(value, date):
            return value.isoformat()
        return date.fromisoformat(str(value)).isoformat()

    def publish(self, value):
        published = self._validate(value)
        self._reference = published
        for module in self._module_dates:
            if module not in self._overrides:
                self._module_dates[module] = published
        return published

    def subscribe(self, module):
        if module not in self._module_dates:
            self._module_dates[module] = self._reference
        return self._module_dates[module]

    def set_module_date(self, module, value):
        self.subscribe(module)
        self._module_dates[module] = self._validate(value)
        self._overrides.add(module)

    def date_for(self, module):
        return self.subscribe(module)

    def reset_to_reference(self, module):
        self._overrides.discard(module)
        self._module_dates[module] = self._reference
        return self._reference
