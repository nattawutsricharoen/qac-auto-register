from dataclasses import dataclass, field
from typing import List

@dataclass
class FormOption:
    value: str
    name: str

    @property
    def label(self) -> str:
        return f"{self.name} [{self.value}]"

@dataclass
class DowntimeOption:
    value: str
    name: str
    machine_required: bool = False
    model_required: bool = False
    production_output_required: bool = False
    time_loss_required: bool = False
    category_key: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} [{self.value}]"


@dataclass
class CategoryOption:
    value: str
    name: str
    downtime_value: str = ""

    @property
    def label(self) -> str:
        return f"{self.name} [{self.value}]"


@dataclass
class ModelOption:
    value: str
    name: str
    product_number: str = ""

    @property
    def label(self) -> str:
        suffix = f" — {self.product_number}" if self.product_number else ""
        return f"{self.name}{suffix} [{self.value}]"

@dataclass
class QACDocument:
    page_index: int
    title: str
    url: str
    production_date: str
    line: str
    shift: str
    document_no: str
    models: List[ModelOption] = field(default_factory=list)
    machines: List[FormOption] = field(default_factory=list)
    downtimes: List[DowntimeOption] = field(default_factory=list)
    categories: List[CategoryOption] = field(default_factory=list)
    ng_products: List[FormOption] = field(default_factory=list)
    itag_lines: List[FormOption] = field(default_factory=list)

    @property
    def label(self) -> str:
        return (
            f"{self.production_date} | {self.line} | "
            f"{self.shift} | Tab {self.page_index + 1}"
        )
