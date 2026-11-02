from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from .qac_reader import (
    scan_documents_async,
    load_itag_process_subs_async,
)
from .ocr_ng import process_images
from .qac_sync import sync_events_incremental
from .register_engine import (
    execute_register_async,
    execute_alarm_import_async,
    execute_production_output_async,
    execute_manual_qac_events_async,
)


class AutomationControl:
    def __init__(self):
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
    def pause(self): self.pause_event.set()
    def resume(self): self.pause_event.clear()
    def stop(self):
        self.stop_event.set()
        self.pause_event.clear()



class LoggedQACWorker(QThread):
    """Persist progress across all UI workflows even when GUI log is cleared."""

    def _progress_log(self, message):
        from .qac_interaction import _log
        _log(None, f"WORKFLOW={type(self).__name__} | {message}")
        from datetime import datetime
        self.progress.emit(f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {message}")


class QACSessionWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        employee_id: str,
        module_key: str | None = None,
        home_url: str = "http://159.228.251.234:8077/",
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.employee_id = str(employee_id or "").strip()
        self.module_key = module_key
        self.home_url = home_url

    def run(self):
        try:
            from .qac_session import ensure_qac_session_and_module_async
            result = asyncio.run(
                ensure_qac_session_and_module_async(
                    cdp_url=self.cdp_url,
                    employee_id=self.employee_id,
                    module_key=self.module_key,
                    home_url=self.home_url,
                    progress=self._progress_log,
                )
            )
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))



class DailyDocumentScanWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url: str, production_date: str, documents: list[dict]):
        super().__init__()
        self.cdp_url = cdp_url
        self.production_date = production_date
        self.documents = documents

    def run(self):
        try:
            from .daily_document import scan_qac_documents_async
            result = asyncio.run(scan_qac_documents_async(
                self.cdp_url, self.production_date, self.documents, self._progress_log
            ))
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class DailyDocumentOpenWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, cdp_url: str, task_id: str, document: dict | None = None):
        super().__init__()
        self.cdp_url = cdp_url
        self.task_id = task_id
        self.document = document or {}

    def run(self):
        try:
            from .daily_document import open_daily_measure_async
            result = asyncio.run(open_daily_measure_async(self.cdp_url, self.task_id, self.document))
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class QACHtmlCollectorWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        production_date: str,
        documents: list[dict],
        output_root: str,
        overwrite_existing: bool = False,
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.production_date = production_date
        self.documents = list(documents)
        self.output_root = output_root
        self.overwrite_existing = bool(overwrite_existing)
        self.control = AutomationControl()

    def request_pause(self): self.control.pause()
    def request_resume(self): self.control.resume()
    def request_stop(self): self.control.stop()

    def run(self):
        try:
            from .qac_html_collector import collect_qac_html_async
            result = asyncio.run(collect_qac_html_async(
                cdp_url=self.cdp_url,
                production_date=self.production_date,
                documents=self.documents,
                output_root=self.output_root,
                progress=self._progress_log,
                control=self.control,
                overwrite_existing=self.overwrite_existing,
            ))
            self.completed.emit(result)
        except InterruptedError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(str(e))


class DailyDocumentRegisterWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        production_date: str,
        documents: list[dict],
        settings: dict | None = None,
        dry_run: bool = True,
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.production_date = production_date
        self.documents = list(documents)
        self.settings = dict(settings or {})
        self.dry_run = bool(dry_run)
        self.control = AutomationControl()

    def request_pause(self): self.control.pause()
    def request_resume(self): self.control.resume()
    def request_stop(self): self.control.stop()

    def run(self):
        try:
            from .daily_document_register import execute_daily_ok_register_async
            result = asyncio.run(execute_daily_ok_register_async(
                cdp_url=self.cdp_url,
                production_date=self.production_date,
                documents=self.documents,
                settings=self.settings,
                dry_run=self.dry_run,
                progress=self._progress_log,
                control=self.control,
            ))
            self.completed.emit(result)
        except InterruptedError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(str(e))


class SamplePrepareWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url: str, production_date: str, documents: list[dict], excel_headers: list[str], excel_row_values: dict, serial_2d: str, sample_type: str, excel_raw_values: list[str] | None = None, reserved_plans: list[dict] | None = None, source_profile: dict[int, tuple[str, str]] | None = None, model: str = "", process_master: str = "", station: str = "", target_process: str = "", line: str = ""):
        super().__init__()
        self.cdp_url = cdp_url
        self.production_date = production_date
        self.documents = list(documents)
        self.excel_headers = list(excel_headers)
        self.excel_row_values = dict(excel_row_values)
        self.serial_2d = str(serial_2d or "")
        self.sample_type = str(sample_type or "")
        self.excel_raw_values = list(excel_raw_values or [])
        self.reserved_plans = list(reserved_plans or [])
        self.source_profile = dict(source_profile or {})
        self.model = str(model or "")
        self.process_master = str(process_master or "")
        self.station = str(station or "")
        self.target_process = str(target_process or "")
        self.line = str(line or "")

    def run(self):
        try:
            from .sample_register import prepare_sample_registration_async
            result = asyncio.run(prepare_sample_registration_async(
                self.cdp_url, self.production_date, self.documents,
                self.excel_headers, self.excel_row_values,
                self.serial_2d, self.sample_type, self._progress_log,
                excel_raw_values=self.excel_raw_values, reserved_plans=self.reserved_plans,
                source_profile=self.source_profile, model=self.model,
                process_master=self.process_master, station=self.station,
                target_process=self.target_process, line=self.line
            ))
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class SampleRegisterWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url: str, plan):
        super().__init__()
        self.cdp_url = cdp_url
        self.plan = [dict(p) for p in plan] if isinstance(plan, list) else dict(plan or {})

    def run(self):
        try:
            from .sample_register import execute_sample_registration_async, execute_sample_batch_registration_async
            if isinstance(self.plan, list):
                result = asyncio.run(execute_sample_batch_registration_async(
                    self.cdp_url, self.plan, self._progress_log
                ))
            else:
                result = asyncio.run(execute_sample_registration_async(
                    self.cdp_url, self.plan, self._progress_log
                ))
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

class ScanWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, cdp_url: str):
        super().__init__()
        self.cdp_url = cdp_url

    def run(self):
        try:
            result = asyncio.run(
                scan_documents_async(self.cdp_url)
            )
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class RegisterWorker(LoggedQACWorker):
    progress = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        page_index: int,
        actions: list[dict],
        dry_run: bool,
        expected_document: dict | None = None,
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index
        self.actions = actions
        self.dry_run = dry_run
        self.expected_document = expected_document
        self.control = AutomationControl()

    def request_pause(self): self.control.pause()
    def request_resume(self): self.control.resume()
    def request_stop(self): self.control.stop()

    def run(self):
        try:
            asyncio.run(
                execute_register_async(
                    cdp_url=self.cdp_url,
                    page_index=self.page_index,
                    actions=self.actions,
                    dry_run=self.dry_run,
                    progress=self._progress_log,
                    control=self.control,
                    expected_document=self.expected_document,
                )
            )
            self.completed.emit()
        except Exception as e:
            self.failed.emit(str(e))


class AlarmImportWorker(LoggedQACWorker):
    progress = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        page_index: int,
        actions: list[dict],
        dry_run: bool,
        duplicate_check: bool = True
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index
        self.actions = actions
        self.dry_run = dry_run
        self.duplicate_check = bool(
            duplicate_check
        )
        self.control = AutomationControl()

    def request_pause(self): self.control.pause()
    def request_resume(self): self.control.resume()
    def request_stop(self): self.control.stop()

    def run(self):
        try:
            asyncio.run(
                execute_alarm_import_async(
                    cdp_url=self.cdp_url,
                    page_index=self.page_index,
                    actions=self.actions,
                    dry_run=self.dry_run,
                    progress=self._progress_log,
                    control=self.control,
                    duplicate_check=self.duplicate_check
                )
            )
            self.completed.emit()
        except Exception as e:
            self.failed.emit(str(e))



class ItagProcessWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        cdp_url: str,
        page_index: int,
        process_id: str
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index
        self.process_id = process_id

    def run(self):
        try:
            result = asyncio.run(
                load_itag_process_subs_async(
                    self.cdp_url,
                    self.page_index,
                    self.process_id
                )
            )
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class ExistingAlarmWorker(LoggedQACWorker):
    """
    Shared persistent QAC-cache reader used by Auto Register,
    Alarm Import and Production Output status views.

    It compares timeline Result IDs with SQLite and clicks only Result IDs
    that are new/incomplete in the local cache.
    """
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cdp_url,
        page_index
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index

    def run(self):
        try:
            from playwright.async_api import (
                async_playwright
            )

            async def read_existing():
                async with async_playwright() as pw:
                    browser = (
                        await pw.chromium
                        .connect_over_cdp(
                            self.cdp_url
                        )
                    )

                    if not browser.contexts:
                        raise RuntimeError(
                            "ไม่พบ Browser Context"
                        )

                    pages = (
                        browser.contexts[0].pages
                    )

                    if (
                        self.page_index < 0
                        or self.page_index
                        >= len(pages)
                    ):
                        raise RuntimeError(
                            "QAC tab ไม่อยู่แล้ว "
                            "กรุณา Scan ใหม่"
                        )

                    page = pages[
                        self.page_index
                    ]

                    (
                        _document_key,
                        _identity,
                        events,
                        stats,
                    ) = await sync_events_incremental(
                        page,
                        progress=self._progress_log
                    )

                    self._progress_log(
                        "QAC CACHE READY | "
                        f"timeline={stats['timeline']} | "
                        f"read_new={stats['read_details']} | "
                        f"cached={stats['returned']}"
                    )

                    return events

            result = asyncio.run(
                read_existing()
            )
            self.completed.emit(
                result
            )

        except Exception as e:
            self.failed.emit(
                str(e)
            )


class OcrBatchWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)
    progress_percent = Signal(int, str)

    def __init__(
        self,
        image_paths: list[str],
        tesseract_cmd: str,
        app_root: str
    ):
        super().__init__()
        self.image_paths = list(
            image_paths
        )
        self.tesseract_cmd = tesseract_cmd
        self.app_root = app_root

    def run(self):
        try:
            results = []

            total = len(
                self.image_paths
            )

            self.progress_percent.emit(
                0,
                f"เตรียม OCR 0/{total}"
            )

            for index, image_path in enumerate(
                self.image_paths,
                1
            ):
                name = Path(image_path).name

                before_percent = int(
                    ((index - 1) / max(total, 1)) * 100
                )
                self.progress_percent.emit(
                    before_percent,
                    f"กำลัง OCR {index}/{total}: {name}"
                )

                self._progress_log(
                    f"OCR {index}/{total}: {name}"
                )

                one = process_images(
                    [image_path],
                    tesseract_cmd=self.tesseract_cmd,
                    app_root=self.app_root
                )
                results.extend(one)

                after_percent = int(
                    (index / max(total, 1)) * 100
                )
                self.progress_percent.emit(
                    after_percent,
                    f"OCR เสร็จ {index}/{total}: {name}"
                )

            self.progress_percent.emit(
                100,
                f"OCR COMPLETE {total}/{total}"
            )
            self.completed.emit(
                results
            )
        except Exception as e:
            self.failed.emit(
                str(e)
            )



class ProductionOutputWorker(LoggedQACWorker):
    completed = Signal()
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        cdp_url,
        page_index,
        actions,
        dry_run
    ):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index
        self.actions = list(actions)
        self.dry_run = dry_run
        self.control = AutomationControl()

    def request_pause(self):
        self.control.pause()

    def request_resume(self):
        self.control.resume()

    def request_stop(self):
        self.control.stop()

    def run(self):
        try:
            asyncio.run(
                execute_production_output_async(
                    self.cdp_url,
                    self.page_index,
                    self.actions,
                    dry_run=self.dry_run,
                    progress=self._progress_log,
                    control=self.control
                )
            )
            self.completed.emit()
        except Exception as e:
            self.failed.emit(str(e))


class ManualQACEventWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url, page_index, actions):
        super().__init__()
        self.cdp_url = cdp_url
        self.page_index = page_index
        self.actions = list(actions)

    def run(self):
        try:
            result = asyncio.run(
                execute_manual_qac_events_async(
                    self.cdp_url,
                    self.page_index,
                    self.actions,
                    progress=self._progress_log,
                )
            )
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class ProductionTransferWorker(LoggedQACWorker):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url, employee_id, file_path):
        super().__init__()
        self.cdp_url = cdp_url
        self.employee_id = employee_id
        self.file_path = file_path

    def run(self):
        try:
            from .production_transfer import transfer_line_data_async
            result = asyncio.run(transfer_line_data_async(
                self.cdp_url, self.employee_id, self.file_path, self._progress_log
            ))
            self.completed.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


from .browser_operation_lock import _serialize_qac_browser_run

for _qac_worker_type in (
    QACSessionWorker, DailyDocumentScanWorker, DailyDocumentOpenWorker,
    QACHtmlCollectorWorker, DailyDocumentRegisterWorker,
    SamplePrepareWorker, SampleRegisterWorker, ScanWorker, RegisterWorker,
    AlarmImportWorker, ItagProcessWorker, ExistingAlarmWorker,
    ProductionOutputWorker, ManualQACEventWorker, ProductionTransferWorker,
):
    _qac_worker_type.run = _serialize_qac_browser_run(_qac_worker_type.run)
