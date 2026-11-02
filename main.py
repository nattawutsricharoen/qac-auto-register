import sys
import os
import re
import json
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QPixmap, QIntValidator

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QComboBox,
    QTextEdit,
    QCheckBox,
    QFileDialog,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QLineEdit,
    QProgressBar,
    QHeaderView,
    QCompleter,
    QGroupBox,
    QFormLayout,
    QScrollArea,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QProgressDialog,
    QSpinBox,
    QMenu,
    QInputDialog,
    QSplitter,
    QSizePolicy,
)

from app.core.local_connection import LocalConnection
from app.core.reference_date import ReferenceDateHub
from app.modules.auto_register import AutoRegisterState
from app.modern_shell import ModernShell
from app.access_csv_editor import read_access_csv, save_access_csv
from app.config import load_settings, save_settings, app_root
from app.runtime_paths import program_dir
from app.access_control import (
    load_access_record,
    enroll_pending_access,
)
from app.audit import AuditLogger
from app.browser import launch_browser, cdp_ready
from app.schedule import build_schedule
from app.excel_import import load_alarm_files
from app.sample_register import (
    load_sample_excel, find_sample_row, guess_2d_column, apply_manual_values,
    load_sample_process_options, resolve_sample_document_name, build_daily_sample_targets,
)
from app.alarm_learning import AlarmLearningStore
from app.sample_mapping_store import save_override, delete_override, mapping_db_path, load_overrides
from app.alarm_learning_sync import upload_alarm_learning_snapshot
from app.electrode_replacement import ReplacementStore, ReplacementError
from app.ocr_ng import build_description, find_tesseract
from app.production_output import load_production_line_file
from app.daily_document import load_document_master, resolve_document_source
from app.mct_master import (
    load_central_mct,
    save_central_mct,
    resolve_central_mct_path,
)
from app.hourly_validation import (
    ManualEventStore,
    resolve_mct_rule,
    hour_datetimes,
    normalize_qac_events,
    normalize_manual_events,
    validate_manual_event_rows,
    evaluate_hour,
)
from app.worker import (
    ScanWorker,
    RegisterWorker,
    AlarmImportWorker,
    ItagProcessWorker,
    ExistingAlarmWorker,
    OcrBatchWorker,
    ProductionOutputWorker,
    ProductionTransferWorker,
    ManualQACEventWorker,
    QACSessionWorker,
    DailyDocumentScanWorker,
    DailyDocumentOpenWorker,
    QACHtmlCollectorWorker,
    DailyDocumentRegisterWorker,
    SamplePrepareWorker,
    SampleRegisterWorker,
)


def set_windows_app_id():
    """Give Windows a stable application identity for the taskbar icon."""
    if sys.platform != "win32":
        return

    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "OMBIZ.QACAutoRegister.1.7"
        )
    except Exception:
        # Icon failure must never block the production application.
        pass


def make_searchable(combo: QComboBox):
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.NoInsert)
    completer = QCompleter(combo.model(), combo)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    combo.setCompleter(completer)
    return combo


def _column_width_state_path() -> Path:
    """Per-PC UI state. Never synchronize this file with central config."""
    return program_dir() / "ui_column_widths.json"


def _load_column_width_state() -> dict:
    path = _column_width_state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_column_width_state(state: dict) -> None:
    path = _column_width_state_path()
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        # Column preferences must never block production work.
        pass


def _fit_table_columns(table: QTableWidget, min_width: int = 48) -> None:
    table.setProperty("_column_width_programmatic", True)
    try:
        table.resizeColumnsToContents()
        for col in range(table.columnCount()):
            width = table.columnWidth(col)
            table.setColumnWidth(col, max(min_width, min(width, 320)))
    finally:
        table.setProperty("_column_width_programmatic", False)


def _restore_table_column_widths(table: QTableWidget, key: str, min_width: int = 48) -> bool:
    state = _load_column_width_state()
    widths = state.get(key)
    if not isinstance(widths, list) or not widths:
        return False

    table.setProperty("_column_width_programmatic", True)
    try:
        for col, width in enumerate(widths[:table.columnCount()]):
            try:
                table.setColumnWidth(col, max(min_width, int(width)))
            except Exception:
                pass
    finally:
        table.setProperty("_column_width_programmatic", False)
    return True


def _persist_table_column_widths(table: QTableWidget, key: str) -> None:
    if table.property("_column_width_programmatic"):
        return
    state = _load_column_width_state()
    state[key] = [table.columnWidth(i) for i in range(table.columnCount())]
    _save_column_width_state(state)


def _clear_saved_table_widths(key: str) -> None:
    state = _load_column_width_state()
    if key in state:
        state.pop(key, None)
        _save_column_width_state(state)


def make_table_columns_resizable(
    table: QTableWidget,
    min_width: int = 48,
    persistence_key: str | None = None,
):
    """Interactive columns with per-PC remembered widths.

    Behaviour:
      * first use: Auto Fit (content capped at 320 px)
      * user drag: save widths locally in ui_column_widths.json
      * next launch/refresh: restore saved widths
      * header right-click: Auto Fit Columns / Reset Saved Widths

    The state is intentionally local because PCs can use different displays.
    """
    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(min_width)
    header.setSectionsMovable(False)
    header.setSectionResizeMode(QHeaderView.Interactive)

    key = persistence_key or table.objectName().strip()
    if not key:
        # Dynamic/temporary tables still remain manually resizable but are not
        # persisted unless the caller gives a stable key.
        _fit_table_columns(table, min_width)
        return

    table.setObjectName(key)

    # Repeated calls are intentional after table data is populated. If the
    # user has a saved layout, restore it; otherwise auto-fit the new content.
    restored = _restore_table_column_widths(table, key, min_width)
    if not restored:
        _fit_table_columns(table, min_width)

    if table.property("_column_width_persistence_initialized"):
        return
    table.setProperty("_column_width_persistence_initialized", True)

    def on_section_resized(_logical_index, _old_size, _new_size):
        _persist_table_column_widths(table, key)

    header.sectionResized.connect(on_section_resized)

    header.setContextMenuPolicy(Qt.CustomContextMenu)

    def show_header_menu(pos):
        menu = QMenu(header)
        act_fit = menu.addAction("Auto Fit Columns")
        act_reset = menu.addAction("Reset Saved Widths")
        chosen = menu.exec(header.mapToGlobal(pos))
        if chosen == act_fit:
            _fit_table_columns(table, min_width)
            _persist_table_column_widths(table, key)
        elif chosen == act_reset:
            _clear_saved_table_widths(key)
            _fit_table_columns(table, min_width)

    header.customContextMenuRequested.connect(show_header_menu)

def resource_path(relative_name: str) -> Path:
    """
    Resolve packaged resources in source mode and PyInstaller onedir/onefile.
    In onedir, files added with --add-data are beside the executable bundle.
    """
    base = getattr(
        sys,
        "_MEIPASS",
        Path(__file__).resolve().parent
    )
    return Path(base) / relative_name


class DailySlotScanThread(QThread):
    """Read-only QAC measure HTML in a worker; never block PySide6 GUI thread."""
    schema_ready = Signal(object)
    scan_error = Signal(str)
    progress = Signal(str)

    def __init__(self, cdp_url: str, document: dict):
        super().__init__()
        self.cdp_url = cdp_url
        self.document = dict(document)

    def run(self):
        import asyncio
        from app.daily_slot_schema import discover_daily_slots
        try:
            result = asyncio.run(discover_daily_slots(
                self.cdp_url, self.document,
                progress=lambda line: self.progress.emit(str(line)),
            ))
            self.schema_ready.emit(result)
        except Exception as exc:
            self.scan_error.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("QAC Auto Register")
        self.setWindowIcon(
            QIcon(str(resource_path("Auto.ico")))
        )
        self.resize(1280, 820)

        self.local_connection = LocalConnection()
        self.reference_dates = ReferenceDateHub()
        self.auto_register_state = AutoRegisterState()
        self.settings = load_settings()
        self.app_root_path = app_root()
        self.audit = AuditLogger(
            self.app_root_path,
            self.settings.get("logging", {}).get("directory", "logs")
        )

        access_cfg = self.settings.get("access_control", {})
        try:
            record, local_ips, resolved_path = load_access_record(
                access_cfg.get("config_path", ""),
                self.app_root_path
            )
        except Exception as e:
            self.audit.write("ACCESS_CONFIG_ERROR", status="DENY", error=str(e))
            QMessageBox.critical(
                self,
                "QAC Auto Register",
                access_cfg.get("deny_message", "กรุณาติดต่อผู้พัฒนา")
            )
            raise SystemExit(3)

        if record is None:
            try:
                (
                    added,
                    pending_ip,
                    pending_name,
                    pending_path,
                ) = enroll_pending_access(
                    access_cfg.get(
                        "config_path",
                        ""
                    ),
                    self.app_root_path,
                    local_ips
                )

                self.audit.set_identity(
                    pending_name,
                    pending_ip
                )
                self.audit.write(
                    "ACCESS_PENDING_ENROLL",
                    status="PENDING",
                    added=added,
                    computer_name=pending_name,
                    ip=pending_ip,
                    access_config=pending_path
                )

                QMessageBox.critical(
                    self,
                    "QAC Auto Register",
                    (
                        "เครื่องนี้ยังไม่ได้รับสิทธิ์ใช้งาน\n\n"
                        f"IP: {pending_ip}\n"
                        f"Computer Name: {pending_name}\n\n"
                        "ระบบได้เพิ่มเครื่องนี้ลงใน "
                        "access_control.csv แล้ว\n"
                        "โดยกำหนด status=pending และสิทธิ์ทั้งหมด=0\n\n"
                        "กรุณาติดต่อผู้พัฒนา"
                    )
                )
                raise SystemExit(4)

            except SystemExit:
                raise
            except Exception as e:
                self.audit.write(
                    "ACCESS_PENDING_ENROLL_ERROR",
                    status="DENY",
                    local_ips=local_ips,
                    error=str(e)
                )
                QMessageBox.critical(
                    self,
                    "QAC Auto Register",
                    (
                        access_cfg.get(
                            "deny_message",
                            "กรุณาติดต่อผู้พัฒนา"
                        )
                        + "\n\n"
                        + "ไม่สามารถลงทะเบียนเครื่องใหม่"
                        + "ใน Central Access Config ได้\n"
                        + str(e)
                    )
                )
                raise SystemExit(5)

        if record.status.strip().lower() != "active":
            self.audit.set_identity(
                record.name,
                record.ip
            )
            self.audit.write(
                "ACCESS_DENIED",
                status="DENY",
                reason="NOT_ACTIVE",
                access_status=record.status,
                local_ips=local_ips
            )
            QMessageBox.critical(
                self,
                "QAC Auto Register",
                (
                    "เครื่องนี้ยังไม่ได้รับสิทธิ์ใช้งาน\n\n"
                    f"IP: {record.ip}\n"
                    f"Computer Name: {record.name}\n"
                    f"Status: {record.status}\n\n"
                    "กรุณาติดต่อผู้พัฒนา"
                )
            )
            raise SystemExit(4)

        self.access_record = record

        # Central MCT Master: one shared file beside access_control.csv.
        # Missing file is allowed; affected rows will show WAITING MCT until configured.
        try:
            central_rules, central_mct_path = load_central_mct(
                access_cfg.get("config_path", ""),
                self.app_root_path,
            )
            self.central_mct_path = str(central_mct_path)
            self.settings["hourly_validation"] = {
                "mct_rules": central_rules,
            }
            self.audit.write(
                "CENTRAL_MCT_LOAD",
                status="OK",
                path=self.central_mct_path,
                rule_count=len(central_rules),
            )
        except Exception as e:
            self.central_mct_path = str(resolve_central_mct_path(
                access_cfg.get("config_path", ""), self.app_root_path
            ))
            self.settings["hourly_validation"] = {"mct_rules": []}
            self.audit.write(
                "CENTRAL_MCT_LOAD", status="ERROR", path=self.central_mct_path, error=str(e)
            )
        self.audit.set_identity(
            record.name,
            record.ip
        )
        self.audit.configure_central(
            record.source_path
            or access_cfg.get(
                "config_path",
                ""
            )
        )
        self.audit.write(
            "PROGRAM_START",
            status="OK",
            tab1_enable=record.tab1_enable,
            tab1_show=record.tab1_show,
            tab2_enable=record.tab2_enable,
            tab2_show=record.tab2_show,
            tab3_enable=record.tab3_enable,
            tab3_show=record.tab3_show,
            tab4_enable=record.tab4_enable,
            tab4_show=record.tab4_show,
            tab5_enable=record.tab5_enable,
            tab5_show=record.tab5_show,
            tab6_enable=record.tab6_enable,
            tab6_show=record.tab6_show,
            settings_show=record.settings_show,
            access_config=record.source_path,
            access_source=record.source_mode,
            access_cached_at=record.cached_at
        )

        if (
            record.source_mode
            == "LOCAL_CACHE"
        ):
            self.setWindowTitle(
                "QAC Auto Register "
                "[OFFLINE ACCESS CACHE]"
            )

        self.documents = []
        self.current_actions = []
        self.auto_existing_events = []
        self.auto_existing_worker = None
        self.alarm_rows = []
        self.alarm_files = []

        self.scan_worker = None
        self.register_worker = None
        self.alarm_worker = None
        self.itag_process_worker = None
        self.existing_alarm_worker = None
        self.existing_alarm_events = []
        self.current_itag_line = None
        self.alarm_learning_store = AlarmLearningStore()
        self._alarm_ui_memory = {}
        self._pending_alarm_learning_actions = []
        self.itag_process_options = []

        self.ocr_files = []
        self.ocr_results = []
        self.ocr_rows = []
        self.ocr_worker = None
        self.ocr_import_worker = None
        self.ocr_itag_worker = None
        self.ocr_existing_worker = None
        self.ocr_itag_line = None
        self.ocr_process_options = []

        self.production_file = ""
        self.production_data = None
        self.production_worker = None
        self.production_transfer_worker = None
        self.production_existing_worker = None
        self.production_existing_events = []
        self.hourly_event_store = ManualEventStore()
        self.production_validation_results = {}

        self.qac_session_worker = None
        self._last_module_request = None

        self.daily_master_rows = []
        self.daily_filtered_rows = []
        self.daily_scan_results = {}
        self.daily_scan_worker = None
        self.daily_open_worker = None
        self.html_collector_worker = None
        self.daily_register_worker = None
        self._pending_daily_register_payload = None
        self._pending_html_collect_payload = None

        self.sample_excel = None
        self.sample_excel_row = None
        self.sample_filtered_docs = []
        self.sample_prepare_worker = None
        self.sample_register_worker = None
        self.sample_status_worker = None
        self.sample_plan = None
        self.sample_batch_plans = []
        self._pending_sample_prepare_payload = None

        self.electrode_selected_no = ""

        self.tabs = QTabWidget()

        self.tab_register = self._build_register_tab()
        self.tab_alarm = self._build_excel_tab()
        self.tab_ocr = self._build_ocr_tab()
        self.tab_production = self._build_production_output_tab()
        self.tab_daily_document = self._build_daily_document_tab()
        self.tab_sample_register = self._build_sample_register_tab()
        self.tab_electrode = self._build_electrode_tab()

        self.tabs.addTab(
            self.tab_register,
            "Auto Register"
        )
        self.tabs.addTab(
            self.tab_alarm,
            "Alarm Import"
        )
        self.tabs.addTab(
            self.tab_ocr,
            "OCR NG Import"
        )
        self.tabs.addTab(
            self.tab_production,
            "Production Output Import"
        )
        self.tabs.addTab(
            self.tab_daily_document,
            "Daily Document"
        )
        self.tabs.addTab(
            self.tab_sample_register,
            "Sample Register"
        )
        self.tabs.addTab(
            self.tab_electrode,
            "Electrode Control"
        )

        if self.access_record.settings_show:
            self.tab_settings = self._build_settings_tab()
            self.tabs.addTab(
                self.tab_settings,
                "Settings"
            )
        else:
            self.tab_settings = None

        self._apply_tab_access()
        self.tabs.currentChanged.connect(self._on_main_tab_changed)

        # Modern presentation shell; all existing tabs and workers remain intact.
        self._admin_unlocked = False
        self.modern_shell = ModernShell(
            self.tabs,
            on_navigate=lambda index: None,
            before_navigate=self._authorize_settings_tab,
            access_checker=lambda index: (
                0 <= index < self.tabs.count()
                and self.tabs.isTabVisible(index)
                and self.tabs.isTabEnabled(index)
            ),
        )
        self.setCentralWidget(self.modern_shell)
        self.tabs.currentChanged.connect(self.modern_shell.sync_tab)

        # Connection controls remain available on the Auto Register page.
        connection = QGroupBox("QAC Connection")
        login_row = QHBoxLayout(connection)
        login_row.addWidget(QLabel("Employee ID"))
        self.txt_employee_id = QLineEdit()
        self.txt_employee_id.setPlaceholderText("Employee ID")
        self.txt_employee_id.setMaximumWidth(220)
        self.txt_employee_id.returnPressed.connect(self.connect_qac_session)
        login_row.addWidget(self.txt_employee_id)
        self.btn_qac_connect = QPushButton("Connect / Sign In QAC")
        self.btn_qac_connect.clicked.connect(self.connect_qac_session)
        login_row.addWidget(self.btn_qac_connect)
        self.lbl_qac_session = QLabel("QAC Session: Not connected")
        login_row.addWidget(self.lbl_qac_session)
        login_row.addStretch()
        self.tab_register.layout().insertWidget(0, connection)

        self.refresh_browser_status()
        self.load_daily_document_list(show_message=False)

    # ---------------- Auto Register ----------------
    def _build_register_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        browser_row = QHBoxLayout()
        browser_row.addWidget(QLabel("Browser"))

        self.cmb_browser = QComboBox()
        for key, cfg in self.settings["browsers"].items():
            self.cmb_browser.addItem(cfg["display_name"], key)

        self.cmb_browser.currentIndexChanged.connect(
            self.refresh_browser_status
        )

        self.btn_browser = QPushButton("Open QAC Browser")
        self.btn_scan = QPushButton("Scan QAC Tabs")

        self.btn_browser.clicked.connect(self.open_browser)
        self.btn_scan.clicked.connect(self.scan_tabs)

        browser_row.addWidget(self.cmb_browser)
        browser_row.addWidget(self.btn_browser)
        browser_row.addWidget(self.btn_scan)

        self.lbl_browser_status = QLabel()
        browser_row.addWidget(self.lbl_browser_status)
        browser_row.addStretch()

        root.addLayout(browser_row)
        root.addWidget(QLabel("QAC Document"))

        self.cmb_doc = QComboBox()
        self.cmb_doc.currentIndexChanged.connect(self.document_changed)
        root.addWidget(self.cmb_doc)

        self.lbl_doc = QLabel("ยังไม่ได้เลือกเอกสาร")
        self.lbl_doc.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_doc)

        root.addWidget(QLabel("Model"))

        self.cmb_model = make_searchable(QComboBox())
        self.cmb_model.currentIndexChanged.connect(self.refresh_preview)
        root.addWidget(self.cmb_model)

        opt = QHBoxLayout()

        self.chk_dry = QCheckBox("Dry Run (ไม่บันทึกจริง)")
        self.chk_dry.setChecked(False)
        self.chk_dry.setVisible(False)

        self.btn_preview = QPushButton("Refresh QAC Status")
        self.btn_register = QPushButton("REGISTER")
        self.btn_reg_pause = QPushButton("Pause")
        self.btn_reg_resume = QPushButton("Resume")
        self.btn_reg_stop = QPushButton("Stop")

        self.btn_preview.clicked.connect(self.refresh_preview)
        self.btn_register.clicked.connect(self.run_register)
        self.btn_reg_pause.clicked.connect(self.pause_register)
        self.btn_reg_resume.clicked.connect(self.resume_register)
        self.btn_reg_stop.clicked.connect(self.stop_register)

        opt.addStretch()
        opt.addWidget(self.btn_preview)
        opt.addWidget(self.btn_register)
        opt.addWidget(self.btn_reg_pause)
        opt.addWidget(self.btn_reg_resume)
        opt.addWidget(self.btn_reg_stop)
        root.addLayout(opt)

        self.tbl = QTableWidget(0, 5)
        self.tbl.setHorizontalHeaderLabels(
            ["Status", "Type", "Start", "End", "Model"]
        )
        make_table_columns_resizable(self.tbl, persistence_key="auto_register")
        root.addWidget(self.tbl)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(190)
        root.addWidget(self.log)

        return w

    # ---------------- Electrode Control ----------------
    def _electrode_db_path(self) -> Path:
        cfg = dict(self.settings.get("electrode_control") or {})
        raw = str(cfg.get("sqlite_path") or ".\\electrode_control.db")
        path = Path(raw)
        if not path.is_absolute():
            path = program_dir() / raw.replace("\\", "/").lstrip("./")
        return path

    def _build_electrode_tab(self):
        """Independent scan-first Issue/Return page; no Employee ID or QAC login."""
        from app.electrode_issue_return_ui import ElectrodeIssueReturnPage
        self.electrode_issue_page = ElectrodeIssueReturnPage(
            program_dir() / 'database' / 'electrode_issue_return_local.sqlite3', self)
        return self.electrode_issue_page

    def _replacement_store(self):
        if not hasattr(self, "_replacement_ledger"):
            self._replacement_ledger = ReplacementStore(self._electrode_db_path())
        return self._replacement_ledger

    def _build_replacement_pages(self, tabs):
        page = QWidget(); layout=QVBoxLayout(page)
        layout.addWidget(QLabel("Current Electrode / Change Electrode"))
        filters=QHBoxLayout()
        self.replace_machine=QComboBox();self.replace_machine.addItem("All Machines")
        self.replace_station=QComboBox();self.replace_station.addItem("All Stations")
        self.replace_diameter=QComboBox();self.replace_diameter.addItem("All Diameters")
        for x in (self.replace_machine,self.replace_station,self.replace_diameter):
            filters.addWidget(x);x.currentIndexChanged.connect(self.refresh_replacement_current)
        layout.addLayout(filters)
        self.replace_table=QTableWidget(0,9)
        self.replace_table.setHorizontalHeaderLabels(["Machine","Station / Head","Position","Diameter","Electrode No.","Start Shot","Current Shot","Installed","Status"])
        self.replace_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.replace_table.itemSelectionChanged.connect(self._replacement_row_selected)
        make_table_columns_resizable(self.replace_table,persistence_key="replacement_current")
        layout.addWidget(self.replace_table,1)
        form=QGroupBox("Change Electrode — เลือกรายการจากตารางด้านบน")
        f=QFormLayout(form)
        self.replace_old_label=QLabel("—")
        self.replace_old_counter=QLineEdit()
        self.replace_old_counter.setValidator(QIntValidator(0, 2_000_000_000, self))
        self.replace_old_counter.setPlaceholderText("กรอก Final Counter ตัวเก่าทุกครั้ง")
        self.replace_new_no=QLineEdit();self.replace_new_no.setPlaceholderText("New Electrode No.")
        self.replace_new_start=QSpinBox();self.replace_new_start.setRange(0,2_000_000_000)
        self.replace_remark=QLineEdit()
        f.addRow("Old Electrode",self.replace_old_label)
        f.addRow("Final Counter (Old) *",self.replace_old_counter)
        f.addRow("New Electrode No. *",self.replace_new_no)
        f.addRow("Start Counter (New) *",self.replace_new_start)
        self.replace_current_shot=QLineEdit()
        self.replace_current_shot.setValidator(QIntValidator(0, 2_000_000_000, self))
        self.replace_current_shot.setPlaceholderText("บันทึก Shot ปัจจุบัน")
        f.addRow("Current Shot",self.replace_current_shot)
        f.addRow("Remark",self.replace_remark)
        btns=QHBoxLayout();
        first=QPushButton("Initial Install (ช่องว่างเท่านั้น)");first.clicked.connect(self.replacement_initial)
        confirm=QPushButton("Confirm Change");confirm.clicked.connect(self.replacement_change)
        shot_button=QPushButton("Save Shot")
        shot_button.clicked.connect(self.replacement_save_shot)
        btns.addWidget(first);btns.addWidget(shot_button);btns.addWidget(confirm);f.addRow(btns)
        layout.addWidget(form)
        tabs.addTab(page,"Electrode No. / Shot")
        self.replacement_page=page
        history=QWidget();hl=QVBoxLayout(history)
        hr=QHBoxLayout();self.replace_history_search=QLineEdit();self.replace_history_search.setPlaceholderText("Filter by Machine / Station / Old or New No.")
        self.replace_history_search.textChanged.connect(self.refresh_replacement_history)
        hr.addWidget(self.replace_history_search)
        for label,func in (("Export CSV",self.export_replacement_csv),("Export Excel",self.export_replacement_excel)):
            b=QPushButton(label);b.clicked.connect(func);hr.addWidget(b)
        hl.addLayout(hr)
        self.replace_history_table=QTableWidget(0,12)
        self.replace_history_table.setHorizontalHeaderLabels(["Date & Time","Machine","Station","Position","Diameter","Old No.","Old Start","Final Counter","Usage","New No.","New Start","By"])
        make_table_columns_resizable(self.replace_history_table,persistence_key="replacement_history")
        hl.addWidget(self.replace_history_table)
        tabs.addTab(history,"History / Export")
        master=QWidget();ml=QVBoxLayout(master)
        self.replace_master_table=QTableWidget(0,6)
        self.replace_master_table.setHorizontalHeaderLabels(["Machine","Station","Position","Diameter","Enabled","Required"])
        make_table_columns_resizable(self.replace_master_table,persistence_key="replacement_master")
        ml.addWidget(self.replace_master_table)
        master_buttons=QHBoxLayout()
        for label,func in (("Add Slot",self.replacement_add_slot),("Toggle Enable",self.replacement_toggle_slot),("Toggle Required",self.replacement_toggle_required)):
            b=QPushButton(label);b.clicked.connect(func);master_buttons.addWidget(b)
        ml.addLayout(master_buttons)
        self.replacement_master_page = master
        try:self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,"Replacement Ledger",str(exc))

    def replacement_open_settings(self):
        if not self._replacement_admin():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Electrode Slot Settings")
        dialog.resize(900, 580)
        layout = QVBoxLayout(dialog)
        # The admin table is not a normal operator tab.
        self.replacement_master_page.setParent(None)
        layout.addWidget(self.replacement_master_page)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        self.replacement_master_page.setParent(None)

    def _replacement_actor(self):
        actor=self.txt_employee_id.text().strip()
        if not actor:raise ReplacementError("กรุณากรอก Employee ID ก่อนบันทึก")
        return actor

    def _replacement_selected(self):
        row=self.replace_table.currentRow()
        if row<0:raise ReplacementError("กรุณาเลือกแถว Electrode ก่อน")
        item=self.replace_table.item(row,0)
        data=item.data(Qt.UserRole) if item else None
        if not isinstance(data,dict):raise ReplacementError("ไม่พบข้อมูลตำแหน่ง")
        return data

    def _replacement_row_selected(self):
        try:
            r=self._replacement_selected()
            self.replace_old_label.setText(str(r.get("electrode_no") or "(Not installed)"))
            self.replace_old_counter.clear()
            self.replace_current_shot.clear()
        except ReplacementError:self.replace_old_label.setText("—")

    def refresh_replacement_all(self):
        store=self._replacement_store();rows=store.current()
        for combo,key in ((self.replace_machine,'machine'),(self.replace_station,'station'),(self.replace_diameter,'diameter')):
            previous=combo.currentText();combo.blockSignals(True);combo.clear();combo.addItem({"machine":"All Machines","station":"All Stations","diameter":"All Diameters"}[key])
            for value in sorted({str(r[key]) for r in rows if r[key]}):combo.addItem(value)
            index=combo.findText(previous)
            if index>=0:combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.refresh_replacement_current();self.refresh_replacement_history()
        self.replace_master_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for j,v in enumerate((r['machine'],r['station'],r['position'],r['diameter'],"YES" if r['enabled'] else "NO","YES" if r['required'] else "NO")):
                cell=QTableWidgetItem(str(v));cell.setData(Qt.UserRole,r);self.replace_master_table.setItem(i,j,cell)

    def refresh_replacement_current(self,*args):
        if not hasattr(self,'replace_table'):return
        rows=self._replacement_store().current()
        for widget,key,prefix in ((self.replace_machine,'machine','All Machines'),(self.replace_station,'station','All Stations'),(self.replace_diameter,'diameter','All Diameters')):
            value=widget.currentText()
            if value!=prefix:rows=[r for r in rows if str(r[key])==value]
        self.replace_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=(r['machine'],r['station'],r['position'],r['diameter'],r.get('electrode_no') or '—',r.get('start_counter') if r.get('start_counter') is not None else '—',r.get('current_shot') if r.get('current_shot') is not None else '—',r.get('installed_at') or '—','ON' if r['enabled'] else 'OFF')
            for j,v in enumerate(vals):
                cell=QTableWidgetItem(str(v));cell.setData(Qt.UserRole,r);self.replace_table.setItem(i,j,cell)

    def refresh_replacement_history(self,*args):
        if not hasattr(self,'replace_history_table'):return
        term=self.replace_history_search.text().strip().casefold()
        rows=self._replacement_store().history()
        if term:rows=[r for r in rows if term in ' '.join(str(r.get(k) or '') for k in ('machine','station','position','old_no','new_no')).casefold()]
        self.replace_history_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=tuple(r.get(k) for k in ('changed_at','machine','station','position','diameter','old_no','old_start','final_counter','usage_count','new_no','new_start','actor'))
            for j,v in enumerate(vals):self.replace_history_table.setItem(i,j,QTableWidgetItem(str(v if v is not None else '')))

    def replacement_save_shot(self):
        try:
            row=self._replacement_selected()
            if not row.get('electrode_no'):
                raise ReplacementError('กรุณาติดตั้ง Electrode ก่อน')
            value=self.replace_current_shot.text().strip()
            if not value:
                raise ReplacementError('กรุณากรอก Current Shot')
            self._replacement_store().record_shot(row['id'],row['electrode_no'],value,self._replacement_actor())
            self.replace_current_shot.clear()
            self.refresh_replacement_all()
        except Exception as exc:
            QMessageBox.warning(self,'Save Shot',str(exc))

    def replacement_initial(self):
        try:
            row=self._replacement_selected()
            if row.get('electrode_no'):raise ReplacementError('มี Electrode ติดตั้งแล้ว กรุณาใช้ Confirm Change')
            self._replacement_store().first_install(row['id'],self.replace_new_no.text(),self.replace_new_start.value(),self._replacement_actor())
            self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,'Initial Install',str(exc))

    def replacement_change(self):
        try:
            row=self._replacement_selected()
            if not row.get('electrode_no'):raise ReplacementError('ยังไม่มี Electrode เดิม กรุณาใช้ Initial Install')
            if not self.replace_old_counter.text().strip():
                raise ReplacementError("กรุณากรอก Final Counter ของตัวเก่าก่อนยืนยัน")
            details=f"Old: {row['electrode_no']}\nFinal Counter: {self.replace_old_counter.text()}\nNew: {self.replace_new_no.text()}\nStart Counter: {self.replace_new_start.value()}"
            if QMessageBox.question(self,'Confirm Electrode Change',details)!=QMessageBox.Yes:return
            self._replacement_store().replace(row['id'],row['electrode_no'],self.replace_old_counter.text(),self.replace_new_no.text(),self.replace_new_start.value(),self._replacement_actor(),self.replace_remark.text())
            self.replace_old_counter.clear();self.replace_new_no.clear();self.replace_new_start.setValue(0);self.replace_remark.clear()
            self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,'Change Electrode',str(exc))

    def _replacement_admin(self):
        from PySide6.QtWidgets import QInputDialog
        pin,ok=QInputDialog.getText(self,'Admin Settings','Admin PIN',QLineEdit.Password)
        return ok and pin=='12338'

    def replacement_add_slot(self):
        if not self._replacement_admin():return
        d=QDialog(self);d.setWindowTitle('Add Electrode Slot');layout=QFormLayout(d)
        fields={name:QLineEdit() for name in ('Machine','Station','Position','Diameter')}
        for name,edit in fields.items():layout.addRow(name,edit)
        buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);layout.addRow(buttons)
        if d.exec()!=QDialog.Accepted:return
        try:
            self._replacement_store().add_slot(*(fields[k].text() for k in fields));self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,'Master',str(exc))

    def replacement_toggle_slot(self):
        if not self._replacement_admin():return
        row=self.replace_master_table.currentRow()
        if row<0:return
        r=self.replace_master_table.item(row,0).data(Qt.UserRole)
        try:self._replacement_store().set_slot(r['id'],not r['enabled'],r['required']);self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,'Master',str(exc))

    def replacement_toggle_required(self):
        if not self._replacement_admin():return
        row=self.replace_master_table.currentRow()
        if row<0:return
        r=self.replace_master_table.item(row,0).data(Qt.UserRole)
        try:self._replacement_store().set_slot(r['id'],r['enabled'],not r['required']);self.refresh_replacement_all()
        except Exception as exc:QMessageBox.warning(self,'Master',str(exc))

    def export_replacement_csv(self):
        path,_=QFileDialog.getSaveFileName(self,'Export Electrode History','electrode_history.csv','CSV (*.csv)')
        if path:
            try:self._replacement_store().export_csv(path);QMessageBox.information(self,'Export','CSV exported')
            except Exception as exc:QMessageBox.warning(self,'Export',str(exc))

    def export_replacement_excel(self):
        path,_=QFileDialog.getSaveFileName(self,'Export Electrode','electrode_history.xlsx','Excel (*.xlsx)')
        if path:
            try:self._replacement_store().export_xlsx(path);QMessageBox.information(self,'Export','Excel exported')
            except Exception as exc:QMessageBox.warning(self,'Export',str(exc))

    # ---------------- Sample Register ----------------
    def _build_sample_register_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        title = QLabel("Sample Register - Prepare from Real Sample File + Live QAC")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)
        root.addWidget(QLabel(
            "อ่าน 2 แหล่งจริงเท่านั้น: Sample CSV/Excel + Live QAC | Exact Mapping only | "
            "เตรียมหลาย 2D ลง Queue ก่อน แล้วค่อย Register ทีเดียว"
        ))

        file_row = QHBoxLayout()
        self.btn_sample_import = QPushButton("Import Sample CSV / Excel")
        self.btn_sample_import.clicked.connect(self.browse_sample_excel)
        self.lbl_sample_file = QLabel("ยังไม่ได้เลือก Sample File")
        self.lbl_sample_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        file_row.addWidget(self.btn_sample_import)
        self.btn_sample_mapping = QPushButton("Open Mapping Master")
        self.btn_sample_mapping.setToolTip("เปิด config/QAC_Sample_Mapping_Master_SC1_MAPPED.xlsx เพื่อแก้ Mapping")
        self.btn_sample_mapping.clicked.connect(self.open_sample_mapping_master)
        file_row.addWidget(self.btn_sample_mapping)
        self.btn_sample_refresh = QPushButton("Refresh QAC Status")
        self.btn_sample_refresh.clicked.connect(self.sample_refresh_qac_status)
        file_row.addWidget(self.btn_sample_refresh)
        file_row.addWidget(self.lbl_sample_file, 1)
        root.addLayout(file_row)

        setup = QGroupBox("Batch Setup - วันที่ตั้งครั้งเดียวสำหรับ Queue ชุดนี้")
        setup_row = QHBoxLayout(setup)
        setup_row.addWidget(QLabel("Production Date"))
        self.sample_date = QDateEdit()
        self.sample_date.setCalendarPopup(True)
        self.sample_date.setDisplayFormat("yyyy-MM-dd")
        self.reference_dates.subscribe("sample_register")
        self.sample_date.setDate(QDate.fromString(self.reference_dates.date_for("sample_register") or QDate.currentDate().toString("yyyy-MM-dd"), "yyyy-MM-dd"))
        self.sample_date.dateChanged.connect(lambda d: self.reference_dates.set_module_date("sample_register", d.toString("yyyy-MM-dd")))
        setup_row.addWidget(self.sample_date)
        self.lbl_sample_date_lock = QLabel("Date ยังแก้ได้จนกว่าจะ Prepare รายการแรก")
        setup_row.addWidget(self.lbl_sample_date_lock)
        setup_row.addStretch()
        root.addWidget(setup)

        entry = QGroupBox("Prepare Sample")
        entry_root = QVBoxLayout(entry)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Line"))
        self.cmb_sample_line = make_searchable(QComboBox())
        self.cmb_sample_line.addItem("-- Line --", "")
        self.cmb_sample_line.currentIndexChanged.connect(self._refresh_sample_document_options)
        row1.addWidget(self.cmb_sample_line)
        row1.addWidget(QLabel("Model"))
        self.cmb_sample_model = make_searchable(QComboBox())
        self.cmb_sample_model.currentIndexChanged.connect(self._refresh_sample_target_process_options)
        row1.addWidget(self.cmb_sample_model)

        row1.addWidget(QLabel("Target Process / Sample (from Daily Document)"))
        self.cmb_sample_process = make_searchable(QComboBox())
        self.cmb_sample_process.currentIndexChanged.connect(self.sample_update_target_document)
        row1.addWidget(self.cmb_sample_process, 1)

        row1.addWidget(QLabel("Sample Type"))
        self.cmb_sample_type = QComboBox()
        self.cmb_sample_type.addItem("-- Select --", "")
        for value in ("INITIAL", "MIDDLE", "FINAL"):
            self.cmb_sample_type.addItem(value, value)
        row1.addWidget(self.cmb_sample_type)
        entry_root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("2D Column"))
        self.cmb_sample_2d_column = make_searchable(QComboBox())
        row2.addWidget(self.cmb_sample_2d_column)
        row2.addWidget(QLabel("2D Serial"))
        self.txt_sample_2d = QLineEdit()
        self.txt_sample_2d.setPlaceholderText("Scan / input 2D แล้วกด Enter")
        self.txt_sample_2d.returnPressed.connect(self.sample_lookup_and_prepare)
        row2.addWidget(self.txt_sample_2d, 1)
        self.btn_sample_find = QPushButton("Find Row")
        self.btn_sample_find.clicked.connect(self.sample_lookup_2d)
        row2.addWidget(self.btn_sample_find)
        self.btn_sample_prepare = QPushButton("Prepare / Add to List")
        self.btn_sample_prepare.clicked.connect(self.sample_prepare)
        row2.addWidget(self.btn_sample_prepare)
        entry_root.addLayout(row2)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Resolved QAC Document"))
        self.lbl_sample_target_document = QLabel("-")
        self.lbl_sample_target_document.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_sample_target_document.setStyleSheet("font-weight: 600;")
        target_row.addWidget(self.lbl_sample_target_document, 1)
        entry_root.addLayout(target_row)
        root.addWidget(entry)

        self.lbl_sample_match = QLabel("ยังไม่มี Sample row ที่ match")
        self.lbl_sample_match.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.lbl_sample_match)

        # Every lower pane is vertically resizable instead of being capped at a
        # fixed pixel height. Column widths remain user-resizable/persisted.
        self.sample_workspace_splitter = QSplitter(Qt.Vertical)
        self.sample_workspace_splitter.setChildrenCollapsible(False)
        self.sample_workspace_splitter.setHandleWidth(8)
        self.sample_workspace_splitter.setObjectName("sample_workspace_splitter")
        self.sample_workspace_splitter.setStyleSheet(
            "QSplitter::handle:vertical { background: #ccd7e5; "
            "border-top: 1px solid #a9b9ce; border-bottom: 1px solid #a9b9ce; }"
        )
        def _sample_pane():
            pane = QWidget()
            pane.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout = QVBoxLayout(pane)
            layout.setContentsMargins(0, 2, 0, 2)
            layout.setSpacing(3)
            self.sample_workspace_splitter.addWidget(pane)
            return layout

        sample_source_area = _sample_pane()
        sample_batch_area = _sample_pane()
        sample_values_area = _sample_pane()
        sample_log_area = _sample_pane()
        root.addWidget(self.sample_workspace_splitter, 1)
        self.sample_workspace_splitter.setStretchFactor(0, 1)
        self.sample_workspace_splitter.setStretchFactor(1, 2)
        self.sample_workspace_splitter.setStretchFactor(2, 3)
        self.sample_workspace_splitter.setStretchFactor(3, 1)
        self.sample_workspace_splitter.setSizes([90, 180, 270, 105])
        self.sample_workspace_splitter.setToolTip(
            "ลากแถบคั่นระหว่างตารางเพื่อปรับความสูงแต่ละส่วน"
        )

        # Matched sample is shown as one source row (headers across columns),
        # mirroring the real Sample CSV layout instead of Field/Value vertically.
        sample_source_area.addWidget(QLabel("Matched CSV Row — ลากขอบคอลัมน์หรือแถบคั่นเพื่อปรับขนาด"))
        self.tbl_sample_excel = QTableWidget(0, 0)
        self.tbl_sample_excel.setMinimumHeight(65)
        make_table_columns_resizable(self.tbl_sample_excel, persistence_key="sample_excel_row")
        sample_source_area.addWidget(self.tbl_sample_excel, 1)

        batch_title = QHBoxLayout()
        batch_title.addWidget(QLabel("Prepared List - ยังไม่เขียน QAC จนกด Register"))
        self.btn_sample_clear_batch = QPushButton("Clear Prepared List")
        self.btn_sample_clear_batch.clicked.connect(self.sample_clear_batch)
        self.btn_sample_register = QPushButton("REGISTER PREPARED LIST TO QAC")
        self.btn_sample_register.setEnabled(False)
        self.btn_sample_register.clicked.connect(self.sample_register_execute)
        batch_title.addStretch()
        batch_title.addWidget(self.btn_sample_clear_batch)
        batch_title.addWidget(self.btn_sample_register)
        sample_batch_area.addLayout(batch_title)

        self.tbl_sample_batch = QTableWidget(0, 10)
        self.tbl_sample_batch.setHorizontalHeaderLabels([
            "#", "2D Serial", "Model", "Target Process", "QAC Document", "Sample Type",
            "Source Row", "Master Slot", "Manual Fields", "Status"
        ])
        self.tbl_sample_batch.setMinimumHeight(95)
        self.tbl_sample_batch.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_sample_batch.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_sample_batch.currentCellChanged.connect(self._sample_batch_selection_changed)
        make_table_columns_resizable(self.tbl_sample_batch, persistence_key="sample_register_batch")
        sample_batch_area.addWidget(self.tbl_sample_batch, 1)

        detail_title = QHBoxLayout()
        detail_title.addWidget(QLabel("Prepared QAC Values - ชื่อ Field จาก QAC Live / ค่าแก้ไขได้ก่อน Register"))
        self.lbl_sample_detail = QLabel("เลือก Sample ใน Prepared List เพื่อดู/แก้ไขค่าที่จะกรอก QAC")
        self.lbl_sample_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_title.addStretch()
        detail_title.addWidget(self.lbl_sample_detail)
        sample_values_area.addLayout(detail_title)

        self.tbl_sample_prepared_values = QTableWidget(0, 7)
        self.tbl_sample_prepared_values.setHorizontalHeaderLabels([
            "QAC Document", "Section", "QAC Field", "Source", "Source Detail", "Value (Editable)", "Status"
        ])
        self.tbl_sample_prepared_values.setMinimumHeight(115)
        self.tbl_sample_prepared_values.itemChanged.connect(self._sample_prepared_value_item_changed)
        make_table_columns_resizable(self.tbl_sample_prepared_values, persistence_key="sample_prepared_values")
        sample_values_area.addWidget(self.tbl_sample_prepared_values, 1)
        self.sample_prepared_paste_shortcut = QShortcut(QKeySequence.Paste, self.tbl_sample_prepared_values)
        self.sample_prepared_paste_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.sample_prepared_paste_shortcut.activated.connect(self._paste_sample_prepared_value)
        self._sample_detail_loading = False

        self.lbl_sample_plan = QLabel("Prepared: 0 sample")
        self.lbl_sample_plan.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sample_log_area.addWidget(self.lbl_sample_plan)

        self.sample_log = QTextEdit()
        self.sample_log.setPlaceholderText("Sample execution log")
        self.sample_log.setReadOnly(True)
        self.sample_log.setMinimumHeight(72)
        sample_log_area.addWidget(self.sample_log, 1)

        self.sample_process_options = []
        self.sample_target_document = None
        try:
            self.sample_process_options = load_sample_process_options()
        except Exception as e:
            self.sample_log_msg(f"SAMPLE PROCESS MASTER ERROR | {e}")
        return w

    def sample_log_msg(self, text):
        if hasattr(self, "sample_log"):
            self.sample_log.append(str(text))
        self.audit.write("SAMPLE_REGISTER_LOG", message=str(text))

    def open_sample_mapping_master(self):
        if not self._permission_or_warn(6):
            return
        path = program_dir() / "config" / "QAC_Sample_Mapping_Master_SC1_MAPPED.xlsx"
        if not path.exists():
            QMessageBox.critical(self, "Sample Mapping", f"ไม่พบ Mapping Master:\n{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(path)])
            self.sample_log_msg(f"SAMPLE MAPPING OPEN | {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Sample Mapping", f"เปิด Mapping Master ไม่สำเร็จ:\n{exc}")

    def browse_sample_excel(self):
        if not self._permission_or_warn(6):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Sample File", str(program_dir()), "Sample Files (*.csv *.xlsx *.xlsm);;CSV (*.csv);;Excel (*.xlsx *.xlsm)"
        )
        if not path:
            return
        try:
            data = load_sample_excel(path)
            self.sample_excel = data
            self.sample_excel_row = None
            self.sample_plan = None
            self.btn_sample_register.setEnabled(bool(self.sample_batch_plans))
            self.lbl_sample_file.setText(
                f"{data.path} | sheet={data.sheet_name} | header row={data.header_row} | rows={len(data.rows)}"
            )
            self.cmb_sample_2d_column.clear()
            for header in data.headers:
                self.cmb_sample_2d_column.addItem(header, header)
            guess = guess_2d_column(data.headers)
            idx = self.cmb_sample_2d_column.findData(guess)
            if idx >= 0:
                self.cmb_sample_2d_column.setCurrentIndex(idx)
            self.tbl_sample_excel.clear()
            self.tbl_sample_excel.setRowCount(0)
            self.tbl_sample_excel.setColumnCount(0)
            self.lbl_sample_match.setText("Sample File พร้อมแล้ว - ระบุ Model / Target Process / Sample Type แล้ว Scan 2D")
            self.sample_log_msg(
                f"SAMPLE SOURCE READY | type={data.source_type} | sheet={data.sheet_name} | header={data.header_row} | rows={len(data.rows)} | columns={len(data.headers)}"
            )
            if data.source_type == "CSV":
                serial_idx = next((i for i, h in enumerate(data.header_names or [], start=1) if str(h).strip() == "Serial(Temporary)"), None)
                self.sample_log_msg(
                    f"SAMPLE CSV SCHEMA | two_row_header=YES | serial_column={serial_idx or '-'} | exact_identity_columns={len(data.column_profile or {})}"
                )
        except Exception as e:
            QMessageBox.critical(self, "Sample File", str(e))

    def _fill_sample_combo(self, combo, values, placeholder="-- Select --"):
        current = str(combo.currentData() or "")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(placeholder, "")
        for value in sorted({str(v).strip() for v in values if str(v).strip()}):
            combo.addItem(value, value)
        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _sample_line(self):
        """Sample owns its line selection; never consult Auto Register state."""
        if not hasattr(self, "cmb_sample_line"):
            return ""
        return str(self.cmb_sample_line.currentData() or "").strip()

    def _refresh_sample_document_options(self):
        """Build Sample choices from read-only master data, not another tab."""
        if not hasattr(self, "cmb_sample_model"):
            return
        current_line = self._sample_line()
        line_values = sorted({str(r.get("line") or "").strip() for r in self.daily_master_rows
                              if str(r.get("document_kind") or "") == "AUTO_CSV"
                              and "initial" in str(r.get("document_name") or "").casefold()
                              and str(r.get("line") or "").strip()})
        self._fill_sample_combo(self.cmb_sample_line, line_values, "-- Line --")
        if current_line:
            index = self.cmb_sample_line.findData(current_line)
            if index >= 0:
                self.cmb_sample_line.setCurrentIndex(index)
        line = self._sample_line()
        rows = [
            r for r in self.daily_master_rows
            if str(r.get("document_kind") or "") == "AUTO_CSV"
            and "initial" in str(r.get("document_name") or "").casefold()
            and (not line or str(r.get("line") or "").strip().casefold() == line.casefold())
        ]
        self._fill_sample_combo(self.cmb_sample_model, [r.get("model") for r in rows], "-- Model --")
        self._refresh_sample_target_process_options()

    def _refresh_sample_target_process_options(self):
        """Target Process options come only from Daily Document for current line/model."""
        if not hasattr(self, "cmb_sample_process"):
            return
        line = self._sample_line()
        model = str(self.cmb_sample_model.currentData() or "").strip()
        current_doc = ""
        data = self.cmb_sample_process.currentData()
        if isinstance(data, dict):
            current_doc = str(data.get("document_name") or "")
        targets = build_daily_sample_targets(
            self.daily_master_rows, line, model, self.sample_process_options
        ) if line and model else []
        self.cmb_sample_process.blockSignals(True)
        self.cmb_sample_process.clear()
        self.cmb_sample_process.addItem("-- Target Process from Daily Document --", None)
        restore_idx = -1
        for target in targets:
            display = str(target.get("display") or target.get("document_name") or "")
            self.cmb_sample_process.addItem(display, dict(target))
            if current_doc and str(target.get("document_name") or "").casefold() == current_doc.casefold():
                restore_idx = self.cmb_sample_process.count() - 1
        if restore_idx >= 0:
            self.cmb_sample_process.setCurrentIndex(restore_idx)
        self.cmb_sample_process.blockSignals(False)
        self.sample_update_target_document()

    def sample_update_target_document(self):
        if not hasattr(self, "lbl_sample_target_document"):
            return
        self.sample_target_document = None
        line = self._sample_line()
        model = str(self.cmb_sample_model.currentData() or "").strip()
        option = self.cmb_sample_process.currentData()
        if not line or not model or not isinstance(option, dict):
            self.lbl_sample_target_document.setText("-")
            self.lbl_sample_target_document.setStyleSheet("font-weight: 600;")
            return
        document = option.get("document")
        if not isinstance(document, dict):
            self.lbl_sample_target_document.setText("INVALID DAILY DOCUMENT TARGET")
            self.lbl_sample_target_document.setStyleSheet("font-weight: 600; color: #b00020;")
            return
        doc_name = str(document.get("document_name") or "").strip()
        if (str(document.get("line") or "").strip().casefold() != line.casefold()
                or str(document.get("model") or "").strip().casefold() != model.casefold()
                or not doc_name):
            self.lbl_sample_target_document.setText("DOCUMENT MASTER DOES NOT MATCH SAMPLE LINE / MODEL")
            self.lbl_sample_target_document.setStyleSheet("font-weight: 600; color: #b00020;")
            return
        self.sample_target_document = dict(document)
        self.lbl_sample_target_document.setText(doc_name)
        self.lbl_sample_target_document.setStyleSheet("font-weight: 600; color: #138a36;")

    def sample_refresh_qac_status(self):
        """Explicit user-requested scoped QAC status refresh, never a full tab scan."""
        if not self._ensure_local_action('Sample QAC Status'):
            return
        if not self._permission_or_warn(6):
            return
        if self.sample_status_worker and self.sample_status_worker.isRunning():
            return

        docs = []
        seen = set()
        if isinstance(self.sample_target_document, dict):
            name = str(self.sample_target_document.get("document_name") or "").strip()
            if name:
                seen.add(name.casefold())
                docs.append(dict(self.sample_target_document))
        for plan in self.sample_batch_plans:
            for doc in plan.get("documents") or []:
                name = str(doc.get("document_name") or "").strip()
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    # Prefer the Daily Document master row because the scanner
                    # expects the original document metadata.
                    master = next((r for r in self.daily_master_rows
                                   if str(r.get("document_name") or "").strip().casefold() == name.casefold()), None)
                    docs.append(dict(master or {"document_name": name}))

        if not docs:
            QMessageBox.information(
                self, "Sample Register",
                "เลือก Model / Target Process หรือ Prepare Sample ก่อน Refresh QAC Status"
            )
            return

        cfg = self.browser_cfg()
        if not cdp_ready(cfg["cdp_url"]):
            QMessageBox.warning(self, "Sample Register", "QAC Browser ยังไม่พร้อม")
            return

        production_date = self.sample_date.date().toString("yyyy-MM-dd")
        self.sample_log_msg(
            f"SAMPLE QAC STATUS REFRESH | date={production_date} | documents={len(docs)}"
        )
        self.btn_sample_refresh.setEnabled(False)
        self.sample_status_worker = DailyDocumentScanWorker(
            cfg["cdp_url"], production_date, docs
        )
        self.sample_status_worker.progress.connect(self.sample_log_msg)
        self.sample_status_worker.completed.connect(self._sample_status_refresh_completed)
        self.sample_status_worker.failed.connect(self._sample_status_refresh_failed)
        self.sample_status_worker.start()

    def _sample_status_refresh_completed(self, results):
        self.btn_sample_refresh.setEnabled(True)
        found = missing = 0
        for result in list(results or []):
            status = str(result.get("scan_status") or "ERROR")
            name = str(result.get("document_name") or "")
            task = str(result.get("task_id") or "")
            found_date = str(result.get("found_date") or "")
            if status == "FOUND":
                found += 1
            else:
                missing += 1
            self.sample_log_msg(
                f"SAMPLE QAC STATUS | {status} | date={found_date or '-'} | task={task or '-'} | {name}"
            )
        self.sample_log_msg(f"SAMPLE QAC STATUS DONE | FOUND={found} | MISSING={missing}")

    def _sample_status_refresh_failed(self, error):
        self.btn_sample_refresh.setEnabled(True)
        self.sample_log_msg(f"SAMPLE QAC STATUS ERROR | {error}")
        QMessageBox.warning(self, "Sample Register", str(error))

    def sample_lookup_and_prepare(self):
        if not self._permission_or_warn(6):
            return
        if not str(self.cmb_sample_type.currentData() or "").strip():
            QMessageBox.information(self, "Sample Register", "กรุณาระบุ Sample Type: INITIAL / MIDDLE / FINAL ก่อน")
            return
        if not self.sample_lookup_2d():
            return
        self.sample_prepare()

    def sample_lookup_2d(self):
        if not self._permission_or_warn(6):
            return
        if not self.sample_excel:
            QMessageBox.information(self, "Sample Register", "กรุณา Import Sample CSV / Excel ก่อน")
            return False
        serial = self.txt_sample_2d.text().strip()
        column = str(self.cmb_sample_2d_column.currentData() or self.cmb_sample_2d_column.currentText()).strip()
        try:
            row = find_sample_row(self.sample_excel, column, serial)
        except Exception as e:
            self.sample_excel_row = None
            self.lbl_sample_match.setText(str(e))
            self.tbl_sample_excel.clear()
            self.tbl_sample_excel.setRowCount(0)
            self.tbl_sample_excel.setColumnCount(0)
            QMessageBox.warning(self, "Sample 2D", str(e))
            return False
        self.sample_excel_row = row
        self.sample_plan = None
        model = str(self.cmb_sample_model.currentData() or "").strip()
        process_opt = self.cmb_sample_process.currentData()
        process_name = str((process_opt or {}).get("display") or "") if isinstance(process_opt, dict) else ""
        self.lbl_sample_match.setText(
            f"MATCHED | 2D={serial} | source row={row.get('source_row')} | Model={model or '-'} | "
            f"Target={process_name or '-'} | Sample={self.cmb_sample_type.currentText()}"
        )
        values = row.get("values") or {}
        # Show the matched Sample exactly as one horizontal source row.
        headers = list(self.sample_excel.headers)
        self.tbl_sample_excel.clear()
        self.tbl_sample_excel.setColumnCount(len(headers))
        self.tbl_sample_excel.setHorizontalHeaderLabels(headers)
        self.tbl_sample_excel.setRowCount(1)
        self.tbl_sample_excel.setVerticalHeaderLabels([str(row.get("source_row") or "")])
        for col, header in enumerate(headers):
            item = QTableWidgetItem(str(values.get(header, "") or ""))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.tbl_sample_excel.setItem(0, col, item)
        self.sample_log_msg(f"SAMPLE 2D MATCH | 2D={serial} | source_row={row.get('source_row')}")
        return True

    def sample_prepare(self):
        if not self._ensure_local_action('Sample Prepare'):
            return
        if not self._permission_or_warn(6):
            return
        sample_type = str(self.cmb_sample_type.currentData() or "").strip()
        line = self._sample_line()
        model = str(self.cmb_sample_model.currentData() or "").strip()
        process_opt = self.cmb_sample_process.currentData()
        if not line:
            QMessageBox.information(self, "Sample Register", "กรุณาเลือก Line ในหน้า Sample Register")
            return
        if not model:
            QMessageBox.information(self, "Sample Register", "กรุณาเลือก Model")
            return
        if not isinstance(process_opt, dict):
            QMessageBox.information(self, "Sample Register", "กรุณาเลือก Target Process / Sample")
            return
        if not sample_type:
            QMessageBox.information(self, "Sample Register", "กรุณาระบุ Sample Type: INITIAL / MIDDLE / FINAL")
            return
        self.sample_update_target_document()
        if not self.sample_target_document:
            QMessageBox.warning(self, "Sample Register", "ยังเลือก QAC Document จาก Master ไม่ได้ กรุณาตรวจ Model / Target Process")
            return
        if not self.sample_excel_row and not self.sample_lookup_2d():
            return
        if self.sample_prepare_worker and self.sample_prepare_worker.isRunning():
            return
        serial_2d = self.txt_sample_2d.text().strip()
        process_master = str(process_opt.get("process_master") or "")
        station = str(process_opt.get("station") or "")
        target_process = str(process_opt.get("display") or process_opt.get("document_name") or process_master)
        duplicate = any(
            str(p.get("serial_2d") or "").casefold() == serial_2d.casefold()
            and str(p.get("process_master") or "").casefold() == process_master.casefold()
            and str(p.get("station") or "").casefold() == station.casefold()
            and str(p.get("sample_type") or "").casefold() == sample_type.casefold()
            for p in self.sample_batch_plans
        )
        if duplicate:
            QMessageBox.warning(self, "Sample Register", f"2D {serial_2d} + {target_process} + {sample_type} อยู่ใน Prepared List แล้ว")
            return
        docs = [dict(self.sample_target_document)]
        payload = (
            self.sample_date.date().toString("yyyy-MM-dd"), docs,
            list(self.sample_excel.headers), dict(self.sample_excel_row.get("values") or {}),
            serial_2d, sample_type,
            list(self.sample_excel_row.get("raw_values") or []),
            [dict(p) for p in self.sample_batch_plans],
            dict(self.sample_excel.column_profile or {}),
            model, process_master, station, target_process,
        )
        self.btn_sample_prepare.setEnabled(False)
        self.btn_sample_register.setEnabled(False)
        self.sample_log_msg(
            f"SAMPLE PREPARE REQUEST | 2D={serial_2d} | model={model} | target={target_process} | "
            f"sample={sample_type} | document={self.sample_target_document.get('document_name')}"
        )
        self._pending_sample_prepare_payload = payload
        self.ensure_qac_module("sample_register")

    def _start_sample_prepare_worker(self, production_date, docs, headers, row_values, serial_2d, sample_type, raw_values, reserved_plans, source_profile, model, process_master, station, target_process):
        cfg = self.browser_cfg()
        if not cdp_ready(cfg["cdp_url"]):
            self._sample_prepare_failed("QAC Browser ยังไม่พร้อม")
            return
        self.sample_prepare_worker = SamplePrepareWorker(
            cfg["cdp_url"], production_date, docs, headers, row_values, serial_2d, sample_type,
            raw_values, reserved_plans, source_profile,
            model=model, process_master=process_master, station=station, target_process=target_process,
            line=self._sample_line(),
        )
        self.sample_prepare_worker.progress.connect(self.sample_log_msg)
        self.sample_prepare_worker.completed.connect(self._sample_prepare_completed)
        self.sample_prepare_worker.failed.connect(self._sample_prepare_failed)
        self.sample_prepare_worker.start()

    def _sample_prepare_completed(self, plan):
        self.btn_sample_prepare.setEnabled(True)
        if not plan:
            return

        # The prepared plan includes the live scan. Ask once without discarding
        # the scanned data or silently skipping an incomplete earlier slot.
        partials = list(plan.get("partial_slot_warnings") or [])
        if partials:
            from app.sample_register import authorize_partial_slot_resume
            # Only offer the latest partial slot immediately preceding the next
            # available common empty slot. Older partial slots may belong to
            # previous samples and must not be offered indiscriminately.
            next_slot = int(plan.get("master_slot") or 0)
            candidates = [p for p in partials if int(p.get("slot") or 0) < next_slot]
            latest = max((int(p.get("slot") or 0) for p in candidates), default=0)
            selected = [p for p in candidates if int(p.get("slot") or 0) == latest]
            if selected and len(selected) == len(plan.get("documents") or []):
                lines = []
                for part in selected:
                    fields = ", ".join(str(x) for x in part.get("saved_fields") or [])
                    lines.append(f"{part.get('document_name')} | Slot {latest}: "
                                 f"{part.get('saved_count')}/{part.get('total_count')} saved\n{fields}")
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("Sample — ใช้ Partial Slot เดิมหรือไม่?")
                box.setText(f"ต้องการใช้ Slot {latest} ต่อ สำหรับ 2D {plan.get('serial_2d')} หรือไม่?")
                box.setInformativeText("\n".join(lines) +
                    "\n\nเลือกใช้ Slot เดิม = ยืนยันด้วยตนเองว่าเป็น 2D นี้ "
                    "โปรแกรมจะข้ามผลที่บันทึกแล้วและเติมเฉพาะช่องว่าง "
                    "ถ้าค่าเดิมขัดแย้งจะหยุดโดยไม่เขียนทับ "
                    "(การยืนยันของผู้ใช้ไม่ใช่หลักฐานจาก QAC ว่าเป็น 2D เดียวกัน)")
                resume = box.addButton(f"ใช้ Slot {latest} เดิม / เติมเฉพาะช่องว่าง", QMessageBox.AcceptRole)
                newer = box.addButton(f"ไม่ใช้ / เลือก Slot {next_slot}", QMessageBox.ActionRole)
                box.addButton("ยกเลิก", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is resume:
                    try:
                        plan = authorize_partial_slot_resume(plan, latest, operator_confirmed=True)
                    except Exception as exc:
                        QMessageBox.warning(self, "Resume Slot", str(exc))
                        self.sample_log_msg(f"SAMPLE RESUME BLOCKED | {exc}")
                        return
                    self.sample_log_msg(f"SAMPLE PARTIAL SLOT RESUME APPROVED | slot={latest} | 2D={plan.get('serial_2d')}")
                elif box.clickedButton() is newer:
                    self.sample_log_msg(f"SAMPLE PARTIAL SLOT SKIPPED | slot={latest} | next={next_slot}")
                else:
                    self.sample_log_msg(f"SAMPLE PARTIAL SLOT CANCELLED | slot={latest}")
                    return
            else:
                # A multi-document batch must use the same absolute slot in all
                # documents, so do not offer an unsafe single-document resume.
                self.sample_log_msg("SAMPLE PARTIAL SLOT | no common resume candidate across documents")

        # One review modal shows the complete Live QAC ↔ Sample mapping. Existing
        # mapped values are read-only; only missing values are editable.
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Review Sample Mapping - {plan.get('serial_2d')}")
        dialog.resize(1120, 720)
        root = QVBoxLayout(dialog)
        root.addWidget(QLabel(
            f"2D: {plan.get('serial_2d')}    Model: {plan.get('model')}    "
            f"Target: {plan.get('target_process')}    Sample: {plan.get('sample_type')}    "
            f"Master Slot: {plan.get('master_slot')}\n"
            "ค่าที่มาจาก Sample/QAC จริงจะแสดงไว้แล้ว; ช่องที่ยังไม่มีให้กรอกก่อนกด OK"
        ))

        table = QTableWidget(0, 7)
        table.setHorizontalHeaderLabels(["QAC Document", "Section", "QAC Field", "Source", "Source Detail", "Value", "Status"])
        manual_editors = {}
        for doc in plan.get("documents") or []:
            doc_name = str(doc.get("document_name") or "")
            for field in doc.get("schema") or []:
                row = table.rowCount(); table.insertRow(row)
                value = str(field.get("value") or "")
                source = str(field.get("source") or "")
                values = [doc_name, str(field.get("section") or ""), str(field.get("label") or ""), source,
                          str(field.get("excel_column") or ""), value, "READY" if value else "INPUT REQUIRED"]
                for col, txt in enumerate(values):
                    item = QTableWidgetItem(txt)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(row, col, item)
                # Time is operator-editable even when sourced from CSV.
                # It remains the single source for the Time result and QAC trace comment.
                if str(field.get("label") or "").strip().casefold() == "time" and value:
                    edit = QLineEdit(value)
                    edit.setPlaceholderText("HH.MM (แก้ไขเวลาได้)")
                    table.setCellWidget(row, 5, edit)
                    manual_editors[str(field.get("key") or "")] = (edit, "Time", "TIME")
                    continue
                if not value:
                    key = str(field.get("key") or "")
                    label = str(field.get("label") or field.get("key") or "")
                    # QAC OK/NG fields must be an explicit choice.  Never accept
                    # free text here because the live QAC only has OK / NG actions.
                    if source == "MANUAL_OK_NG" or str(field.get("input_format") or "") == "4":
                        edit = QComboBox()
                        edit.addItem("-- เลือก --", "")
                        edit.addItem("OK", "OK")
                        edit.addItem("NG", "NG")
                        table.setCellWidget(row, 5, edit)
                        manual_editors[key] = (edit, label, "CHOICE_OK_NG")
                    else:
                        edit = QLineEdit()
                        edit.setPlaceholderText("กรอกค่าที่ไม่มีใน Sample (รองรับ Ctrl+V)")
                        edit.setClearButtonEnabled(True)
                        table.setCellWidget(row, 5, edit)
                        manual_editors[key] = (edit, label, "TEXT")
        make_table_columns_resizable(table, persistence_key="sample_mapping_review")
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(table, 1)

        map_row = QHBoxLayout()
        map_hint = QLabel("เลือกแถว QAC Field → Set Source / Mapping → SMP Column → เลือกคอลัมน์ CSV จริง (เช่น HD E-rode (U)/(L)) → Save; Mapping จะจดจำแยกตามชื่อเอกสารและ QAC Field")
        map_hint.setWordWrap(True)
        map_row.addWidget(map_hint, 1)
        btn_map_source = QPushButton("Set Source / Mapping")
        btn_remove_map = QPushButton("Remove Local Map")
        map_row.addWidget(btn_map_source)
        map_row.addWidget(btn_remove_map)
        root.addLayout(map_row)

        def _selected_mapping_identity():
            row = table.currentRow()
            if row < 0:
                QMessageBox.warning(dialog, "Sample Mapping", "กรุณาเลือก QAC Field ก่อน")
                return None
            return (
                str(table.item(row, 0).text() if table.item(row, 0) else "").strip(),
                str(table.item(row, 1).text() if table.item(row, 1) else "").strip(),
                str(table.item(row, 2).text() if table.item(row, 2) else "").strip(),
                row,
            )

        def _map_selected_source():
            identity = _selected_mapping_identity()
            if not identity:
                return
            doc_name, section, qac_field, row = identity
            chooser = QDialog(dialog)
            chooser.setWindowTitle(f"Source Mapping: {section} / {qac_field}")
            chooser.resize(780, 300)
            lay = QVBoxLayout(chooser)
            lay.addWidget(QLabel(f"QAC: {doc_name} | {section} | {qac_field}"))
            form = QFormLayout()
            source_type = QComboBox()
            for label, key in (
                ("SMP Column", "SMP_COLUMN"),
                ("Electrode No. (active ISSUE in Electrode Control)", "ELECTRODE_NO"),
                ("Electrode Shot", "ELECTRODE_SHOT"),
                ("Manual Input", "MANUAL"),
                ("Fixed Value", "FIXED"),
                ("Ignore", "IGNORE"),
            ):
                source_type.addItem(label, key)
            form.addRow("Source Type", source_type)

            source_column = make_searchable(QComboBox())
            profile = dict(getattr(self.sample_excel, "column_profile", {}) or {}) if self.sample_excel else {}
            for colno in sorted(profile):
                group, name = profile[colno]
                label = f"{name}  [CSV #{colno}; {group}]" if group else f"{name}  [CSV #{colno}]"
                source_column.addItem(label, (int(colno), str(group or ""), str(name or "")))
            form.addRow("SMP Column", source_column)

            position_combo = make_searchable(QComboBox())
            try:
                from app.electrode_issue_return import IssueReturnStore
                positions = IssueReturnStore(program_dir() / "database" / "electrode_issue_return_local.sqlite3").destinations()
            except Exception:
                positions = []
            for pos in positions:
                position_combo.addItem(f"{pos.get('machine')} / {pos.get('station') or '-'} / {pos.get('position')} / {pos.get('diameter')}", dict(pos))
            form.addRow("Machine / Position", position_combo)

            fixed_value = QLineEdit()
            fixed_value.setPlaceholderText("ใช้เฉพาะ Source Type = Fixed Value")
            form.addRow("Fixed Value", fixed_value)
            lay.addLayout(form)

            hint = QLabel("Electrode No. อ่านจาก Electrode Issue/Return Ledger เฉพาะรายการ ISSUED ของ Line/Machine/Position ที่มีเพียงหนึ่งรายการเท่านั้น")
            hint.setWordWrap(True); lay.addWidget(hint)
            box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            box.accepted.connect(chooser.accept); box.rejected.connect(chooser.reject); lay.addWidget(box)
            if chooser.exec() != QDialog.Accepted:
                return

            kind = str(source_type.currentData() or "SMP_COLUMN")
            group = name = machine = position = station = value = ""
            colno = None
            if kind == "SMP_COLUMN":
                data = source_column.currentData()
                if not data:
                    QMessageBox.warning(dialog, "Sample Mapping", "Sample file นี้ไม่มี source column profile")
                    return
                colno, group, name = data
            elif kind in {"ELECTRODE_NO", "ELECTRODE_SHOT"}:
                pos = position_combo.currentData()
                if not isinstance(pos, dict):
                    QMessageBox.warning(dialog, "Sample Mapping", "ยังไม่มี Machine / Position Master สำหรับ Electrode")
                    return
                machine, position = str(pos.get("machine") or ""), str(pos.get("position") or "")
                station = str(pos.get("station") or "")
                selected_electrode_slot = pos
            elif kind == "FIXED":
                value = fixed_value.text().strip()

            try:
                save_override(
                    doc_name, section, qac_field, group, name,
                    source_type=kind, source_value=value,
                    source_machine=machine, source_position=position, source_station=station,
                )
            except Exception as exc:
                QMessageBox.critical(dialog, "Sample Mapping", f"บันทึก Local Mapping ไม่สำเร็จ:\n{exc}")
                return

            resolved = ""
            detail = kind
            if kind == "SMP_COLUMN":
                raw_values = list((self.sample_excel_row or {}).get("raw_values") or [])
                resolved = str(raw_values[colno - 1]).strip() if colno and 0 < colno <= len(raw_values) else ""
                detail = f"column {colno} {group}/{name}".strip()
            elif kind == "FIXED":
                resolved = value; detail = "Fixed"
            elif kind == "MANUAL":
                detail = "Manual"
            elif kind == "IGNORE":
                detail = "Ignore"
            elif kind in {"ELECTRODE_NO", "ELECTRODE_SHOT"}:
                detail = f"{machine} / {position}"
                try:
                    from app.electrode_issue_return import IssueReturnStore
                    store = IssueReturnStore(program_dir() / "database" / "electrode_issue_return_local.sqlite3")
                    line = str(selected_electrode_slot.get("line") or "").strip()
                    active = [r for r in store.history() if r.get("state") == "ISSUED"
                              and str(r.get("line") or "").casefold() == line.casefold()
                              and str(r.get("machine") or "").casefold() == machine.casefold()
                              and str(r.get("position") or "").casefold() == position.casefold()]
                    if kind == "ELECTRODE_NO" and len(active) == 1:
                        resolved = active[0]["barcode"]
                except Exception:
                    resolved = ""

            table.item(row, 3).setText(kind)
            table.item(row, 4).setText(detail)
            editor = table.cellWidget(row, 5)
            if isinstance(editor, QLineEdit): editor.setText(resolved)
            elif isinstance(editor, QComboBox) and resolved.upper() in {"OK", "NG"}:
                idx = editor.findData(resolved.upper())
                if idx >= 0: editor.setCurrentIndex(idx)
            elif table.item(row, 5): table.item(row, 5).setText(resolved)
            table.item(row, 6).setText("MAPPING SAVED" if resolved or kind in {"MANUAL", "IGNORE"} else "MAPPING SAVED / SOURCE NOT READY")
            for doc in plan.get("documents") or []:
                if str(doc.get("document_name") or "").strip().casefold() != doc_name.casefold(): continue
                for field in doc.get("schema") or []:
                    if (str(field.get("section") or "").strip().casefold() == section.casefold()
                            and str(field.get("label") or "").strip().casefold() == qac_field.casefold()):
                        field["source"] = kind; field["excel_column"] = detail; field["value"] = resolved
            self.sample_log_msg(f"SAMPLE SOURCE SAVE | document={doc_name} | field={section}/{qac_field} | source={kind} | detail={detail}")

        def _remove_selected_source():
            identity = _selected_mapping_identity()
            if not identity:
                return
            doc_name, section, qac_field, row = identity
            try:
                delete_override(doc_name, section, qac_field)
            except Exception as exc:
                QMessageBox.critical(dialog, "Sample Mapping", f"ลบ Local Mapping ไม่สำเร็จ:\n{exc}")
                return
            table.item(row, 6).setText("LOCAL MAP REMOVED - Prepare again")
            self.sample_log_msg(f"SAMPLE LOCAL MAP DELETE | document={doc_name} | section={section} | field={qac_field}")

        btn_map_source.clicked.connect(_map_selected_source)
        btn_remove_map.clicked.connect(_remove_selected_source)

        # Explicit Ctrl+V support for cell widgets. QLineEdit already supports
        # paste natively; this dialog shortcut also lets OK/NG comboboxes accept
        # clipboard text "OK" or "NG" without turning them into free-text fields.
        paste_shortcut = QShortcut(QKeySequence.Paste, dialog)
        paste_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        def paste_review_value():
            focus = QApplication.focusWidget()
            clip = QApplication.clipboard().text()
            if isinstance(focus, QLineEdit):
                focus.insert(clip)
                return
            if isinstance(focus, QComboBox):
                wanted = str(clip or "").strip().upper()
                if wanted in {"OK", "NG"}:
                    idx = focus.findData(wanted)
                    if idx >= 0:
                        focus.setCurrentIndex(idx)
        paste_shortcut.activated.connect(paste_review_value)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            self.sample_log_msg("SAMPLE PREPARE CANCELLED | operator cancelled mapping review")
            self.btn_sample_register.setEnabled(bool(self.sample_batch_plans))
            return

        manual_values = {}
        empty_labels = []
        for key, (editor, label, editor_type) in manual_editors.items():
            if editor_type == "CHOICE_OK_NG":
                value = str(editor.currentData() or "").strip()
            else:
                value = editor.text().strip()
            if not value:
                empty_labels.append(label)
            if editor_type == "TIME" and not re.fullmatch(r"(?:[01]?\d|2[0-3])[.:][0-5]\d", value):
                QMessageBox.warning(self, "Sample Time", "รูปแบบเวลาไม่ถูกต้อง: ต้องเป็น HH.MM หรือ HH:MM")
                return
            manual_values[key] = value
        if empty_labels:
            QMessageBox.warning(self, "Sample Register", "ข้อมูลยังไม่ครบ:\n" + "\n".join(empty_labels[:50]))
            self.btn_sample_register.setEnabled(bool(self.sample_batch_plans))
            return
        if manual_values:
            plan = apply_manual_values(plan, manual_values)

        self.sample_plan = plan
        plan["manual_field_count"] = len(manual_values)
        plan["source_row"] = (self.sample_excel_row or {}).get("source_row")
        self.sample_batch_plans.append(plan)
        self._refresh_sample_batch_table()
        self.btn_sample_register.setEnabled(True)
        self.sample_date.setEnabled(False)
        self.lbl_sample_date_lock.setText(f"Locked for this Prepared List: {plan.get('production_date')}")
        docs = len(plan.get("documents") or [])
        slot = plan.get("master_slot")
        self.lbl_sample_plan.setText(
            f"Prepared: {len(self.sample_batch_plans)} sample | Last 2D={plan.get('serial_2d')} | "
            f"Model={plan.get('model')} | Target={plan.get('target_process')} | Sample={plan.get('sample_type')} | Slot={slot}"
        )
        self.sample_log_msg(
            f"SAMPLE QUEUED | count={len(self.sample_batch_plans)} | 2D={plan.get('serial_2d')} | "
            f"model={plan.get('model')} | target={plan.get('target_process')} | sample={plan.get('sample_type')} | "
            f"master_slot={slot} | pages={docs} | manual={len(manual_values)}"
        )
        self.txt_sample_2d.clear()
        self.txt_sample_2d.setFocus()
        self.cmb_sample_type.setCurrentIndex(0)
        self.sample_excel_row = None
        self.tbl_sample_excel.clear()
        self.tbl_sample_excel.setRowCount(0)
        self.tbl_sample_excel.setColumnCount(0)
        self.lbl_sample_match.setText("Prepared แล้ว - Scan 2D ตัวถัดไปและระบุ Sample Type")

    def _sample_prepare_failed(self, error):
        self.btn_sample_prepare.setEnabled(True)
        self.btn_sample_register.setEnabled(bool(self.sample_batch_plans))
        self.sample_plan = None
        self.sample_log_msg(f"SAMPLE PREPARE ERROR | {error}")
        QMessageBox.critical(self, "Sample Prepare", str(error))

    def _paste_sample_prepared_value(self):
        if not hasattr(self, "tbl_sample_prepared_values"):
            return
        table = self.tbl_sample_prepared_values
        row = table.currentRow()
        col = table.currentColumn()
        if row < 0:
            return
        if col != 5:
            col = 5
            table.setCurrentCell(row, col)
        clip = str(QApplication.clipboard().text() or "").strip()
        widget = table.cellWidget(row, 5)
        if isinstance(widget, QComboBox):
            wanted = clip.upper()
            idx = widget.findData(wanted)
            if idx >= 0:
                widget.setCurrentIndex(idx)
            return
        item = table.item(row, 5)
        if item is not None:
            item.setText(clip)

    def _sample_batch_selection_changed(self, current_row, current_col, previous_row, previous_col):
        self._load_sample_prepared_values(current_row)

    def _clear_sample_prepared_values(self):
        if not hasattr(self, "tbl_sample_prepared_values"):
            return
        self._sample_detail_loading = True
        try:
            self.tbl_sample_prepared_values.clearContents()
            self.tbl_sample_prepared_values.setRowCount(0)
            if hasattr(self, "lbl_sample_detail"):
                self.lbl_sample_detail.setText("เลือก Sample ใน Prepared List เพื่อดู/แก้ไขค่าที่จะกรอก QAC")
        finally:
            self._sample_detail_loading = False

    def _load_sample_prepared_values(self, queue_row):
        if not hasattr(self, "tbl_sample_prepared_values"):
            return
        if queue_row is None or queue_row < 0 or queue_row >= len(self.sample_batch_plans):
            self._clear_sample_prepared_values()
            return
        plan = self.sample_batch_plans[queue_row]
        self._sample_detail_loading = True
        try:
            table = self.tbl_sample_prepared_values
            table.clearContents()
            table.setRowCount(0)
            self.lbl_sample_detail.setText(
                f"2D={plan.get('serial_2d')} | Model={plan.get('model')} | "
                f"Sample={plan.get('sample_type')} | Slot={plan.get('master_slot')}"
            )
            for doc_index, doc in enumerate(plan.get("documents") or []):
                doc_name = str(doc.get("document_name") or "")
                for field_index, field in enumerate(doc.get("schema") or []):
                    row = table.rowCount()
                    table.insertRow(row)
                    source = str(field.get("source") or "")
                    source_detail = str(field.get("excel_column") or "")
                    value = str(field.get("value") or "")
                    status = "EDITED" if field.get("value_overridden") else ("READY" if value else "MISSING")
                    base_values = [
                        doc_name, str(field.get("section") or ""), str(field.get("label") or ""),
                        source, source_detail, value, status,
                    ]
                    for col, txt in enumerate(base_values):
                        item = QTableWidgetItem(txt)
                        if col != 5:
                            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                        item.setData(Qt.UserRole, (queue_row, doc_index, field_index))
                        table.setItem(row, col, item)

                    input_format = str(field.get("input_format") or "")
                    if input_format == "4" or source == "MANUAL_OK_NG":
                        combo = QComboBox()
                        combo.addItem("-- เลือก --", "")
                        combo.addItem("OK", "OK")
                        combo.addItem("NG", "NG")
                        idx = combo.findData(value.upper())
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                        combo.currentIndexChanged.connect(
                            lambda _idx, qr=queue_row, di=doc_index, fi=field_index, cb=combo:
                                self._sample_prepared_combo_changed(qr, di, fi, cb)
                        )
                        table.setCellWidget(row, 5, combo)
                    elif input_format == "3":
                        combo = QComboBox()
                        combo.addItem("-- เลือก --", "")
                        for sample_value in ("INITIAL", "MIDDLE", "FINAL"):
                            combo.addItem(sample_value, sample_value)
                        idx = combo.findData(value.upper())
                        if idx >= 0:
                            combo.setCurrentIndex(idx)
                        combo.currentIndexChanged.connect(
                            lambda _idx, qr=queue_row, di=doc_index, fi=field_index, cb=combo:
                                self._sample_prepared_combo_changed(qr, di, fi, cb)
                        )
                        table.setCellWidget(row, 5, combo)
        finally:
            self._sample_detail_loading = False

    def _sample_prepared_combo_changed(self, queue_row, doc_index, field_index, combo):
        if self._sample_detail_loading:
            return
        if queue_row < 0 or queue_row >= len(self.sample_batch_plans):
            return
        try:
            plan = self.sample_batch_plans[queue_row]
            field = plan["documents"][doc_index]["schema"][field_index]
            new_value = str(combo.currentData() or "").strip()
            old_value = str(field.get("value") or "")
            if new_value == old_value:
                return
            if "original_value" not in field:
                field["original_value"] = old_value
            field["value"] = new_value
            field["value_overridden"] = True
            if str(field.get("input_format") or "") == "3" and new_value:
                plan["sample_type"] = new_value
            self.sample_log_msg(
                f"SAMPLE PREPARED EDIT | 2D={plan.get('serial_2d')} | "
                f"{field.get('section')}/{field.get('label')} | {old_value} -> {new_value}"
            )
            self._refresh_sample_batch_table(select_row=queue_row)
        except Exception as exc:
            self.sample_log_msg(f"SAMPLE PREPARED EDIT ERROR | {exc}")

    def _sample_prepared_value_item_changed(self, item):
        if self._sample_detail_loading or item is None or item.column() != 5:
            return
        ref = item.data(Qt.UserRole)
        if not isinstance(ref, tuple) or len(ref) != 3:
            return
        queue_row, doc_index, field_index = ref
        if queue_row < 0 or queue_row >= len(self.sample_batch_plans):
            return
        try:
            plan = self.sample_batch_plans[queue_row]
            field = plan["documents"][doc_index]["schema"][field_index]
            new_value = str(item.text() or "").strip()
            old_value = str(field.get("value") or "")
            if new_value == old_value:
                return
            if "original_value" not in field:
                field["original_value"] = old_value
            field["value"] = new_value
            field["value_overridden"] = True
            self.sample_log_msg(
                f"SAMPLE PREPARED EDIT | 2D={plan.get('serial_2d')} | "
                f"{field.get('section')}/{field.get('label')} | {old_value} -> {new_value}"
            )
            self._load_sample_prepared_values(queue_row)
        except Exception as exc:
            self.sample_log_msg(f"SAMPLE PREPARED EDIT ERROR | {exc}")

    def _sample_slot_capacity(self, plan):
        """Smallest verified QAC result-slot capacity across the prepared fields."""
        capacities = []
        for doc in plan.get("documents") or []:
            for field in doc.get("schema") or []:
                slots = field.get("slots") or []
                if slots:
                    capacities.append(len(slots))
        return min(capacities) if capacities else max(1, int(plan.get("master_slot") or 1))

    def _sample_change_prepared_slot(self, row, requested_slot):
        """Update only the prepared plan; QAC is always checked at Register time."""
        if row < 0 or row >= len(self.sample_batch_plans):
            return
        if (self.sample_register_worker and self.sample_register_worker.isRunning()) or (
            self.sample_prepare_worker and self.sample_prepare_worker.isRunning()
        ):
            self._refresh_sample_batch_table(select_row=row)
            return
        plan = self.sample_batch_plans[row]
        previous = int(plan.get("master_slot") or 0)
        requested_slot = int(requested_slot)
        capacity = self._sample_slot_capacity(plan)
        if requested_slot < 1 or requested_slot > capacity:
            QMessageBox.warning(self, "Sample Slot", f"Slot {requested_slot} อยู่นอกช่วง QAC 1–{capacity}")
            self._refresh_sample_batch_table(select_row=row)
            return
        doc_names = {str(d.get("document_name") or "").casefold() for d in plan.get("documents") or []}
        for j, other in enumerate(self.sample_batch_plans):
            if j == row or int(other.get("master_slot") or 0) != requested_slot:
                continue
            other_docs = {str(d.get("document_name") or "").casefold() for d in other.get("documents") or []}
            if doc_names & other_docs and str(other.get("production_date")) == str(plan.get("production_date")):
                QMessageBox.warning(self, "Sample Slot", f"Slot {requested_slot} ถูกจองโดย 2D {other.get('serial_2d')} ในเอกสารเดียวกันแล้ว")
                self._refresh_sample_batch_table(select_row=row)
                return
        if requested_slot == previous:
            return
        plan["master_slot"] = requested_slot
        for doc in plan.get("documents") or []:
            doc["next_slot"] = requested_slot
        self.sample_log_msg(
            f"SAMPLE SLOT OVERRIDE | 2D={plan.get('serial_2d')} | {previous} -> {requested_slot} | "
            "QAC live occupancy to be verified before writing"
        )
        self._refresh_sample_batch_table(select_row=row)

    def _refresh_sample_batch_table(self, select_row=None):
        if not hasattr(self, "tbl_sample_batch"):
            return
        previous_row = self.tbl_sample_batch.currentRow() if select_row is None else select_row
        self.tbl_sample_batch.setRowCount(0)
        for idx, plan in enumerate(self.sample_batch_plans, start=1):
            row = self.tbl_sample_batch.rowCount(); self.tbl_sample_batch.insertRow(row)
            qac_doc = " ; ".join(str(d.get("document_name") or "") for d in (plan.get("documents") or []))
            values = [
                idx, plan.get("serial_2d", ""), plan.get("model", ""), plan.get("target_process", ""),
                qac_doc, plan.get("sample_type", ""), plan.get("source_row", ""), plan.get("master_slot", ""),
                plan.get("manual_field_count", 0), "PREPARED",
            ]
            for col, value in enumerate(values):
                if col == 7:
                    slot_editor = QSpinBox(self.tbl_sample_batch)
                    slot_editor.setMinimum(1)
                    slot_editor.setMaximum(self._sample_slot_capacity(plan))
                    slot_editor.setValue(int(plan.get("master_slot") or 1))
                    slot_editor.setToolTip("เลือก Master Slot สำหรับ 2D นี้; QAC จะตรวจ Slot จริงก่อน Register")
                    slot_editor.valueChanged.connect(
                        lambda slot, queue_row=row: self._sample_change_prepared_slot(queue_row, slot)
                    )
                    self.tbl_sample_batch.setCellWidget(row, col, slot_editor)
                    continue
                item = QTableWidgetItem(str(value)); item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.tbl_sample_batch.setItem(row, col, item)
        has_queue = bool(self.sample_batch_plans)
        if has_queue:
            row_to_select = previous_row if previous_row is not None and previous_row >= 0 else len(self.sample_batch_plans) - 1
            row_to_select = min(row_to_select, len(self.sample_batch_plans) - 1)
            self.tbl_sample_batch.setCurrentCell(row_to_select, 0)
            self.tbl_sample_batch.selectRow(row_to_select)
            self._load_sample_prepared_values(row_to_select)
        else:
            self._clear_sample_prepared_values()
        if hasattr(self, "sample_date"):
            self.sample_date.setEnabled(not has_queue)
            self.lbl_sample_date_lock.setText(
                f"Locked for this Prepared List: {self.sample_date.date().toString('yyyy-MM-dd')}" if has_queue
                else "Date ยังแก้ได้จนกว่าจะ Prepare รายการแรก"
            )

    def sample_clear_batch(self):
        if not self._permission_or_warn(6):
            return
        if not self.sample_batch_plans:
            return
        ans = QMessageBox.question(
            self, "Clear Prepared List",
            f"ล้าง Sample ที่ Prepare ไว้ {len(self.sample_batch_plans)} รายการหรือไม่?\nยังไม่มีข้อมูลใดถูกเขียนลง QAC",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if ans != QMessageBox.Yes:
            return
        self.sample_batch_plans.clear()
        self.sample_plan = None
        self._refresh_sample_batch_table()
        self.btn_sample_register.setEnabled(False)
        self.lbl_sample_plan.setText("Prepared: 0 sample")
        self.sample_log_msg("SAMPLE QUEUE CLEARED | QAC unchanged | Date unlocked")

    def sample_register_execute(self):
        if not self._ensure_local_action('Sample Register'):
            return
        if not self._permission_or_warn(6):
            return
        if not self.sample_batch_plans:
            QMessageBox.warning(self, "Sample Register", "ยังไม่มี Sample ที่ Prepare ไว้")
            return
        if self.sample_register_worker and self.sample_register_worker.isRunning():
            return
        plans = [dict(p) for p in self.sample_batch_plans]
        lines = [
            f"{i}. {p.get('serial_2d')} | {p.get('model')} | {p.get('target_process')} | "
            f"{p.get('sample_type')} | Slot {p.get('master_slot')}"
            for i, p in enumerate(plans, start=1)
        ]
        answer = QMessageBox.question(
            self, "Confirm Prepared Sample List",
            f"Production Date: {self.sample_date.date().toString('yyyy-MM-dd')}\nPrepared Samples: {len(plans)}\n\n" +
            "\n".join(lines[:30]) +
            "\n\nโปรแกรมจะ re-check QAC live ก่อนกรอกแต่ละ Sample และหยุดทันทีหาก slot/state ไม่ตรง ต้องการเริ่มหรือไม่?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        self.btn_sample_register.setEnabled(False)
        self.btn_sample_prepare.setEnabled(False)
        self.sample_register_worker = SampleRegisterWorker(self.browser_cfg()["cdp_url"], plans)
        self.sample_register_worker.progress.connect(self.sample_log_msg)
        self.sample_register_worker.completed.connect(self._sample_register_completed)
        self.sample_register_worker.failed.connect(self._sample_register_failed)
        self.sample_register_worker.start()

    def _sample_register_completed(self, result):
        self.btn_sample_prepare.setEnabled(True)
        self.btn_sample_register.setEnabled(False)
        count = int((result or {}).get("samples") or len(self.sample_batch_plans))
        self.sample_batch_plans.clear()
        self.sample_plan = None
        self._refresh_sample_batch_table()
        self.lbl_sample_plan.setText("Prepared: 0 sample")
        self.sample_log_msg(f"SAMPLE BATCH REGISTER COMPLETE | samples={count}")
        QMessageBox.information(self, "Sample Register", f"ลง Sample ใน QAC สำเร็จ {count} รายการ")

    def _sample_register_failed(self, error):
        self.btn_sample_prepare.setEnabled(True)
        self.btn_sample_register.setEnabled(bool(self.sample_batch_plans))
        self.sample_log_msg(f"SAMPLE REGISTER ERROR | {error}")
        QMessageBox.critical(self, "Sample Register", str(error))

    # ---------------- Daily Document ----------------
    def _build_daily_document_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        title = QLabel("Daily Document - Production Check Sheet")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(title)

        info = QLabel(
            "QAC module: Production Check Sheet (process=25, product-type=17)\n"
            "Document List อ่านจาก Source ที่กำหนดใน Settings แล้วเลือกเอกสารที่จะ Scan/Create/Edit"
        )
        root.addWidget(info)

        module_row = QHBoxLayout()
        self.btn_daily_open = QPushButton("Open / Verify Production Check Sheet")
        self.btn_daily_open.clicked.connect(
            lambda: self.ensure_qac_module("daily_document")
        )
        module_row.addWidget(self.btn_daily_open)
        self.lbl_daily_status = QLabel("ยังไม่ได้เปิด Production Check Sheet")
        module_row.addWidget(self.lbl_daily_status)
        module_row.addStretch()
        root.addLayout(module_row)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Production Date"))
        self.daily_date = QDateEdit()
        self.daily_date.setCalendarPopup(True)
        self.daily_date.setDisplayFormat("yyyy-MM-dd")
        self.reference_dates.subscribe("daily_document")
        self.daily_date.setDate(QDate.fromString(self.reference_dates.date_for("daily_document") or QDate.currentDate().toString("yyyy-MM-dd"), "yyyy-MM-dd"))
        self.daily_date.dateChanged.connect(lambda d: self.reference_dates.set_module_date("daily_document", d.toString("yyyy-MM-dd")))
        date_row.addWidget(self.daily_date)
        self.chk_daily_ref = QCheckBox("Read reference results from QAC date")
        self.chk_daily_ref.setChecked(False)
        date_row.addWidget(self.chk_daily_ref)
        self.daily_ref_date = QDateEdit()
        self.daily_ref_date.setCalendarPopup(True)
        self.daily_ref_date.setDisplayFormat("yyyy-MM-dd")
        # Reference date is relative to the selected production date, not the PC clock.
        # Qt's popup uses the editor's selected date; bounding the editor also prevents
        # navigating/committing future dates accidentally.
        self.daily_ref_date.setMaximumDate(self.daily_date.date().addDays(-1))
        self.daily_ref_date.setDate(self.daily_date.date().addDays(-1))
        self.daily_date.dateChanged.connect(self._sync_daily_reference_date)
        self.daily_date.dateChanged.connect(self._invalidate_daily_scan_on_date_change)
        self.daily_ref_date.setEnabled(False)
        self.chk_daily_ref.toggled.connect(self.daily_ref_date.setEnabled)
        date_row.addWidget(self.daily_ref_date)
        date_row.addStretch()
        root.addLayout(date_row)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Document List"))
        self.lbl_daily_source = QLabel("-")
        self.lbl_daily_source.setTextInteractionFlags(Qt.TextSelectableByMouse)
        source_row.addWidget(self.lbl_daily_source, 1)
        self.btn_daily_reload = QPushButton("Reload List")
        self.btn_daily_reload.clicked.connect(self.load_daily_document_list)
        source_row.addWidget(self.btn_daily_reload)
        root.addLayout(source_row)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Line"))
        self.cmb_daily_line = make_searchable(QComboBox())
        self.cmb_daily_line.currentIndexChanged.connect(self.apply_daily_filters)
        filter_row.addWidget(self.cmb_daily_line)

        filter_row.addWidget(QLabel("Model"))
        self.cmb_daily_model = make_searchable(QComboBox())
        self.cmb_daily_model.currentIndexChanged.connect(self.apply_daily_filters)
        filter_row.addWidget(self.cmb_daily_model)

        filter_row.addWidget(QLabel("Period"))
        self.cmb_daily_period = make_searchable(QComboBox())
        self.cmb_daily_period.currentIndexChanged.connect(self.apply_daily_filters)
        filter_row.addWidget(self.cmb_daily_period)

        filter_row.addWidget(QLabel("Type"))
        self.cmb_daily_kind = make_searchable(QComboBox())
        self.cmb_daily_kind.currentIndexChanged.connect(self.apply_daily_filters)
        filter_row.addWidget(self.cmb_daily_kind)

        filter_row.addWidget(QLabel("Search"))
        self.txt_daily_search = QLineEdit()
        self.txt_daily_search.setPlaceholderText("Document name / Document no.")
        self.txt_daily_search.textChanged.connect(self.apply_daily_filters)
        filter_row.addWidget(self.txt_daily_search, 1)
        root.addLayout(filter_row)

        action_row = QHBoxLayout()
        self.btn_daily_check_all = QPushButton("Check All")
        self.btn_daily_uncheck_all = QPushButton("Uncheck All")
        self.btn_daily_scan_selected = QPushButton("Scan Selected")
        self.btn_daily_refresh = QPushButton("Refresh QAC Status")
        self.btn_daily_run_due = QPushButton("Run Due / Edit Found")
        self.btn_daily_run_due.setEnabled(False)
        self.btn_daily_check_all.clicked.connect(
            lambda: self.set_daily_checks(True)
        )
        self.btn_daily_uncheck_all.clicked.connect(
            lambda: self.set_daily_checks(False)
        )
        self.btn_daily_scan_selected.clicked.connect(
            self.daily_scan_selected
        )
        self.btn_daily_refresh.clicked.connect(self.daily_refresh_qac_status)
        self.btn_daily_run_due.clicked.connect(self.daily_run_due)
        action_row.addWidget(self.btn_daily_check_all)
        action_row.addWidget(self.btn_daily_uncheck_all)
        action_row.addWidget(self.btn_daily_scan_selected)
        action_row.addWidget(self.btn_daily_refresh)
        action_row.addWidget(self.btn_daily_run_due)
        action_row.addStretch()
        self.lbl_daily_count = QLabel("0 documents")
        action_row.addWidget(self.lbl_daily_count)
        root.addLayout(action_row)

        register_group = QGroupBox("Daily Document Register")
        register_layout = QVBoxLayout(register_group)
        register_action_row = QHBoxLayout()
        self.btn_daily_register_ok = QPushButton("Register OK Selected")
        self.btn_daily_register_pause = QPushButton("Pause")
        self.btn_daily_register_resume = QPushButton("Resume")
        self.btn_daily_register_retry = QPushButton("Retry Incomplete (No Rescan)")
        self.btn_daily_register_retry.setEnabled(False)
        self.btn_daily_register_retry.clicked.connect(self.retry_daily_register_incomplete)
        self.btn_daily_register_stop = QPushButton("Stop")
        self.btn_daily_register_pause.setEnabled(False)
        self.btn_daily_register_resume.setEnabled(False)
        self.btn_daily_register_stop.setEnabled(False)
        self.btn_daily_register_ok.clicked.connect(self.daily_register_ok_selected)
        self.btn_daily_register_pause.clicked.connect(self.pause_daily_register)
        self.btn_daily_register_resume.clicked.connect(self.resume_daily_register)
        self.btn_daily_register_stop.clicked.connect(self.stop_daily_register)
        register_action_row.addWidget(self.btn_daily_register_ok)
        register_action_row.addWidget(self.btn_daily_register_pause)
        register_action_row.addWidget(self.btn_daily_register_resume)
        register_action_row.addWidget(self.btn_daily_register_retry)
        register_action_row.addWidget(self.btn_daily_register_stop)
        register_action_row.addStretch()
        self.daily_register_progress = QProgressBar()
        self.daily_register_progress.setRange(0, 100)
        self.daily_register_progress.setValue(0)
        register_action_row.addWidget(self.daily_register_progress, 1)
        register_layout.addLayout(register_action_row)
        register_layout.addWidget(QLabel(
            "Daily Check Sheet: ทำงานจริงกับ QAC | เอกสารที่มี Time จะถามเวลาก่อน Register (1 เวลา = 1 Slot) | "
            "OK/NG เติมเฉพาะ Slot ที่เลือก | NUMBER ใช้ค่าจริงจาก Value File หรือค่า D-1 ตามกฎเอกสาร"
        ))
        root.addWidget(register_group)

        # QAC HTML Collector UI removed from Daily Document.
        # Historical D-1 data remains an internal data source for live register rules.
        self.daily_history_root = str(program_dir() / "qac_html_exports")

        self.tbl_daily = QTableWidget(0, 10)
        self.tbl_daily.setHorizontalHeaderLabels(
            [
                "Select",
                "Line",
                "Model",
                "Period",
                "Type",
                "Document",
                "Document No.",
                "Target",
                "QAC Status",
                "Action",
            ]
        )
        make_table_columns_resizable(self.tbl_daily, persistence_key="daily_document")
        root.addWidget(self.tbl_daily)

        self.daily_log = QTextEdit()
        self.daily_log.setReadOnly(True)
        self.daily_log.setMaximumHeight(190)
        root.addWidget(self.daily_log)

        # Defer loading until all top-level UI widgets are ready.
        return w


    def _sync_daily_reference_date(self, production_date: QDate) -> None:
        """Keep reference <= production - 1 day, preserving a valid older selection."""
        if not production_date.isValid():
            return
        last_allowed = production_date.addDays(-1)
        reference = self.daily_ref_date
        reference.setMaximumDate(last_allowed)
        if not reference.date().isValid() or reference.date() > last_allowed:
            reference.setDate(last_allowed)


    def daily_log_msg(self, message: str):
        from datetime import datetime
        import re
        value = str(message)
        if not re.match(r'^\[\d{4}-\d{2}-\d{2} ', value):
            value = f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}] {value}"
        if hasattr(self, "daily_log"):
            self.daily_log.append(value)

    def load_daily_document_list(self, show_message: bool = True):
        cfg = self.settings.get("daily_document", {})
        source = str(cfg.get("list_source", "config/List document.xlsx") or "")
        sheet = str(cfg.get("sheet_name", "Raw") or "Raw")
        active_only = bool(cfg.get("active_only", True))
        try:
            rows, resolved = load_document_master(
                source_path=source,
                app_root=self.app_root_path,
                sheet_name=sheet,
                active_only=active_only,
            )
            self.daily_master_rows = rows
            self.lbl_daily_source.setText(str(resolved))
            self._refresh_daily_filter_options()
            self.apply_daily_filters()
            self._refresh_sample_document_options()
            self.daily_log_msg(
                f"DOCUMENT LIST READY | {len(rows)} rows | {resolved}"
            )
            if show_message:
                self.audit.write(
                    "DAILY_DOCUMENT_LIST_LOADED",
                    status="OK",
                    source=str(resolved),
                    rows=len(rows),
                )
        except Exception as e:
            self.daily_master_rows = []
            self.daily_filtered_rows = []
            self.tbl_daily.setRowCount(0)
            self.lbl_daily_count.setText("0 documents")
            self.lbl_daily_source.setText(source or "-")
            self.daily_log_msg(f"DOCUMENT LIST ERROR | {e}")
            if show_message:
                QMessageBox.critical(self, "Daily Document List", str(e))

    def _refresh_daily_filter_options(self):
        def fill(combo, values):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All", "")
            for value in sorted({str(v).strip() for v in values if str(v).strip()}):
                combo.addItem(value, value)
            if current:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

        fill(self.cmb_daily_line, [r.get("line", "") for r in self.daily_master_rows])
        fill(self.cmb_daily_model, [r.get("model", "") for r in self.daily_master_rows])
        fill(self.cmb_daily_period, [r.get("period", "") for r in self.daily_master_rows])
        fill(self.cmb_daily_kind, [r.get("document_kind", "") for r in self.daily_master_rows])
        self._set_daily_line_from_auto_register(force=False)

    def _auto_register_line(self):
        """Return the line from the currently selected Auto Register QAC document."""
        try:
            idx = self.cmb_doc.currentIndex()
            if 0 <= idx < len(self.documents):
                return str(self.documents[idx].line or "").strip()
        except Exception:
            pass
        return ""

    def _set_daily_line_from_auto_register(self, force=False):
        """Seed Daily Document Line from Auto Register while keeping it editable."""
        if not hasattr(self, "cmb_daily_line"):
            return False
        line = self._auto_register_line()
        if not line:
            return False
        idx = self.cmb_daily_line.findData(line)
        if idx < 0:
            # Case-insensitive fallback because master spelling may differ only by case.
            target = line.casefold()
            for i in range(self.cmb_daily_line.count()):
                if str(self.cmb_daily_line.itemData(i) or "").strip().casefold() == target:
                    idx = i
                    break
        if idx < 0:
            return False
        current = str(self.cmb_daily_line.currentData() or "").strip()
        if force or not current:
            self.cmb_daily_line.setCurrentIndex(idx)
            return True
        return False

    def apply_daily_filters(self):
        if not hasattr(self, "tbl_daily"):
            return
        line = str(self.cmb_daily_line.currentData() or "").strip().casefold()
        model = str(self.cmb_daily_model.currentData() or "").strip().casefold()
        period = str(self.cmb_daily_period.currentData() or "").strip().casefold()
        kind = str(self.cmb_daily_kind.currentData() or "").strip().casefold()
        query = str(self.txt_daily_search.text() or "").strip().casefold()

        rows = []
        for row in self.daily_master_rows:
            if line and str(row.get("line", "")).strip().casefold() != line:
                continue
            row_model = str(row.get("model", "")).strip()
            if model and row_model.casefold() != model:
                continue
            if period and str(row.get("period", "")).strip().casefold() != period:
                continue
            if kind and str(row.get("document_kind", "")).strip().casefold() != kind:
                continue
            hay = (
                str(row.get("document_name", ""))
                + " "
                + str(row.get("document_no", ""))
            ).casefold()
            if query and query not in hay:
                continue
            rows.append(row)

        self.daily_filtered_rows = rows
        self._render_daily_rows()

    def _render_daily_rows(self):
        table = self.tbl_daily
        table.setRowCount(0)
        for row_index, data in enumerate(self.daily_filtered_rows):
            table.insertRow(row_index)

            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemIsEnabled
                | Qt.ItemIsSelectable
                | Qt.ItemIsUserCheckable
            )
            check.setCheckState(Qt.Unchecked)
            table.setItem(row_index, 0, check)

            for col, key in (
                (1, "line"),
                (2, "model"),
                (3, "period"),
                (4, "document_kind"),
                (5, "document_name"),
                (6, "document_no"),
                (7, "target_num"),
            ):
                item = QTableWidgetItem(str(data.get(key, "") or ""))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row_index, col, item)

            status_item = QTableWidgetItem("NOT SCANNED")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_index, 8, status_item)

            btn = QPushButton("Scan")
            btn.clicked.connect(
                lambda _checked=False, idx=row_index: self.daily_scan_row(idx)
            )
            table.setCellWidget(row_index, 9, btn)

        self.lbl_daily_count.setText(f"{len(self.daily_filtered_rows)} documents")
        make_table_columns_resizable(table, persistence_key="daily_document")

    def set_daily_checks(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.tbl_daily.rowCount()):
            item = self.tbl_daily.item(row, 0)
            if item:
                item.setCheckState(state)

    def daily_selected_indices(self):
        out = []
        for row in range(self.tbl_daily.rowCount()):
            item = self.tbl_daily.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                out.append(row)
        return out

    def _invalidate_daily_scan_on_date_change(self, _date=None):
        """Old Task IDs must never be reused for a different selected date."""
        self.daily_scan_results = {}
        self._daily_retry_payload = None
        self._pending_daily_scan_payload = None
        self._pending_daily_register_payload = None
        self.btn_daily_run_due.setEnabled(False)
        for row in range(self.tbl_daily.rowCount()):
            cell = self.tbl_daily.item(row, 8)
            if cell:
                cell.setText('NOT SCANNED')
            btn = self.tbl_daily.cellWidget(row, 9)
            if isinstance(btn, QPushButton):
                btn.setText('Scan')
                try: btn.clicked.disconnect()
                except (TypeError, RuntimeError): pass
                btn.clicked.connect(lambda _checked=False, idx=row: self.daily_scan_row(idx))
        self.daily_log_msg('DAILY SCAN INVALIDATED | selected production date changed; old task IDs cleared')

    def daily_scan_row(self, row_index: int):
        if row_index < 0 or row_index >= len(self.daily_filtered_rows):
            return
        self.set_daily_checks(False)
        item = self.tbl_daily.item(row_index, 0)
        if item:
            item.setCheckState(Qt.Checked)
        self.daily_scan_selected()

    def daily_scan_selected(self):
        if self._workflow_running():
            QMessageBox.warning(self, 'QAC Scan', 'มี Workflow ทำงานอยู่ — ไม่อนุญาตให้ Scan ซ้ำ')
            return
        selected = self.daily_selected_indices()
        if not selected:
            QMessageBox.information(
                self, "Daily Document", "กรุณาเลือกเอกสารอย่างน้อย 1 รายการ"
            )
            return
        if self.daily_scan_worker and self.daily_scan_worker.isRunning():
            return

        # An explicit Scan must never reuse a previous run's task identity.
        self.daily_scan_results = {}
        self._daily_retry_payload = None
        self.btn_daily_register_retry.setEnabled(False)
        self._pending_daily_register_payload = None
        self.btn_daily_run_due.setEnabled(False)
        for r in selected:
            btn = self.tbl_daily.cellWidget(r, 9)
            if isinstance(btn, QPushButton):
                btn.setText('Scan')
                try: btn.clicked.disconnect()
                except (TypeError, RuntimeError): pass
                btn.clicked.connect(lambda _checked=False, idx=r: self.daily_scan_row(idx))
        self.daily_log_msg(f'DAILY RESCAN RESET | cleared previous task IDs for {len(selected)} selected documents')
        docs = [dict(self.daily_filtered_rows[r], _ui_row=r) for r in selected]
        production_date = self.daily_date.date().toString("yyyy-MM-dd")
        for r in selected:
            item = self.tbl_daily.item(r, 8)
            if item:
                item.setText("WAIT QAC...")
        self.btn_daily_scan_selected.setEnabled(False)
        self.btn_daily_run_due.setEnabled(False)
        self.daily_log_msg(
            f"SCAN REQUEST | date={production_date} | selected={len(docs)} | เปิด QAC หลังผู้ใช้กดปุ่มแล้ว"
        )
        # Store the requested scan. It starts only after Production Check Sheet
        # has been verified/opened successfully. This prevents navigation/scan
        # races and guarantees that changing tabs alone never touches QAC.
        self._pending_daily_scan_payload = (production_date, docs)
        self.ensure_qac_module("daily_document")

    def daily_refresh_qac_status(self):
        """Explicit status refresh for Daily Document without changing business rules.

        Uses checked rows; when nothing is checked, uses the current row only.
        This avoids accidentally scanning hundreds of Daily Document masters.
        """
        selected = self.daily_selected_indices()
        if not selected:
            row = self.tbl_daily.currentRow()
            if 0 <= row < self.tbl_daily.rowCount():
                item = self.tbl_daily.item(row, 0)
                if item:
                    item.setCheckState(Qt.Checked)
                selected = [row]
        if not selected:
            QMessageBox.information(
                self, "Daily Document",
                "เลือกอย่างน้อย 1 เอกสารก่อน Refresh QAC Status"
            )
            return
        self.daily_log_msg(f"QAC STATUS REFRESH | selected={len(selected)}")
        self.daily_scan_selected()

    def _start_daily_scan_worker(self, production_date, docs):
        cfg = self.browser_cfg()
        if not cdp_ready(cfg["cdp_url"]):
            self._daily_scan_failed("QAC Browser ยังไม่พร้อม")
            return

        self.daily_log_msg(
            f"SCAN START | date={production_date} | selected={len(docs)}"
        )
        self._daily_scan_requested_date = production_date
        self.daily_scan_worker = DailyDocumentScanWorker(
            cfg["cdp_url"], production_date, docs
        )
        self.daily_scan_worker.progress.connect(self.daily_log_msg)
        self.daily_scan_worker.completed.connect(self._daily_scan_completed)
        self.daily_scan_worker.failed.connect(self._daily_scan_failed)
        self.daily_scan_worker.start()

    def _daily_scan_completed(self, results):
        self.btn_daily_scan_selected.setEnabled(True)
        if getattr(self, '_daily_scan_requested_date', None) != self.daily_date.date().toString('yyyy-MM-dd'):
            self.daily_log_msg('DAILY SCAN DISCARDED | date changed while scan was running; no stale task ID imported')
            self.daily_scan_results = {}
            self.btn_daily_run_due.setEnabled(False)
            return
        self.daily_scan_results = {}
        found = missing = 0
        for result in list(results or []):
            row = int(result.get("_ui_row", -1))
            if row < 0 or row >= self.tbl_daily.rowCount():
                continue
            status = str(result.get("scan_status") or "ERROR")
            self.daily_scan_results[row] = dict(result, _scanned_production_date=self.daily_date.date().toString("yyyy-MM-dd"))
            item = self.tbl_daily.item(row, 8)
            if item:
                found_date = str(result.get("found_date") or "").strip()
                item.setText(f"{status} {found_date}".strip())
            btn = self.tbl_daily.cellWidget(row, 9)
            if status == "FOUND":
                found += 1
                if isinstance(btn, QPushButton):
                    btn.setText("Edit / Measure")
                    try:
                        btn.clicked.disconnect()
                    except Exception:
                        pass
                    btn.clicked.connect(lambda _=False, rr=row: self.daily_open_found(rr))
            else:
                missing += 1
                if isinstance(btn, QPushButton):
                    btn.setText("Create")
                    btn.setToolTip("เอกสารยังไม่ถูกสร้างใน QAC วันที่เลือก")
        self.btn_daily_run_due.setEnabled(found > 0)
        self.daily_log_msg(f"SCAN DONE | FOUND={found} | MISSING={missing}")

    def _daily_scan_failed(self, error: str):
        self.btn_daily_scan_selected.setEnabled(True)
        self.btn_daily_run_due.setEnabled(False)
        self.daily_log_msg(f"SCAN ERROR | {error}")
        QMessageBox.critical(self, "Daily Document Scan", str(error))

    def daily_open_found(self, row: int):
        result = self.daily_scan_results.get(row) or {}
        task_id = str(result.get("task_id") or "").strip()
        if not task_id or result.get("_scanned_production_date") != self.daily_date.date().toString("yyyy-MM-dd"):
            QMessageBox.warning(self, "Daily Document", "Task ID ไม่ตรงกับวันที่เลือก กรุณา Scan ใหม่")
            return
        if self.daily_open_worker and self.daily_open_worker.isRunning():
            return
        self.daily_log_msg(f"EDIT | task={task_id} | {result.get('document_name','')}")
        self.daily_open_worker = DailyDocumentOpenWorker(self.browser_cfg()["cdp_url"], task_id, result)
        self.daily_open_worker.completed.connect(lambda r: self.daily_log_msg(f"MEASURE OPENED | task={task_id}"))
        self.daily_open_worker.failed.connect(lambda e: QMessageBox.critical(self, "Daily Document", str(e)))
        self.daily_open_worker.start()

    def daily_run_due(self):
        # At this stage Run Due means process already-created selected documents.
        # Future schedule rules will decide exact slot/time; never auto-create or
        # write future slots merely because a master row is selected.
        rows = [r for r in self.daily_selected_indices() if (self.daily_scan_results.get(r) or {}).get("scan_status") == "FOUND"]
        if not rows:
            QMessageBox.information(self, "Daily Document", "ไม่มีเอกสาร FOUND ที่เลือกไว้")
            return
        # Open the oldest/first selected document for edit. Sequential auto-fill
        # will be connected once each document's schedule/input rule is defined.
        self.daily_open_found(rows[0])

    def browse_html_output(self):
        current = str(self.txt_html_output.text() or "").strip()
        selected = QFileDialog.getExistingDirectory(
            self,
            "เลือก Folder สำหรับ QAC HTML",
            current or str(program_dir()),
        )
        if selected:
            self.txt_html_output.setText(selected)

    def daily_collect_html_selected(self):
        selected = self.daily_selected_indices()
        if not selected:
            QMessageBox.information(
                self, "HTML Collector", "กรุณาเลือกเอกสารอย่างน้อย 1 รายการ"
            )
            return
        if not self._employee_id():
            QMessageBox.warning(self, "QAC Login", "กรุณากรอก Employee ID")
            self.txt_employee_id.setFocus()
            return
        if self.html_collector_worker and self.html_collector_worker.isRunning():
            QMessageBox.information(self, "HTML Collector", "Collector กำลังทำงานอยู่")
            return
        output_root = str(self.txt_html_output.text() or "").strip()
        if not output_root:
            QMessageBox.warning(self, "HTML Collector", "กรุณาเลือก Output Folder")
            return
        try:
            Path(output_root).expanduser().mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "HTML Collector", f"สร้าง Output Folder ไม่สำเร็จ\n{e}")
            return

        documents = [dict(self.daily_filtered_rows[row], _ui_row=row) for row in selected]
        production_date = self.daily_date.date().toString("yyyy-MM-dd")
        self.html_collect_progress.setValue(0)
        self.btn_html_collect.setEnabled(False)
        self.btn_html_pause.setEnabled(False)
        self.btn_html_resume.setEnabled(False)
        self.btn_html_stop.setEnabled(True)
        overwrite_existing = bool(self.chk_html_overwrite.isChecked())
        self._pending_html_collect_payload = (
            production_date,
            documents,
            output_root,
            overwrite_existing,
        )
        self.daily_log_msg(
            f"HTML COLLECT REQUEST | dates={self.daily_date.date().addDays(-1).toString('yyyy-MM-dd')}..{production_date} | selected={len(documents)} | READ ONLY"
            + (" | OVERWRITE" if overwrite_existing else "")
        )
        self.ensure_qac_module("daily_document")

    def _start_html_collector_worker(self, production_date, documents, output_root, overwrite_existing=False):
        cfg = self.browser_cfg()
        if not cdp_ready(cfg["cdp_url"]):
            self._html_collection_failed("QAC Browser ยังไม่พร้อม")
            return
        self.html_collector_worker = QACHtmlCollectorWorker(
            cfg["cdp_url"], production_date, documents, output_root, overwrite_existing=overwrite_existing
        )
        self.html_collector_worker.progress.connect(self._html_collection_progress)
        self.html_collector_worker.completed.connect(self._html_collection_completed)
        self.html_collector_worker.failed.connect(self._html_collection_failed)
        self.btn_html_pause.setEnabled(True)
        self.btn_html_stop.setEnabled(True)
        self.html_collector_worker.start()

    def _html_collection_progress(self, message: str):
        self.daily_log_msg(message)
        match = re.search(r"\[(\d+)/(\d+)\]", str(message))
        if match and int(match.group(2)) > 0:
            self.html_collect_progress.setValue(
                int(int(match.group(1)) * 100 / int(match.group(2)))
            )

    def _html_collection_completed(self, result):
        self.html_collect_progress.setValue(100)
        self.btn_html_collect.setEnabled(True)
        self.btn_html_pause.setEnabled(False)
        self.btn_html_resume.setEnabled(False)
        self.btn_html_stop.setEnabled(False)
        for item in list((result or {}).get("results") or []):
            row = int(item.get("_ui_row", -1))
            if 0 <= row < self.tbl_daily.rowCount():
                status = str(item.get("status") or "")
                cell = self.tbl_daily.item(row, 8)
                if cell and status:
                    cell.setText(f"HTML {status}")
        output = str((result or {}).get("output_directory") or "")
        summary = (
            f"เก็บสำเร็จ {(result or {}).get('collected', 0)} | "
            f"ข้าม {(result or {}).get('skipped', 0)} | "
            f"ไม่พบ {(result or {}).get('missing', 0)} | "
            f"ผิดพลาด {(result or {}).get('errors', 0)}"
        )
        self.daily_log_msg(f"HTML COLLECT DONE | {summary} | {output}")
        self.audit.write("QAC_HTML_COLLECTION", status="OK", summary=summary, output=output)
        QMessageBox.information(self, "HTML Collector", summary + "\n\n" + output)

    def _html_collection_failed(self, error: str):
        self.btn_html_collect.setEnabled(True)
        self.btn_html_pause.setEnabled(False)
        self.btn_html_resume.setEnabled(False)
        self.btn_html_stop.setEnabled(False)
        self.daily_log_msg(f"HTML COLLECT STOPPED | {error}")
        self.audit.write("QAC_HTML_COLLECTION", status="ERROR", error=str(error))
        QMessageBox.warning(self, "HTML Collector", str(error))

    def pause_html_collection(self):
        if self.html_collector_worker and self.html_collector_worker.isRunning():
            self.html_collector_worker.request_pause()
            self.btn_html_pause.setEnabled(False)
            self.btn_html_resume.setEnabled(True)
            self.daily_log_msg("HTML COLLECT PAUSED | จะหยุดก่อนเปิดเอกสารถัดไป")

    def resume_html_collection(self):
        if self.html_collector_worker and self.html_collector_worker.isRunning():
            self.html_collector_worker.request_resume()
            self.btn_html_pause.setEnabled(True)
            self.btn_html_resume.setEnabled(False)
            self.daily_log_msg("HTML COLLECT RESUMED")

    def stop_html_collection(self):
        if self._pending_html_collect_payload is not None:
            self._pending_html_collect_payload = None
            self._html_collection_failed("ยกเลิกก่อนเริ่ม Collector")
            return
        if self.html_collector_worker and self.html_collector_worker.isRunning():
            self.html_collector_worker.request_stop()
            self.btn_html_stop.setEnabled(False)
            self.daily_log_msg("HTML COLLECT STOP REQUESTED | จะหยุดอย่างปลอดภัย")

    def _prompt_daily_slot_plan(self, document: dict, schema: list[dict]) -> dict | None:
        """Live-HTML-driven form: independent ComboBox for each free Daily slot."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Daily Document - Choose Result Per Slot")
        dlg.resize(830, 670)
        lay = QVBoxLayout(dlg)
        label = QLabel(
            f"{document.get('document_name', '')}\n"
            f"Task ID: {document.get('task_id', '')}\n"
            f"Reference Date: {self.daily_ref_date.date().toString('yyyy-MM-dd') if self.chk_daily_ref.isChecked() else 'Latest confirmed SQLite memory'}\n"
            "เลือกเฉพาะ Slot ที่ตรวจจริง: ไม่ลง / Initial / Middle / Final / OK / NG\n"
            "ตัวเลือกแต่ละรายการมาจาก HTML ของ QAC และช่องที่บันทึกแล้วจะเลือกไม่ได้"
        )
        label.setWordWrap(True)
        lay.addWidget(label)
        status_summary=QLabel('กำลังอ่านสถานะ QAC...')
        lay.addWidget(status_summary)
        scroll=QScrollArea(dlg)
        scroll.setWidgetResizable(True)
        content=QWidget()
        inside=QVBoxLayout(content)
        edits=[]
        slot_counts={'SAVED':0, 'EMPTY':0, 'UNKNOWN':0}
        filter_rows=[]  # (QWidget, verified QAC status, owning QGroupBox)
        filter_groups=[]
        for field in schema:
            item=str(field.get('item') or '')
            options=list(field.get('options') or [])
            if not options:
                self.daily_log_msg(f"DAILY HTML UNSUPPORTED | item={item} | {field.get('format')}")
                continue
            group=QGroupBox(f"{field.get('label') or 'Item'}   [ID {item}]")
            group_lay=QVBoxLayout(group)
            filter_groups.append(group)
            for slot in field.get('slots') or []:
                num=int(slot['number'])
                # Status is QAC evidence, never inferred from the saved template.
                raw_status=str(slot.get('status') or '').upper()
                slot_status=('SAVED' if slot.get('saved') else raw_status)
                if slot_status not in slot_counts:
                    slot_status='UNKNOWN'
                slot_counts[slot_status]+=1
                # A real widget per slot allows filtering without losing edits,
                # saved evidence, or the original document slot ordering.
                row_widget=QWidget(group)
                row=QHBoxLayout(row_widget)
                row.setContentsMargins(2, 2, 2, 2)
                row.addWidget(QLabel(f"Slot #{num}"))
                status_badge=QLabel('EXIST' if slot_status=='SAVED' else slot_status)
                status_badge.setMinimumWidth(78)
                status_badge.setAlignment(Qt.AlignCenter)
                styles={
                    'SAVED':'background:#e1f3e5;color:#155724;border:1px solid #8fc69c;',
                    'EMPTY':'background:#f1f3f5;color:#465362;border:1px solid #cbd3dc;',
                    'UNKNOWN':'background:#ffedd5;color:#92400e;border:1px solid #f4b183;',
                }
                status_badge.setStyleSheet(styles[slot_status]+'border-radius:4px;padding:5px;')
                if slot_status=='UNKNOWN':
                    row.addWidget(QLabel('อ่านสถานะ QAC ไม่ชัดเจน — ไม่อนุญาตลงทะเบียน'),1)
                elif slot_status=='SAVED':
                    current=str(slot.get('current_value') or slot.get('value') or '').strip()
                    label_value=current if current else 'QAC บันทึกแล้ว (ไม่พบค่าที่อ่านได้)'
                    existing=QLabel(label_value)
                    existing.setStyleSheet('color:#155724;')
                    row.addWidget(existing,1)
                elif str(field.get('format')) == '1':
                    entry=QLineEdit()
                    prior=str(slot.get('previous_value') or '').strip()
                    if prior:
                        # Make verified Measure reference visible/editable, not
                        # only a placeholder. The operator must still review,
                        # confirm and explicitly approve carrying forward.
                        entry.setText(prior)
                        entry.setPlaceholderText(f"Reference {slot.get('previous_date')}: {prior}; พิมพ์ '-' เพื่อไม่ลง")
                    else:
                        entry.setPlaceholderText('ไม่มีผล D-1 ที่ยืนยันได้ — ว่าง = ไม่ลง')
                    row.addWidget(entry,1)
                    edits.append((item,num,'NUMBER',entry,prior,slot.get('previous_result_id')))
                else:
                    combo=QComboBox()
                    prior=str(slot.get('previous_value') or '').strip()
                    if prior in options:
                        combo.addItem(f"ใช้ผล D-1: {prior} ({slot.get('previous_date')})",'PREVIOUS')
                    combo.addItem('ไม่ลง','')
                    for option in options:combo.addItem(str(option),str(option))
                    row.addWidget(combo,1)
                    edits.append((item,num,'CHOICE',combo,prior,slot.get('previous_result_id')))
                row.addWidget(status_badge)
                group_lay.addWidget(row_widget)
                filter_rows.append((row_widget,slot_status,group))
            inside.addWidget(group)
        status_summary.setText(
            f"QAC Status: EXIST {slot_counts['SAVED']} | EMPTY {slot_counts['EMPTY']} | UNKNOWN {slot_counts['UNKNOWN']}"
        )
        if slot_counts['UNKNOWN']:
            status_summary.setStyleSheet('color:#a16207;font-weight:bold;')
        # The filter uses verified QAC status, not the selected template value.
        # EXIST rows have no editable widgets and remain interlocked.
        filter_bar=QHBoxLayout()
        filter_bar.addWidget(QLabel('แสดงรายการตามสถานะ QAC:'))
        qac_filter=QComboBox(dlg)
        qac_filter.setObjectName('daily_qac_status_filter')
        qac_filter.addItem(f"ทั้งหมด ({sum(slot_counts.values())})",'ALL')
        qac_filter.addItem(f"EXIST ({slot_counts['SAVED']})",'SAVED')
        qac_filter.addItem(f"EMPTY ({slot_counts['EMPTY']})",'EMPTY')
        qac_filter.addItem(f"UNKNOWN ({slot_counts['UNKNOWN']})",'UNKNOWN')
        filter_bar.addWidget(qac_filter)
        filter_bar.addStretch()
        lay.addLayout(filter_bar)
        def apply_qac_filter(_=None):
            current=str(qac_filter.currentData() or 'ALL')
            visible_groups=set()
            for row_widget, qac_status, owner in filter_rows:
                show=current=='ALL' or qac_status==current
                row_widget.setVisible(show)
                if show:visible_groups.add(owner)
            for group in filter_groups:
                group.setVisible(group in visible_groups)
            # Never let a filtered, shorter list bypass the full-document review.
        qac_filter.currentIndexChanged.connect(apply_qac_filter)
        inside.addStretch()
        scroll.setWidget(content)
        lay.addWidget(scroll,1)
        # Operator must review all content by scrolling manually to the bottom.
        # Buttons remain disabled until this happens, even if an old template exists.
        review_state={'bottom':False, 'at_top':True}
        review_box=QCheckBox('ยืนยันว่าได้ตรวจสอบข้อมูลทั้งหมดของเอกสารนี้แล้ว')
        review_box.setEnabled(False)
        lay.addWidget(review_box)
        review_hint=QLabel('กรุณาเลื่อนจากบนสุดลงล่างสุด เพื่อตรวจสอบทุก Item ก่อนยืนยัน')
        lay.addWidget(review_hint)
        scrollbar=scroll.verticalScrollBar()
        scrollbar.setValue(0)
        def review_scroll(value):
            if value == 0:
                review_state['at_top'] = True
            if scrollbar.maximum()>0 and review_state['at_top'] and value >= scrollbar.maximum():
                review_state['bottom']=True
                review_box.setEnabled(True)
                review_hint.setText('เลื่อนตรวจทานถึงรายการสุดท้ายแล้ว — กรุณาติ๊กยืนยัน')
        scrollbar.valueChanged.connect(review_scroll)
        def activate_if_fully_visible():
            if scrollbar.maximum()==0:
                review_state['bottom']=True
                review_box.setEnabled(True)
                review_hint.setText('ทุกรายการแสดงครบในหน้าจอแล้ว — กรุณายืนยัน')
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, activate_if_fully_visible)
        preset_row=QHBoxLayout()
        btn_reset=QPushButton("Reset Template")
        preset_row.addWidget(btn_reset)
        preset_row.addStretch()
        lay.addLayout(preset_row)
        status=QLabel("ยังไม่เลือก Slot")
        lay.addWidget(status)
        buttons=QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        buttons.button(QDialogButtonBox.Ok).setText("Confirm Slot Plan")
        lay.addWidget(buttons)
        buttons.rejected.connect(dlg.reject)
        confirm_button=buttons.button(QDialogButtonBox.Ok)
        confirm_button.setEnabled(False)
        def refresh_review_button(_=None):
            confirm_button.setEnabled(bool(
                review_state['bottom'] and review_box.isChecked()
                and qac_filter.currentData() == 'ALL'
            ))
        review_box.toggled.connect(refresh_review_button)
        def on_qac_filter_changed(_=None):
            review_state['bottom']=False
            review_state['at_top']=False
            scrollbar.setValue(0)
            review_box.setChecked(False)
            review_box.setEnabled(False)
            review_hint.setText('กลับไปเลือก ทั้งหมด แล้วเลื่อนตรวจทานจากบนสุดถึงล่างสุดก่อนยืนยัน')
            if qac_filter.currentData() == 'ALL':
                review_state['at_top']=True
                QTimer.singleShot(0, activate_if_fully_visible)
            refresh_review_button()
        qac_filter.currentIndexChanged.connect(on_qac_filter_changed)
        def review_invalidated(*_):
            # Changes to any result require a new review of the complete document.
            review_state['bottom']=False
            review_box.setChecked(False)
            review_box.setEnabled(False)
            # Do not change scroll position when an operator edits a row.
            # A new full review begins only when the operator manually reaches top.
            review_state['at_top'] = scrollbar.value() == 0
            QTimer.singleShot(0, activate_if_fully_visible)
            review_hint.setText('ค่าเปลี่ยนแล้ว: ตำแหน่งเลื่อนคงเดิม กรุณากลับไปบนสุดแล้วตรวจทานจนถึงล่างสุด')
            refresh_review_button()
        for _item,_num,_typ,_widget,_prior,_src in edits:
            if _typ=='NUMBER':_widget.textChanged.connect(review_invalidated)
            else:_widget.currentIndexChanged.connect(review_invalidated)

        def selected():
            plan={}
            for item,num,typ,widget,prior,source_id in edits:
                if typ=='NUMBER':
                    entered=widget.text().strip()
                    if entered=='-':value=''
                    elif entered:value='VALUE:'+entered
                    else:value='VALUE:'+prior if prior else ''
                else:
                    selected=str(widget.currentData() or '')
                    value=prior if selected=='PREVIOUS' and prior else selected
                if value:plan.setdefault(item,{})[str(num)]=value
            return plan

        def update_status():
            plan=selected()
            status.setText(
                f"เลือก {sum(len(v) for v in plan.values())} Slot | "
                f"{len(plan)} Inspection Items"
            )
        for item,num,typ,widget,prior,source_id in edits:
            if typ=='NUMBER':widget.textChanged.connect(update_status)
            else:widget.currentIndexChanged.connect(update_status)
        def accept():
            if not (review_state['bottom'] and review_box.isChecked() and qac_filter.currentData() == 'ALL'):
                QMessageBox.warning(dlg,'Daily Review','เลือก ทั้งหมด แล้วเลื่อนตรวจทานถึงด้านล่างและยืนยันก่อน')
                return
            plan=selected()
            if not plan:
                existing=sum(1 for item in schema for slot in item.get('slots',[]) if slot.get('saved'))
                if existing:
                    self.daily_log_msg(
                        f"DAILY NO NEW SLOTS | document={document.get('document_name')} | "
                        f"existing_results={existing} | no register needed"
                    )
                else:
                    QMessageBox.warning(dlg,"Daily Slot Plan","ไม่มี Result เดิม และยังไม่ได้เลือก Slot ที่ต้องการลงทะเบียน")
                    return
            inherited=[]
            for item,num,typ,widget,prior,source_id in edits:
                chosen=plan.get(item,{}).get(str(num),'')
                if prior and chosen==('VALUE:'+prior if typ=='NUMBER' else prior):
                    if (typ=='NUMBER' and widget.text().strip()==prior) or (typ=='CHOICE' and widget.currentData()=='PREVIOUS'):
                        inherited.append((item,num,prior,source_id))
            if inherited:
                answer=QMessageBox.question(
                    dlg,"Confirm D-1 Carry-Forward",
                    f"จะคัดลอกผลตรวจ D-1 จำนวน {len(inherited)} Slot ไปบันทึกวันนี้\n"
                    "นี่คือผลเดิม ไม่ใช่ผลตรวจที่วัดใหม่วันนี้\n"
                    "โปรดยืนยันว่ามาตรฐานงานอนุญาตให้ใช้ผลเดิม และพนักงานตรวจสอบแล้ว\n\n"
                    "ยืนยันการใช้ผลล่าสุดหรือไม่?"
                )
                if answer!=QMessageBox.Yes:return
                for item,num,prior,source_id in inherited:
                    self.daily_log_msg(f"DAILY LATEST APPROVED | item={item} slot={num} result={source_id} value={prior}")
            dlg._plan=plan
            dlg.accept()
        buttons.accepted.connect(accept)
        from app.daily_slot_memory import DailySlotMemory
        memory=DailySlotMemory(app_root() / "database" / "daily_slot_presets.sqlite3")

        def _save_presets(*_):
            try:
                # Preserve choices for QAC EXIST slots that are hidden from editing.
                # Choices are user intentions only, not claims about QAC results.
                previous=memory.load(document)
                editable={(item,str(num)) for item,num,*_ in edits}
                preserved={item:{slot:choice for slot,choice in slots.items()
                                 if (item,slot) not in editable}
                           for item,slots in previous.items() if isinstance(slots,dict)}
                for item,slots in selected().items():
                    preserved.setdefault(item,{}).update(slots)
                memory.save(document,preserved)
            except Exception as exc:
                self.daily_log_msg(f"DAILY TEMPLATE AUTO SAVE ERROR | {type(exc).__name__}: {exc}")

        auto_save_timer=QTimer(dlg)
        auto_save_timer.setSingleShot(True)
        auto_save_timer.setInterval(350)
        auto_save_timer.timeout.connect(_save_presets)
        for _item,_num,_typ,_widget,_prior,_src in edits:
            if _typ=='NUMBER': _widget.textChanged.connect(lambda *_:auto_save_timer.start())
            else: _widget.currentIndexChanged.connect(lambda *_:auto_save_timer.start())

        def load_template():
            try:
                preset=memory.load(document)
                count=0
                for item,num,typ,widget,prior,source_id in edits:
                    value=str(preset.get(item,{}).get(str(num),'') or '')
                    was_blocked=widget.blockSignals(True)
                    try:
                        if typ=='NUMBER':
                            from app.daily_numeric_prefill import resolve_numeric_prefill
                            text, applied = resolve_numeric_prefill(prior, value)
                            widget.setText(text)
                            count += bool(text)
                            if value and not applied:
                                self.daily_log_msg(
                                    f"DAILY NUMERIC PRESET IGNORED | item={item} slot={num} value={value!r}"
                                )
                        else:
                            pos=widget.findData(value)
                            if pos>=0 and value:
                                widget.setCurrentIndex(pos)
                                count+=1
                    finally:
                        widget.blockSignals(was_blocked)
                self.daily_log_msg(f"DAILY SLOT TEMPLATE AUTO LOADED | {document.get('document_name')} | selected={count}")
                update_status()
            except Exception as exc:
                QMessageBox.warning(dlg,"Daily Template",str(exc))

        def reset_template():
            if QMessageBox.question(dlg,"Reset Template","ลบ Template ของเอกสารนี้หรือไม่?")!=QMessageBox.Yes:return
            try:
                memory.reset(document)
                for item,num,typ,widget,prior,source_id in edits:
                    if typ=='NUMBER':widget.clear()
                    else:widget.setCurrentIndex(widget.findData(''))
                auto_save_timer.stop()
                self.daily_log_msg(f"DAILY SLOT TEMPLATE RESET | {document.get('document_name')}")
            except Exception as exc:
                QMessageBox.warning(dlg,"Daily Template",str(exc))

        btn_reset.clicked.connect(reset_template)
        load_template()
        # The plan is persisted even when no further edit event occurs.
        buttons.accepted.connect(_save_presets)
        update_status()
        if dlg.exec()!=QDialog.Accepted:return None
        return dlg._plan

    def daily_register_ok_selected(self):
        if not self._ensure_local_action('Daily Document'):
            return
        selected = self.daily_selected_indices()
        if not selected:
            QMessageBox.information(
                self, "Daily Document Register", "กรุณาเลือกเอกสารอย่างน้อย 1 รายการ"
            )
            return
        if not self._employee_id():
            QMessageBox.warning(self, "QAC Login", "กรุณากรอก Employee ID")
            self.txt_employee_id.setFocus()
            return
        if self.daily_register_worker and self.daily_register_worker.isRunning():
            QMessageBox.information(self, "Daily Document Register", "Register กำลังทำงานอยู่")
            return

        documents = []
        not_found = []
        for row in selected:
            result = self.daily_scan_results.get(row) or {}
            if (str(result.get("scan_status") or "") == "FOUND"
                and str(result.get("task_id") or "").strip()
                and result.get("_scanned_production_date") == self.daily_date.date().toString("yyyy-MM-dd")):
                documents.append(dict(result, _ui_row=row))
            else:
                name = ""
                if 0 <= row < len(self.daily_filtered_rows):
                    name = str(self.daily_filtered_rows[row].get("document_name") or "")
                not_found.append(name or f"row {row + 1}")
        if not documents:
            QMessageBox.information(
                self,
                "Daily Document Register",
                "รายการที่เลือกยังไม่เป็น FOUND กรุณากด Scan Selected ก่อน",
            )
            return

        # Daily-only: discover the first Measure HTML and ask per-item/per-slot.
        # No Sample Register count, selector, or mapping enters this workflow.
        for document in documents:
            try:
                cfg = self.browser_cfg()
                self.daily_log_msg(
                    f"DAILY HTML SCAN START | task={document.get('task_id')} | "
                    f"document={document.get('document_name')}"
                )
                scan_document = dict(document)
                scan_document['_daily_production_date'] = self.daily_date.date().toString('yyyy-MM-dd')
                if self.chk_daily_ref.isChecked():
                    ref_date = self.daily_ref_date.date().toString('yyyy-MM-dd')
                    active_date = self.daily_date.date().toString('yyyy-MM-dd')
                    if ref_date >= active_date:
                        QMessageBox.warning(self, 'Reference Date', 'Reference Date ต้องอยู่ก่อน Production Date')
                        return
                    scan_document['_daily_reference_date'] = ref_date
                    self.daily_log_msg(f'DAILY REFERENCE REQUEST | reference={ref_date} | task={document.get("task_id")}')
                thread = DailySlotScanThread(cfg['cdp_url'], scan_document)
                scan_state = {'schema': None, 'error': None}
                loader = QProgressDialog(
                    "กำลังอ่านหน้า Measure และ Result Slot จาก QAC...", "", 0, 0, self
                )
                loader.setWindowTitle("Daily Document HTML Scan")
                loader.setCancelButton(None)
                loader.setMinimumDuration(0)
                thread.schema_ready.connect(lambda fields: scan_state.__setitem__('schema', fields))
                thread.scan_error.connect(lambda message: scan_state.__setitem__('error', message))
                thread.progress.connect(self.daily_log_msg)
                thread.finished.connect(loader.accept)
                thread.start()
                loader.exec()
                thread.wait()
                if scan_state['error']:
                    raise RuntimeError(scan_state['error'])
                schema=scan_state['schema']
                if not schema:
                    raise RuntimeError('ไม่พบ Inspection Items จาก HTML ของ QAC')
            except Exception as exc:
                self.daily_log_msg(f"DAILY HTML SCAN ERROR | {document.get('task_id')} | {exc}")
                QMessageBox.warning(
                    self, "Daily Document HTML",
                    f"อ่านหน้าแรกของเอกสารไม่สำเร็จ กรุณา Scan ใหม่\n{exc}"
                )
                return
            selected_plan = self._prompt_daily_slot_plan(document, schema)
            if selected_plan is None:
                self.daily_log_msg(f"DAILY SLOT CANCELLED | {document.get('task_id')}")
                return
            from app.daily_slot_schema import validate_daily_slot_plan
            try:
                if selected_plan:
                    validate_daily_slot_plan(schema,selected_plan)
            except ValueError as exc:
                self.daily_log_msg(f"DAILY SLOT PLAN INVALID | {exc}")
                QMessageBox.warning(self, "Daily Slot Order", str(exc))
                return
            if not selected_plan:
                self.daily_log_msg(
                    f"DAILY REGISTER SKIPPED | task={document.get('task_id')} | "
                    "พบผลเดิม และพนักงานไม่ได้เลือกรายการใหม่"
                )
                document['_daily_skip_existing'] = True
            else:
                document['_daily_slot_plan'] = selected_plan
            self.daily_log_msg(
                f"DAILY SLOT PLAN CONFIRMED | task={document.get('task_id')} | "
                f"items={len(selected_plan)} | selections="
                f"{sum(len(x) for x in selected_plan.values())}"
            )

        documents = [doc for doc in documents if not doc.get('_daily_skip_existing')]
        if not documents:
            QMessageBox.information(
                self, "Daily Document", "ตรวจพบ Result เดิมใน QAC และไม่มี Slot ใหม่ที่ต้องลงทะเบียน"
            )
            return

        dry_run = False
        answer = QMessageBox.question(
            self, "Confirm Daily QAC Register",
            f"ลง Daily Check Sheet จำนวน {len(documents)} เอกสาร\n"
            "โปรแกรมจะลงเฉพาะ Item/Slot/Result ที่เลือกจาก HTML เท่านั้น\n"
            "รายการที่ไม่เลือก จะไม่ถูกแก้ไข\n"
            "Sample Register ไม่เกี่ยวข้องกับการลงทะเบียนครั้งนี้\n\n"
            "ต้องการเริ่มบันทึกจริงหรือไม่?",
        )
        if answer != QMessageBox.Yes:
            return

        production_date = self.daily_date.date().toString("yyyy-MM-dd")
        self.daily_register_progress.setValue(0)
        self.btn_daily_register_ok.setEnabled(False)
        self.btn_daily_register_pause.setEnabled(False)
        self.btn_daily_register_resume.setEnabled(False)
        self.btn_daily_register_stop.setEnabled(True)
        self._daily_retry_payload = (production_date, [dict(d) for d in documents], dry_run)
        self.btn_daily_register_retry.setEnabled(False)
        self._pending_daily_register_payload = (production_date, documents, dry_run)
        suffix = f" | skip not FOUND={len(not_found)}" if not_found else ""
        self.daily_log_msg(
            f"DAILY REGISTER REQUEST | date={production_date} | selected={len(documents)} | "
            f"LIVE WRITE{suffix}"
        )
        self.ensure_qac_module("daily_document")

    def _start_daily_register_worker(self, production_date, documents, dry_run):
        cfg = self.browser_cfg()
        if not cdp_ready(cfg["cdp_url"]):
            self._daily_register_failed("QAC Browser ยังไม่พร้อม")
            return
        register_settings = dict(self.settings or {})
        register_cfg = dict(register_settings.get("daily_document_register", {}) or {})
        register_cfg["history_root"] = str(getattr(self, "daily_history_root", program_dir() / "qac_html_exports"))
        register_cfg["history_lookback_days"] = 1
        register_cfg["use_previous_day_number"] = False
        register_settings["daily_document_register"] = register_cfg
        self.daily_register_worker = DailyDocumentRegisterWorker(
            cfg["cdp_url"], production_date, documents, settings=register_settings, dry_run=dry_run
        )
        self.daily_register_worker.progress.connect(self._daily_register_progress)
        self.daily_register_worker.completed.connect(self._daily_register_completed)
        self.daily_register_worker.failed.connect(self._daily_register_failed)
        self.btn_daily_register_pause.setEnabled(True)
        self.btn_daily_register_stop.setEnabled(True)
        self.daily_register_worker.start()

    def _daily_register_progress(self, message: str):
        self.daily_log_msg(message)
        match = re.search(r"\[(\d+)/(\d+)\]", str(message))
        if match and int(match.group(2)) > 0:
            self.daily_register_progress.setValue(
                int(int(match.group(1)) * 100 / int(match.group(2)))
            )

    def _daily_register_completed(self, result):
        self.daily_register_progress.setValue(100)
        self.btn_daily_register_ok.setEnabled(True)
        self.btn_daily_register_pause.setEnabled(False)
        self.btn_daily_register_resume.setEnabled(False)
        self.btn_daily_register_stop.setEnabled(False)
        summary = (
            f"documents={(result or {}).get('documents', 0)} | "
            f"saved={(result or {}).get('saved', 0)} | "
            f"would_fill={(result or {}).get('would_fill', 0)} | "
            f"skipped={(result or {}).get('skipped', 0)} | "
            f"errors={(result or {}).get('errors', 0)} | "
            f"number_no_actual={(result or {}).get('numeric_missing', 0)} | "
            f"history_refs={(result or {}).get('history_references', 0)}"
        )
        incomplete = int((result or {}).get('errors') or 0) > 0
        self.btn_daily_register_retry.setEnabled(incomplete and bool(getattr(self, '_daily_retry_payload', None)))
        if not incomplete:
            self._daily_retry_payload = None
        self.daily_log_msg(f"DAILY REGISTER {'INCOMPLETE' if incomplete else 'DONE'} | {summary}")
        self.audit.write("DAILY_DOCUMENT_REGISTER", status="ERROR" if incomplete else "OK", summary=summary)
        if incomplete:
            QMessageBox.warning(self, "Daily Document Register - Incomplete", summary + "\nตรวจสอบข้อผิดพลาดและสถานะ QAC ก่อน Retry; หาก Task/วันที่ยังตรงกันให้ใช้แผนเดิมได้ โดยระบบตรวจ EXIST สดอีกครั้งก่อน Save")
        else:
            QMessageBox.information(self, "Daily Document Register", summary)

    def _daily_register_failed(self, error: str):
        self.btn_daily_register_retry.setEnabled(bool(getattr(self, '_daily_retry_payload', None)))
        self.btn_daily_register_ok.setEnabled(True)
        self.btn_daily_register_pause.setEnabled(False)
        self.btn_daily_register_resume.setEnabled(False)
        self.btn_daily_register_stop.setEnabled(False)
        self.daily_log_msg(f"DAILY REGISTER STOPPED | {error}")
        self.audit.write("DAILY_DOCUMENT_REGISTER", status="ERROR", error=str(error))
        QMessageBox.warning(self, "Daily Document Register", str(error))

    def retry_daily_register_incomplete(self):
        """Reuse the confirmed plan, NOT the previous QAC save statuses.

        The register worker re-opens the exact Task and re-reads the live Slot
        state before each write. Existing results are skipped automatically.
        """
        payload = getattr(self, '_daily_retry_payload', None)
        if not payload:
            QMessageBox.information(self, 'Daily Retry', 'ไม่มี Slot Plan ที่ยืนยันไว้สำหรับ Retry')
            return
        if self.daily_register_worker and self.daily_register_worker.isRunning():
            return
        production_date, documents, dry_run = payload
        if production_date != self.daily_date.date().toString('yyyy-MM-dd'):
            self._daily_retry_payload = None
            self.btn_daily_register_retry.setEnabled(False)
            QMessageBox.warning(self, 'Daily Retry', 'วันที่เปลี่ยนแล้ว ต้อง Scan และยืนยันแผนใหม่')
            return
        if any(not d.get('task_id') or not d.get('_daily_slot_plan') for d in documents):
            QMessageBox.warning(self, 'Daily Retry', 'ข้อมูล Task ID หรือ Slot Plan ไม่ครบ')
            return
        answer = QMessageBox.question(
            self, 'Retry Incomplete Daily Register',
            f'ใช้ Slot Plan เดิมสำหรับ {len(documents)} เอกสาร โดยไม่ Scan เพื่อเลือกใหม่\n'
            'ระบบจะตรวจสถานะ QAC สดก่อนเขียน และข้าม EXIST ทุก Slot\n'
            'หากผล Save ก่อนหน้ายังไม่แน่ชัด ห้ามลงซ้ำโดยไม่ยืนยันสถานะ\n\n'
            'ต้องการ Retry หรือไม่?')
        if answer != QMessageBox.Yes:
            return
        self.btn_daily_register_retry.setEnabled(False)
        self.btn_daily_register_ok.setEnabled(False)
        self._pending_daily_register_payload = (production_date, [dict(d) for d in documents], dry_run)
        self.daily_log_msg(f'DAILY RETRY PLAN REUSED | date={production_date} docs={len(documents)} '
                           '| QAC live state recheck before each write')
        self.ensure_qac_module('daily_document')

    def pause_daily_register(self):
        if self.daily_register_worker and self.daily_register_worker.isRunning():
            self.daily_register_worker.request_pause()
            self.btn_daily_register_pause.setEnabled(False)
            self.btn_daily_register_resume.setEnabled(True)
            self.daily_log_msg("DAILY REGISTER PAUSED | จะหยุดก่อนเปิดเอกสารถัดไป")

    def resume_daily_register(self):
        if self.daily_register_worker and self.daily_register_worker.isRunning():
            self.daily_register_worker.request_resume()
            self.btn_daily_register_pause.setEnabled(True)
            self.btn_daily_register_resume.setEnabled(False)
            self.daily_log_msg("DAILY REGISTER RESUMED")

    def stop_daily_register(self):
        if self._pending_daily_register_payload is not None:
            self._pending_daily_register_payload = None
            self._daily_register_failed("ยกเลิกก่อนเริ่ม Daily Register")
            return
        if self.daily_register_worker and self.daily_register_worker.isRunning():
            self.daily_register_worker.request_stop()
            self.btn_daily_register_stop.setEnabled(False)
            self.daily_log_msg("DAILY REGISTER STOP REQUESTED | จะหยุดอย่างปลอดภัย")

    # ---------------- Alarm Import ----------------
    def _build_excel_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        info = QLabel(
            "Alarm Import: รองรับ CSV / XLSX / XLSM หลายไฟล์\n"
            "Source: B=Time, D=Alarm Code, E=Message, F=Machine Code | "
            "Time Stop = Column B + 1 minute"
        )
        root.addWidget(info)

        doc_row = QHBoxLayout()
        doc_row.addWidget(QLabel("QAC Document"))
        self.cmb_alarm_doc = QComboBox()
        self.cmb_alarm_doc.currentIndexChanged.connect(
            self.alarm_document_changed
        )
        doc_row.addWidget(self.cmb_alarm_doc, 1)

        doc_row.addWidget(QLabel("Model"))
        self.cmb_alarm_model = make_searchable(QComboBox())
        doc_row.addWidget(self.cmb_alarm_model, 1)

        # I-TAG Shift is independent from DAY/NIGHT and is 1..6.
        doc_row.addWidget(QLabel("Shift"))
        self.cmb_itag_shift = QComboBox()
        for shift_no in range(1, 7):
            self.cmb_itag_shift.addItem(str(shift_no), shift_no)
        self.cmb_itag_shift.currentIndexChanged.connect(
            self.itag_line_changed
        )
        doc_row.addWidget(self.cmb_itag_shift)

        root.addLayout(doc_row)

        itag_row = QHBoxLayout()
        itag_row.addWidget(QLabel("Production Line Found"))
        self.cmb_itag_line = make_searchable(QComboBox())
        self.cmb_itag_line.addItem("Select Production Line Found", None)
        self.cmb_itag_line.currentIndexChanged.connect(
            self.itag_line_changed
        )
        itag_row.addWidget(self.cmb_itag_line, 1)

        root.addLayout(itag_row)

        file_row = QHBoxLayout()
        self.btn_alarm_files = QPushButton("Add Files")
        self.btn_alarm_clear = QPushButton("Clear Files")
        self.btn_alarm_select_all = QPushButton("Check All")
        self.btn_alarm_unselect_all = QPushButton("Uncheck All")
        self.btn_alarm_refresh = QPushButton("Refresh QAC Status")

        self.btn_alarm_files.clicked.connect(self.add_alarm_files)
        self.btn_alarm_clear.clicked.connect(self.clear_alarm_files)
        self.btn_alarm_select_all.clicked.connect(
            lambda: self.set_all_alarm_checks(True)
        )
        self.btn_alarm_unselect_all.clicked.connect(
            lambda: self.set_all_alarm_checks(False)
        )
        self.btn_alarm_refresh.clicked.connect(self.refresh_existing_alarm_status)

        file_row.addWidget(self.btn_alarm_files)
        file_row.addWidget(self.btn_alarm_clear)
        file_row.addWidget(self.btn_alarm_select_all)
        file_row.addWidget(self.btn_alarm_unselect_all)
        file_row.addWidget(self.btn_alarm_refresh)

        self.lbl_alarm_files = QLabel("0 files | 0 rows")
        file_row.addWidget(self.lbl_alarm_files)
        file_row.addStretch()
        root.addLayout(file_row)

        self.tbl_alarm = QTableWidget(0, 11)
        self.tbl_alarm.setHorizontalHeaderLabels([
            "Check",
            "Status",
            "Column F",
            "Machine",
            "NG Product",
            "Column E",
            "Column B",
            "Time Stop",
            "Process Found",
            "Action Type",
            "Action Detail",
        ])
        self.tbl_alarm.verticalHeader().setDefaultSectionSize(30)

        make_table_columns_resizable(self.tbl_alarm, persistence_key="alarm_import")

        root.addWidget(self.tbl_alarm, 1)

        run_row = QHBoxLayout()

        self.btn_alarm_import = QPushButton("IMPORT TO QAC")
        self.btn_alarm_pause = QPushButton("Pause")
        self.btn_alarm_resume = QPushButton("Resume")
        self.btn_alarm_stop = QPushButton("Stop")
        self.btn_alarm_import.clicked.connect(self.run_alarm_import)
        self.btn_alarm_pause.clicked.connect(self.pause_alarm_import)
        self.btn_alarm_resume.clicked.connect(self.resume_alarm_import)
        self.btn_alarm_stop.clicked.connect(self.stop_alarm_import)

        run_row.addStretch()
        run_row.addWidget(self.btn_alarm_import)
        run_row.addWidget(self.btn_alarm_pause)
        run_row.addWidget(self.btn_alarm_resume)
        run_row.addWidget(self.btn_alarm_stop)
        root.addLayout(run_row)

        self.alarm_log = QTextEdit()
        self.alarm_log.setReadOnly(True)
        self.alarm_log.setMaximumHeight(180)
        root.addWidget(self.alarm_log)

        return w

    # ---------------- OCR NG Import ----------------
    def _build_ocr_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        info = QLabel(
            "OCR NG Import: อ่านภาพ AUTO REJECT / Machine Judge\\n"
            "COUNTER NG จะถูกอ่านเพื่ออ้างอิง แต่ไม่สร้าง Register Row | "
            "Message และ Counter แก้ไขได้ก่อน Register"
        )
        root.addWidget(info)

        top = QHBoxLayout()

        top.addWidget(QLabel("QAC Document"))
        self.cmb_ocr_doc = QComboBox()
        self.cmb_ocr_doc.currentIndexChanged.connect(
            self.ocr_document_changed
        )
        top.addWidget(self.cmb_ocr_doc, 2)

        top.addWidget(QLabel("Model"))
        self.cmb_ocr_model = make_searchable(
            QComboBox()
        )
        top.addWidget(self.cmb_ocr_model, 2)

        top.addWidget(QLabel("Shift"))
        self.cmb_ocr_shift = QComboBox()
        for shift_no in range(1, 7):
            self.cmb_ocr_shift.addItem(
                str(shift_no),
                shift_no
            )
        top.addWidget(self.cmb_ocr_shift)

        root.addLayout(top)

        line_row = QHBoxLayout()
        line_row.addWidget(
            QLabel("Production Line Found")
        )
        self.cmb_ocr_itag_line = make_searchable(
            QComboBox()
        )
        self.cmb_ocr_itag_line.addItem(
            "Select Production Line Found",
            None
        )
        self.cmb_ocr_itag_line.currentIndexChanged.connect(
            self.ocr_itag_line_changed
        )
        line_row.addWidget(
            self.cmb_ocr_itag_line,
            1
        )
        root.addLayout(line_row)

        file_row = QHBoxLayout()

        self.btn_ocr_add = QPushButton(
            "Add Images"
        )
        self.btn_ocr_run = QPushButton(
            "Run OCR"
        )
        self.btn_ocr_clear = QPushButton(
            "Clear"
        )
        self.btn_ocr_check = QPushButton(
            "Check All"
        )
        self.btn_ocr_uncheck = QPushButton(
            "Uncheck All"
        )
        self.btn_ocr_refresh = QPushButton(
            "Refresh QAC Status"
        )

        self.btn_ocr_add.clicked.connect(
            self.add_ocr_images
        )
        self.btn_ocr_run.clicked.connect(
            self.run_ocr
        )
        self.btn_ocr_clear.clicked.connect(
            self.clear_ocr
        )
        self.btn_ocr_check.clicked.connect(
            lambda: self.set_all_ocr_checks(True)
        )
        self.btn_ocr_uncheck.clicked.connect(
            lambda: self.set_all_ocr_checks(False)
        )
        self.btn_ocr_refresh.clicked.connect(self.refresh_existing_ocr_status)

        for button in (
            self.btn_ocr_add,
            self.btn_ocr_run,
            self.btn_ocr_clear,
            self.btn_ocr_check,
            self.btn_ocr_uncheck,
            self.btn_ocr_refresh,
        ):
            file_row.addWidget(button)

        self.lbl_ocr_files = QLabel(
            "0 images | 0 rows"
        )
        file_row.addWidget(
            self.lbl_ocr_files
        )
        file_row.addStretch()
        root.addLayout(file_row)

        self.tbl_ocr = QTableWidget(
            0,
            11
        )
        self.tbl_ocr.setHorizontalHeaderLabels([
            "Check",
            "Status",
            "Source",
            "Judge",
            "Message (Editable)",
            "Counter / NG Qty",
            "Machine",
            "NG Product",
            "Start",
            "Time Stop",
            "Process Found",
        ])
        self.tbl_ocr.verticalHeader().setDefaultSectionSize(
            32
        )

        # Source is retained internally for audit/traceability but is not
        # displayed in the OCR work table.
        self.tbl_ocr.setColumnHidden(2, True)
        make_table_columns_resizable(self.tbl_ocr, persistence_key="ocr_ng_import")

        root.addWidget(
            self.tbl_ocr,
            1
        )

        run_row = QHBoxLayout()

        self.chk_ocr_dry = QCheckBox(
            "Dry Run (ไม่บันทึกจริง)"
        )
        self.chk_ocr_dry.setChecked(True)

        self.btn_ocr_register = QPushButton(
            "REGISTER OCR TO QAC"
        )
        self.btn_ocr_pause = QPushButton(
            "Pause"
        )
        self.btn_ocr_resume = QPushButton(
            "Resume"
        )
        self.btn_ocr_stop = QPushButton(
            "Stop"
        )

        self.btn_ocr_register.clicked.connect(
            self.run_ocr_register
        )
        self.btn_ocr_pause.clicked.connect(
            self.pause_ocr_register
        )
        self.btn_ocr_resume.clicked.connect(
            self.resume_ocr_register
        )
        self.btn_ocr_stop.clicked.connect(
            self.stop_ocr_register
        )

        run_row.addWidget(
            self.chk_ocr_dry
        )
        run_row.addStretch()
        run_row.addWidget(
            self.btn_ocr_register
        )
        run_row.addWidget(
            self.btn_ocr_pause
        )
        run_row.addWidget(
            self.btn_ocr_resume
        )
        run_row.addWidget(
            self.btn_ocr_stop
        )
        root.addLayout(run_row)

        progress_row = QHBoxLayout()

        self.lbl_ocr_progress = QLabel(
            "Ready"
        )
        self.lbl_ocr_progress.setMinimumWidth(
            260
        )

        self.ocr_progress_bar = QProgressBar()
        self.ocr_progress_bar.setRange(
            0,
            100
        )
        self.ocr_progress_bar.setValue(
            0
        )
        self.ocr_progress_bar.setFormat(
            "%p%"
        )

        progress_row.addWidget(
            self.lbl_ocr_progress
        )
        progress_row.addWidget(
            self.ocr_progress_bar,
            1
        )
        root.addLayout(
            progress_row
        )

        self.ocr_log = QTextEdit()
        self.ocr_log.setReadOnly(True)
        self.ocr_log.setMaximumHeight(170)
        root.addWidget(
            self.ocr_log
        )

        return w

    # ---------------- Production Output Import ----------------
    def _build_production_output_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)

        info = QLabel(
            "Production Output Import: Net Serial รายชั่วโมง (Gross - Reject) "
            "แล้ว Update Actual Qty ของ Production Output เดิม\n"
            "สร้าง Setup / Run-up ก่อนเริ่มผลิต และ Stop Line หลังจบผลิต"
        )
        root.addWidget(info)

        top = QHBoxLayout()
        top.addWidget(QLabel("QAC Document"))

        self.cmb_prod_doc = QComboBox()
        self.cmb_prod_doc.currentIndexChanged.connect(
            self.production_document_changed
        )
        top.addWidget(self.cmb_prod_doc, 2)

        top.addWidget(QLabel("Model"))
        self.cmb_prod_model = make_searchable(QComboBox())
        top.addWidget(self.cmb_prod_model, 2)

        root.addLayout(top)

        file_row = QHBoxLayout()
        self.btn_prod_file = QPushButton("Select Line Data")
        self.btn_prod_refresh = QPushButton("Refresh QAC Status")
        self.btn_prod_check_all = QPushButton("Check All")
        self.btn_prod_uncheck_all = QPushButton("Uncheck All")
        self.lbl_prod_file = QLabel("ยังไม่ได้เลือกไฟล์")

        self.btn_prod_file.clicked.connect(
            self.select_production_file
        )
        self.btn_prod_refresh.clicked.connect(
            self.refresh_production_status
        )
        self.btn_prod_check_all.clicked.connect(
            lambda: self.set_all_production_checks(True)
        )
        self.btn_prod_uncheck_all.clicked.connect(
            lambda: self.set_all_production_checks(False)
        )

        file_row.addWidget(self.btn_prod_file)
        file_row.addWidget(self.btn_prod_refresh)
        file_row.addWidget(self.btn_prod_check_all)
        file_row.addWidget(self.btn_prod_uncheck_all)
        file_row.addWidget(self.lbl_prod_file, 1)
        root.addLayout(file_row)

        self.lbl_prod_summary = QLabel(
            "First: - | Last: - | Total: - | Shift: -"
        )
        self.lbl_prod_summary.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        root.addWidget(self.lbl_prod_summary)

        self.lbl_prod_time_summary = QLabel(
            "Time Validation: WAITING OUTPUT / WAITING CHECK"
        )
        self.lbl_prod_time_summary.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        root.addWidget(self.lbl_prod_time_summary)

        self.tbl_prod = QTableWidget(0, 13)
        self.tbl_prod.setHorizontalHeaderLabels([
            "Check",
            "Status",
            "Type",
            "Interval",
            "QAC Time",
            "File Qty",
            "QAC Qty",
            "Action",
            "MCT sec",
            "Expected",
            "Event min",
            "Missing min",
            "Time Check",
        ])
        self.tbl_prod.cellDoubleClicked.connect(
            self.production_hour_double_clicked
        )

        make_table_columns_resizable(self.tbl_prod, persistence_key="production_output_import")

        root.addWidget(self.tbl_prod, 1)

        run_row = QHBoxLayout()

        self.btn_prod_transfer = QPushButton("Transfer Data to QAC")
        self.btn_prod_transfer.setToolTip("Upload Line Data → ตรวจ PASS → Checked")
        self.btn_prod_transfer.clicked.connect(self.run_production_transfer)
        self.btn_prod_run = QPushButton("UPDATE QAC")
        self.btn_prod_pause = QPushButton("Pause")
        self.btn_prod_resume = QPushButton("Resume")
        self.btn_prod_stop = QPushButton("Stop")

        self.btn_prod_run.clicked.connect(
            self.run_production_output
        )
        self.btn_prod_pause.clicked.connect(
            self.pause_production_output
        )
        self.btn_prod_resume.clicked.connect(
            self.resume_production_output
        )
        self.btn_prod_stop.clicked.connect(
            self.stop_production_output
        )

        run_row.addStretch()
        run_row.addWidget(self.btn_prod_transfer)
        run_row.addWidget(self.btn_prod_run)
        run_row.addWidget(self.btn_prod_pause)
        run_row.addWidget(self.btn_prod_resume)
        run_row.addWidget(self.btn_prod_stop)

        root.addLayout(run_row)

        progress_row = QHBoxLayout()

        self.lbl_prod_progress = QLabel("Ready")
        self.prod_progress = QProgressBar()
        self.prod_progress.setRange(0, 100)
        self.prod_progress.setValue(0)

        progress_row.addWidget(self.lbl_prod_progress)
        progress_row.addWidget(self.prod_progress, 1)

        root.addLayout(progress_row)

        self.prod_log = QTextEdit()
        self.prod_log.setReadOnly(True)
        self.prod_log.setMaximumHeight(170)
        root.addWidget(self.prod_log)

        return w

    def run_production_transfer(self):
        if not self._ensure_local_action('Production Transfer'):
            return
        if self.production_transfer_worker and self.production_transfer_worker.isRunning():
            QMessageBox.warning(self, "QAC Transfer", "Transfer กำลังทำงานอยู่")
            return
        path = str(self.production_file or "")
        if not path or not Path(path).is_file():
            QMessageBox.warning(self, "QAC Transfer", "กรุณาเลือกไฟล์ Line Data ก่อน")
            return
        cfg = self.settings
        cdp_url = str(cfg.get("cdp_url") or "")
        employee_id = self._employee_id()
        if not cdp_url or not employee_id:
            QMessageBox.warning(self, "QAC Transfer", "ไม่พบ CDP URL หรือ Employee ID ใน Settings")
            return
        answer = QMessageBox.question(
            self, "Transfer Data to QAC",
            "โปรแกรมจะอัปโหลดไฟล์จริงไปยัง QAC และกด Checked เฉพาะเมื่อ Judge PASS ครบทุกหัวข้อ\n"
            f"ไฟล์: {Path(path).name}\n\nยืนยันดำเนินการหรือไม่?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        self.btn_prod_transfer.setEnabled(False)
        self.production_transfer_worker = ProductionTransferWorker(cdp_url, employee_id, path)
        self.production_transfer_worker.progress.connect(self.production_log_msg)
        self.production_transfer_worker.completed.connect(self.production_transfer_completed)
        self.production_transfer_worker.failed.connect(self.production_transfer_failed)
        self.production_transfer_worker.finished.connect(
            lambda: self.btn_prod_transfer.setEnabled(True)
        )
        self.production_transfer_worker.start()

    def production_transfer_completed(self, result):
        self.production_log_msg(f"TRANSFER DONE | {result}")
        QMessageBox.information(self, "Transfer Data to QAC", f"QAC Checked: {result}")

    def production_transfer_failed(self, error):
        self.production_log_msg(f"TRANSFER STOPPED | {error}")
        QMessageBox.critical(self, "Transfer Data to QAC", str(error) +
            "\n\nหากอัปโหลดไปแล้ว ห้ามกดซ้ำจนกว่าจะตรวจ Lot บน QAC")

    def production_log_msg(self, text):
        text = str(text)
        self.prod_log.append(text)

        self.audit.write(
            "PRODUCTION_OUTPUT_LOG",
            message=text
        )

        match = re.search(
            r"\[Production\s+(\d+)/(\d+)\]",
            text
        )

        if match:
            current = int(match.group(1))
            total = max(1, int(match.group(2)))

            self.prod_progress.setValue(
                int((current / total) * 100)
            )
            self.lbl_prod_progress.setText(
                f"Processing {current}/{total}"
            )

    def production_document_changed(self, index):
        self.cmb_prod_model.clear()

        if index < 0 or index >= len(self.documents):
            return

        doc = self.documents[index]

        for model in doc.models:
            self.cmb_prod_model.addItem(
                model.label,
                model
            )

        if self.production_data:
            hint = (
                self.production_data.model_hint
                .strip()
                .lower()
            )

            if hint:
                for i in range(
                    self.cmb_prod_model.count()
                ):
                    option = self.cmb_prod_model.itemData(i)

                    name = str(
                        getattr(option, "name", "")
                    ).strip().lower()

                    if name == hint:
                        self.cmb_prod_model.setCurrentIndex(i)
                        break

    def select_production_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Line Data",
            "",
            "Line Data (*.xlsx *.xlsm *.csv)"
        )

        if not path:
            return

        cfg = self.settings.get(
            "production_output_import",
            {}
        )

        try:
            data = load_production_line_file(
                path,
                day_start=cfg.get(
                    "day_shift_start",
                    "08:00"
                ),
                day_end=cfg.get(
                    "day_shift_end",
                    "20:00"
                ),
                night_start=cfg.get(
                    "night_shift_start",
                    "20:00"
                ),
                night_end=cfg.get(
                    "night_shift_end",
                    "08:00"
                ),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Line Data",
                str(e)
            )
            return

        self.production_file = path
        self.production_data = data

        self.lbl_prod_file.setText(
            data.source_file
        )

        self.lbl_prod_summary.setText(
            f"Date: {data.production_date} | "
            f"Shift: {data.shift_name} | "
            f"First: {data.first_datetime.strftime('%H:%M:%S')} | "
            f"Last: {data.last_datetime.strftime('%H:%M:%S')} | "
            f"Gross: {data.counted_total + data.reject_total} | "
            f"Reject: {data.reject_total} | Net: {data.counted_total} | "
            f"Workbook Total: "
            f"{data.workbook_total if data.workbook_total is not None else '-'}"
        )

        for warning in data.warnings:
            self.production_log_msg(
                f"WARNING: {warning}"
            )

        self.production_document_changed(
            self.cmb_prod_doc.currentIndex()
        )
        self.rebuild_production_table()
        self.refresh_production_status()

    @staticmethod
    def _production_option_match(
        event_value,
        event_label,
        config_value,
        config_label
    ):
        config_value = str(
            config_value or ""
        ).strip()

        if (
            config_value
            and str(event_value or "").strip()
            == config_value
        ):
            return True

        event_label_norm = " ".join(
            str(event_label or "")
            .strip()
            .lower()
            .split()
        )
        config_label_norm = " ".join(
            str(config_label or "")
            .strip()
            .lower()
            .split()
        )

        return bool(
            config_label_norm
            and event_label_norm
            == config_label_norm
        )

    @staticmethod
    def _parse_qac_production_date(
        value
    ):
        raw = str(value or "").strip()

        for fmt in (
            "%Y-%m-%d",
            "%d-%m-%y",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(
                    raw,
                    fmt
                ).date()
            except ValueError:
                pass

        return None

    def _production_actions(self):
        if not self.production_data:
            raise ValueError(
                "กรุณาเลือก Line Data"
            )

        di = self.cmb_prod_doc.currentIndex()

        if di < 0 or di >= len(self.documents):
            raise ValueError(
                "กรุณาเลือก QAC Document"
            )

        doc = self.documents[di]
        model = self.cmb_prod_model.currentData()

        if model is None:
            raise ValueError(
                "กรุณาเลือก Model"
            )

        data = self.production_data

        # Wrong-document interlocks.
        if (
            data.shift_name.upper()
            not in str(doc.shift or "").upper()
        ):
            raise ValueError(
                f"Shift ไม่ตรง: File={data.shift_name}, "
                f"QAC={doc.shift}"
            )

        qac_date = self._parse_qac_production_date(
            doc.production_date
        )

        if (
            qac_date is not None
            and qac_date != data.production_date
        ):
            raise ValueError(
                f"Production Date ไม่ตรง: "
                f"File={data.production_date}, "
                f"QAC={doc.production_date}"
            )

        if (
            data.line_no_hint is not None
            and f"TS{data.line_no_hint}"
            not in str(doc.line or "").upper()
        ):
            raise ValueError(
                f"Line ไม่ตรง: File=TS{data.line_no_hint}, "
                f"QAC={doc.line}"
            )

        cfg = self.settings.get(
            "production_output_import",
            {}
        )
        records = self.settings.get(
            "auto_register_records",
            {}
        )
        production_cfg = records.get(
            "production",
            {}
        )

        actions = []

        setup = cfg.get("setup", {})

        actions.append({
            "kind": "setup",
            "downtime_value": str(
                setup.get("downtime_value", "")
            ),
            "downtime_label": str(
                setup.get("downtime_label", "Setup")
            ),
            "category_value": str(
                setup.get("category_value", "")
            ),
            "category_label": str(
                setup.get("category_label", "Run-up")
            ),
            "model_value": model.value,
            "model_name": model.name,
            "machine_value": str(
                setup.get("machine_value", "")
            ),
            "machine_label": "",
            "machine_search_text": str(
                setup.get(
                    "machine_search_text",
                    "Housing assembly"
                )
            ),
            "description": str(
                setup.get("description", "Run Up")
            ),
            "start": data.shift_start,
            "end": data.first_datetime.strftime(
                "%H:%M:%S"
            ),
        })

        for item in data.hourly:
            actions.append({
                "kind": "production_update",
                "downtime_value": str(
                    production_cfg.get(
                        "downtime_value",
                        ""
                    )
                ),
                "downtime_label": str(
                    production_cfg.get(
                        "downtime_label",
                        "Production Output"
                    )
                ),
                "category_value": str(
                    production_cfg.get(
                        "category_value",
                        ""
                    )
                ),
                "category_label": str(
                    production_cfg.get(
                        "category_label",
                        "Normal Production"
                    )
                ),
                "model_value": model.value,
                "model_name": model.name,
                "interval_start": item.interval_start,
                "interval_end": item.interval_end,
                "qac_event_time": item.qac_event_time,
                "qty": item.qty,
            })

        stop_cfg = cfg.get(
            "stop_line",
            {}
        )

        actions.append({
            "kind": "stop_line",
            "downtime_value": str(
                stop_cfg.get(
                    "downtime_value",
                    ""
                )
            ),
            "downtime_label": str(
                stop_cfg.get(
                    "downtime_label",
                    "Schedule Downtime"
                )
            ),
            "category_value": str(
                stop_cfg.get(
                    "category_value",
                    ""
                )
            ),
            "category_label": str(
                stop_cfg.get(
                    "category_label",
                    "Stop line"
                )
            ),
            "description": str(
                stop_cfg.get(
                    "description",
                    "Stop Line"
                )
            ),
            "start": data.last_datetime.strftime(
                "%H:%M:%S"
            ),
            "end": data.shift_end,
        })

        return actions

    def _production_checkbox(
        self,
        row
    ):
        holder = self.tbl_prod.cellWidget(
            row,
            0
        )

        if holder is None:
            return None

        return holder.findChild(
            QCheckBox
        )

    def set_all_production_checks(
        self,
        checked
    ):
        for row in range(
            self.tbl_prod.rowCount()
        ):
            chk = self._production_checkbox(
                row
            )
            if chk:
                chk.setChecked(
                    bool(checked)
                )

    def _selected_production_actions(
        self,
        actions
    ):
        selected = []

        for row, action in enumerate(
            actions
        ):
            chk = self._production_checkbox(
                row
            )

            if (
                chk is not None
                and chk.isChecked()
            ):
                selected.append(
                    action
                )

        return selected

    def rebuild_production_table(self):
        self.tbl_prod.setRowCount(0)

        if not self.production_data:
            return

        try:
            actions = self._production_actions()
        except Exception as e:
            self.production_log_msg(
                f"PREVIEW ERROR: {e}"
            )
            return

        for action in actions:
            row = self.tbl_prod.rowCount()
            self.tbl_prod.insertRow(row)

            chk = QCheckBox()
            chk.setChecked(True)

            holder = QWidget()
            holder_layout = QHBoxLayout(
                holder
            )
            holder_layout.setContentsMargins(
                0,
                0,
                0,
                0
            )
            holder_layout.setAlignment(
                Qt.AlignCenter
            )
            holder_layout.addWidget(
                chk
            )
            self.tbl_prod.setCellWidget(
                row,
                0,
                holder
            )

            kind = action["kind"]

            if kind == "setup":
                values = [
                    "CHECKING...",
                    "Setup / Run-up",
                    f"{action['start']} - {action['end']}",
                    "-",
                    "-",
                    "-",
                    "CREATE IF MISSING",
                    "-", "-", "-", "-", "-",
                ]
            elif kind == "stop_line":
                values = [
                    "CHECKING...",
                    "Stop Line",
                    f"{action['start']} - {action['end']}",
                    "-",
                    "-",
                    "-",
                    "CREATE IF MISSING",
                    "-", "-", "-", "-", "-",
                ]
            else:
                values = [
                    "CHECKING...",
                    "Production Output",
                    (
                        f"{action['interval_start']} - "
                        f"{action['interval_end']}"
                    ),
                    action["qac_event_time"],
                    str(action["qty"]),
                    "-",
                    "UPDATE EXISTING",
                    "-", "-", "-", "-", "WAITING CHECK",
                ]

            for col, value in enumerate(
                values,
                1
            ):
                item = QTableWidgetItem(
                    str(value)
                )
                item.setFlags(
                    item.flags()
                    & ~Qt.ItemIsEditable
                )
                self.tbl_prod.setItem(
                    row,
                    col,
                    item
                )

    def _production_hour_context(self, row):
        if not self.production_data:
            return None
        try:
            actions = self._production_actions()
        except Exception:
            return None
        if row < 0 or row >= len(actions):
            return None
        action = actions[row]
        if action.get("kind") != "production_update":
            return None

        di = self.cmb_prod_doc.currentIndex()
        if di < 0 or di >= len(self.documents):
            return None
        doc = self.documents[di]
        model = self.cmb_prod_model.currentData()
        if model is None:
            return None

        line = str(getattr(doc, "line", "") or "").strip()
        model_name = str(getattr(model, "name", "") or "").strip()
        rule = resolve_mct_rule(self.settings, line, model_name)
        return {
            "action": action,
            "line": line,
            "model": model_name,
            "model_option": model,
            "document": doc,
            "rule": rule,
            "production_date": self.production_data.production_date,
        }

    def production_hour_double_clicked(self, row, _column):
        ctx = self._production_hour_context(row)
        if ctx is None:
            return
        self.open_hour_event_editor(row, ctx)

    def _manual_event_mode(self, downtime_label: str):
        text = " ".join(str(downtime_label or "").strip().lower().split())
        if "production output" in text:
            return "PRODUCTION"
        if "unreached mct" in text or "unreach mct" in text:
            return "PARTIAL_CAPACITY"
        return "TIME_LOSS"

    def _manual_event_widgets(
        self,
        table,
        row,
        event,
        downtimes,
        categories,
        machines,
        total_stations,
        on_changed=None,
    ):
        event = dict(event or {})

        downtime = QComboBox()
        downtime.addItem("Select DowTime", "")
        for opt in downtimes:
            downtime.addItem(opt.name, opt.value)
        table.setCellWidget(row, 0, downtime)

        category = QComboBox()
        category.addItem("Select Category", "")
        table.setCellWidget(row, 1, category)

        machine = QComboBox()
        machine.addItem("Select Machine", "")
        for opt in machines:
            machine.addItem(opt.name, opt.value)
        table.setCellWidget(row, 2, machine)

        start_edit = QLineEdit(str(event.get("start") or ""))
        start_edit.setPlaceholderText("20:00")
        table.setCellWidget(row, 3, start_edit)

        end_edit = QLineEdit(str(event.get("end") or ""))
        end_edit.setPlaceholderText("20:10")
        table.setCellWidget(row, 4, end_edit)

        stations = QSpinBox()
        stations.setRange(0, max(1, total_stations))
        stations.setValue(int(event.get("unavailable_stations") or 0))
        table.setCellWidget(row, 5, stations)

        remark = QLineEdit(str(event.get("remark") or ""))
        table.setCellWidget(row, 6, remark)

        down_by_value = {str(x.value): x for x in downtimes}
        categories_by_down = {}
        for opt in categories:
            categories_by_down.setdefault(str(opt.downtime_value), []).append(opt)

        def refresh_dependency(*_args):
            selected_down = str(downtime.currentData() or "")
            down_opt = down_by_value.get(selected_down)

            wanted_category_value = str(event.get("category_value") or "")
            wanted_category_label = str(event.get("category") or "")
            old_category_value = str(category.currentData() or "")

            category.blockSignals(True)
            category.clear()
            category.addItem("Select Category", "")
            for opt in categories_by_down.get(selected_down, []):
                category.addItem(opt.name, opt.value)
            target_category = wanted_category_value or old_category_value
            ci = category.findData(target_category) if target_category else -1
            if ci < 0 and wanted_category_label:
                ci = category.findText(wanted_category_label)
            category.setCurrentIndex(ci if ci >= 0 else 0)
            category.setEnabled(bool(selected_down))
            category.blockSignals(False)

            machine_required = bool(
                down_opt and getattr(down_opt, "machine_required", False)
            )
            machine.setEnabled(machine_required)
            if not machine_required:
                machine.setCurrentIndex(0)
            elif str(event.get("machine_value") or ""):
                mi = machine.findData(str(event.get("machine_value") or ""))
                if mi >= 0:
                    machine.setCurrentIndex(mi)
            elif str(event.get("machine") or ""):
                mi = machine.findText(str(event.get("machine") or ""))
                if mi >= 0:
                    machine.setCurrentIndex(mi)

            partial = self._manual_event_mode(
                down_opt.name if down_opt else ""
            ) == "PARTIAL_CAPACITY"
            stations.setEnabled(partial)
            if not partial:
                stations.setValue(0)

            if on_changed:
                on_changed()

        existing_down_value = str(event.get("downtime_value") or "")
        existing_down_label = str(event.get("event_type") or "")
        di = downtime.findData(existing_down_value) if existing_down_value else -1
        if di < 0 and existing_down_label:
            di = downtime.findText(existing_down_label)
        downtime.setCurrentIndex(di if di >= 0 else 0)

        downtime.currentIndexChanged.connect(refresh_dependency)
        category.currentIndexChanged.connect(lambda *_: on_changed() if on_changed else None)
        machine.currentIndexChanged.connect(lambda *_: on_changed() if on_changed else None)
        start_edit.textChanged.connect(lambda *_: on_changed() if on_changed else None)
        end_edit.textChanged.connect(lambda *_: on_changed() if on_changed else None)
        stations.valueChanged.connect(lambda *_: on_changed() if on_changed else None)
        remark.textChanged.connect(lambda *_: on_changed() if on_changed else None)
        refresh_dependency()

    def _collect_manual_event_table(self, table, downtimes):
        rows = []
        down_by_value = {str(x.value): x for x in downtimes}
        for row in range(table.rowCount()):
            downtime = table.cellWidget(row, 0)
            category = table.cellWidget(row, 1)
            machine = table.cellWidget(row, 2)
            start_edit = table.cellWidget(row, 3)
            end_edit = table.cellWidget(row, 4)
            stations = table.cellWidget(row, 5)
            remark = table.cellWidget(row, 6)

            start = start_edit.text().strip() if start_edit else ""
            end = end_edit.text().strip() if end_edit else ""
            down_value = str(downtime.currentData() or "") if downtime else ""
            down_label = downtime.currentText().strip() if downtime else ""
            category_value = str(category.currentData() or "") if category else ""
            category_label = category.currentText().strip() if category else ""
            machine_value = str(machine.currentData() or "") if machine else ""
            machine_label = machine.currentText().strip() if machine else ""

            # Empty starter row is ignored.
            if not start and not end and not down_value:
                continue

            down_opt = down_by_value.get(down_value)
            rows.append({
                "event_type": down_label,
                "downtime_value": down_value,
                "category": category_label,
                "category_value": category_value,
                "machine": machine_label if machine_value else "",
                "machine_value": machine_value,
                "loss_mode": self._manual_event_mode(down_label),
                "machine_required": bool(
                    down_opt and getattr(down_opt, "machine_required", False)
                ),
                "model_required": bool(
                    down_opt and getattr(down_opt, "model_required", False)
                ),
                "production_output_required": bool(
                    down_opt and getattr(down_opt, "production_output_required", False)
                ),
                "start": start,
                "end": end,
                "unavailable_stations": int(stations.value()) if stations else 0,
                "remark": remark.text().strip() if remark else "",
            })
        return rows

    def open_hour_event_editor(self, row, ctx=None):
        ctx = ctx or self._production_hour_context(row)
        if ctx is None:
            return

        action = ctx["action"]
        line = ctx["line"]
        model = ctx["model"]
        doc = ctx["document"]
        model_option = ctx["model_option"]
        rule = ctx.get("rule") or {
            "mct_sec": 0,
            "stations": 1,
            "tolerance_min": 5.0,
        }
        total_stations = int(rule.get("stations", 1) or 1)

        downtimes = list(getattr(doc, "downtimes", []) or [])
        categories = list(getattr(doc, "categories", []) or [])
        machines = list(getattr(doc, "machines", []) or [])
        if not downtimes or not categories:
            QMessageBox.warning(
                self,
                "Hourly Event",
                "ยังอ่าน DownTime / Category Master จาก QAC HTML ไม่ได้\n"
                "กรุณากด Select Line Data / Scan QAC ใหม่ แล้วลองอีกครั้ง",
            )
            return

        html_events = normalize_qac_events(
            self.production_existing_events,
            self.production_data.production_date,
            self.production_data.shift_start,
            action["interval_start"],
            action["interval_end"],
            total_stations,
        )
        existing_manual = self.hourly_event_store.list_events(
            str(self.production_data.production_date),
            line,
            model,
            action["interval_start"],
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"Hourly Event | {line} {model} | "
            f"{action['interval_start']}-{action['interval_end']}"
        )
        dlg.resize(1400, 760)
        root = QVBoxLayout(dlg)

        title = QLabel(
            f"Output {action['qty']} pcs | "
            f"MCT {rule.get('mct_sec', '-')} sec | "
            f"Stations {total_stations} | "
            "Manual Event ใช้ DownTime / Category / Machine จาก QAC HTML เท่านั้น"
        )
        root.addWidget(title)

        root.addWidget(QLabel("Existing Event from QAC / HTML"))
        existing_tbl = QTableWidget(0, 8)
        existing_tbl.setHorizontalHeaderLabels([
            "Source", "DownTime", "Category", "Machine",
            "Mode", "Start", "End", "Remark"
        ])
        for event in html_events:
            r = existing_tbl.rowCount()
            existing_tbl.insertRow(r)
            values = [
                event.get("source", "QAC_HTML"),
                event.get("topic_label", event.get("event_type", "")),
                event.get("category_label", ""),
                event.get("machine_label", ""),
                event.get("loss_mode", ""),
                event.get("start", ""),
                event.get("end", ""),
                event.get("remark", ""),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                existing_tbl.setItem(r, c, item)
        make_table_columns_resizable(existing_tbl, persistence_key="hourly_existing_qac_events")
        existing_tbl.setMaximumHeight(200)
        root.addWidget(existing_tbl)

        root.addWidget(QLabel(
            "Manual Event — เลือกตามลำดับ DownTime → Category → Machine → Start/End; "
            "เพิ่มได้หลาย Event และห้ามเวลา overlap"
        ))
        manual_tbl = QTableWidget(0, 7)
        manual_tbl.setHorizontalHeaderLabels([
            "DownTime (QAC)", "Category (QAC)", "Machine (QAC)",
            "Start", "End", "Stations Down", "Remark"
        ])
        root.addWidget(manual_tbl, 1)

        tools = QHBoxLayout()
        btn_add = QPushButton("+ Add Event")
        btn_remove = QPushButton("Remove Selected")
        tools.addWidget(btn_add)
        tools.addWidget(btn_remove)
        tools.addStretch()
        root.addLayout(tools)

        summary = QLabel("Validation: ready")
        summary.setWordWrap(True)
        root.addWidget(summary)

        def evaluate_pending(show_errors=False):
            events = self._collect_manual_event_table(manual_tbl, downtimes)
            errors = validate_manual_event_rows(
                events,
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
                existing_events=html_events,
            )
            for idx, event in enumerate(events, 1):
                if not event.get("downtime_value"):
                    errors.append(f"Row {idx}: กรุณาเลือก DownTime จาก QAC")
                if not event.get("category_value"):
                    errors.append(f"Row {idx}: กรุณาเลือก Category จาก QAC")
                if event.get("machine_required") and not event.get("machine_value"):
                    errors.append(f"Row {idx}: DownTime นี้ QAC บังคับเลือก Machine")
                if event.get("production_output_required"):
                    errors.append(
                        f"Row {idx}: Production Output ให้แก้จากตาราง Production Output โดยตรง "
                        "ไม่ใช้ Manual Event"
                    )
                if event.get("loss_mode") == "PARTIAL_CAPACITY":
                    down = int(event.get("unavailable_stations") or 0)
                    if down <= 0:
                        errors.append(f"Row {idx}: Unreached MCT ต้องกำหนด Stations Down อย่างน้อย 1")
                    if down >= total_stations:
                        errors.append(
                            f"Row {idx}: Partial Capacity ต้องเหลืออย่างน้อย 1 station"
                        )

            base_hour_s, base_hour_e = hour_datetimes(
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
            )
            base_result = evaluate_hour(
                qty=int(action.get("qty", 0)),
                mct_sec=float(rule.get("mct_sec", 0) or 0),
                total_stations=total_stations,
                tolerance_min=float(rule.get("tolerance_min", 5.0)),
                html_events=html_events,
                manual_events=[],
                hour_start_dt=base_hour_s,
                hour_end_dt=base_hour_e,
            )
            pending_norm = normalize_manual_events(
                events,
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
            )
            pending_result = evaluate_hour(
                qty=int(action.get("qty", 0)),
                mct_sec=float(rule.get("mct_sec", 0) or 0),
                total_stations=total_stations,
                tolerance_min=float(rule.get("tolerance_min", 5.0)),
                html_events=html_events,
                manual_events=pending_norm,
                hour_start_dt=base_hour_s,
                hour_end_dt=base_hour_e,
            )

            if errors:
                summary.setText(
                    f"Validation ERROR | ก่อนเพิ่มขาด {base_result.unexplained_min:.1f} min | "
                    f"หลังรายการปัจจุบันขาด {pending_result.unexplained_min:.1f} min | "
                    + " | ".join(errors)
                )
                if show_errors:
                    QMessageBox.warning(
                        dlg,
                        "Manual Event Validation",
                        "ไม่สามารถบันทึกได้\n\n" + "\n".join(errors),
                    )
                return None, errors, pending_result

            summary.setText(
                f"ก่อนเพิ่ม Event: Missing {base_result.unexplained_min:.1f} min  |  "
                f"หลัง Event ที่กำลังกรอก: Missing {pending_result.unexplained_min:.1f} min  |  "
                f"Result: {pending_result.status}"
            )
            return events, [], pending_result

        def add_row(seed=None):
            r = manual_tbl.rowCount()
            manual_tbl.insertRow(r)
            self._manual_event_widgets(
                manual_tbl, r, seed or {}, downtimes, categories, machines,
                total_stations, on_changed=lambda: evaluate_pending(False),
            )
            make_table_columns_resizable(manual_tbl, persistence_key="hourly_manual_events")

        def remove_row():
            r = manual_tbl.currentRow()
            if r >= 0:
                manual_tbl.removeRow(r)
            if manual_tbl.rowCount() == 0:
                add_row({})
            evaluate_pending(False)

        seed = existing_manual if existing_manual else [{}]
        for event in seed:
            add_row(event)

        btn_add.clicked.connect(lambda: add_row({}))
        btn_remove.clicked.connect(remove_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        root.addWidget(buttons)
        buttons.rejected.connect(dlg.reject)

        def save_events():
            events, errors, pending_result = evaluate_pending(True)
            if errors or events is None:
                return
            if not events:
                QMessageBox.warning(dlg, "Manual Event", "ไม่มี Event สำหรับบันทึก")
                return

            qac_actions = []
            down_by_value = {str(x.value): x for x in downtimes}
            machine_by_value = {str(x.value): x for x in machines}
            for event in events:
                down_opt = down_by_value.get(str(event.get("downtime_value") or ""))
                machine_opt = machine_by_value.get(str(event.get("machine_value") or ""))
                qac_actions.append({
                    "kind": "manual_hourly_event",
                    "downtime_value": str(event.get("downtime_value") or ""),
                    "downtime_label": str(event.get("event_type") or ""),
                    "category_value": str(event.get("category_value") or ""),
                    "category_label": str(event.get("category") or ""),
                    "model_value": (
                        str(getattr(model_option, "value", "") or "")
                        if down_opt and getattr(down_opt, "model_required", False)
                        else ""
                    ),
                    "model_name": model,
                    "machine_value": (
                        str(event.get("machine_value") or "")
                        if down_opt and getattr(down_opt, "machine_required", False)
                        else ""
                    ),
                    "machine_label": (
                        str(getattr(machine_opt, "name", "") or "")
                        if machine_opt else ""
                    ),
                    "start": event.get("start", ""),
                    "end": event.get("end", ""),
                    "description": event.get("remark", ""),
                })

            cfg = self.browser_cfg()
            save_button = buttons.button(QDialogButtonBox.Save)
            save_button.setEnabled(False)
            btn_add.setEnabled(False)
            btn_remove.setEnabled(False)
            summary.setText(
                f"กำลังบันทึก QAC ทีละ Event... | หลังรายการนี้คาดว่า Missing "
                f"{pending_result.unexplained_min:.1f} min"
            )

            self.manual_qac_event_worker = ManualQACEventWorker(
                cfg["cdp_url"], doc.page_index, qac_actions
            )
            self.manual_qac_event_worker.progress.connect(self.production_log_msg)

            def completed(_result_ids):
                # Local manual rows are only pending compatibility data.  Once QAC
                # accepted them, QAC HTML becomes the single source of truth.
                self.hourly_event_store.replace_events(
                    str(self.production_data.production_date),
                    line,
                    model,
                    action["interval_start"],
                    [],
                )
                self.audit.write(
                    "HOURLY_MANUAL_EVENT_QAC_SAVE",
                    status="OK",
                    production_date=str(self.production_data.production_date),
                    line=line,
                    model=model,
                    hour_start=action["interval_start"],
                    hour_end=action["interval_end"],
                    events=events,
                )
                summary.setText("QAC SAVE COMPLETE ✓ | กำลังอ่าน QAC กลับมาตรวจใหม่")
                dlg.accept()

            def failed(error):
                save_button.setEnabled(True)
                btn_add.setEnabled(True)
                btn_remove.setEnabled(True)
                summary.setText(f"QAC SAVE ERROR: {error}")
                QMessageBox.critical(dlg, "QAC Manual Event", str(error))

            self.manual_qac_event_worker.completed.connect(completed)
            self.manual_qac_event_worker.failed.connect(failed)
            self.manual_qac_event_worker.start()

        buttons.accepted.connect(save_events)
        evaluate_pending(False)

        if dlg.exec() == QDialog.Accepted:
            # Re-read QAC/HTML after successful write.  The recalculation is done
            # from QAC data, not optimistic local data.
            self.refresh_production_status()

    def _recalculate_production_validation(self):
        if not self.production_data:
            return
        try:
            actions = self._production_actions()
        except Exception:
            return

        ok = action_required = conflict = waiting = 0
        self.production_validation_results = {}

        for row, action in enumerate(actions):
            if action.get("kind") != "production_update":
                continue
            ctx = self._production_hour_context(row)
            if ctx is None:
                continue
            rule = ctx.get("rule")
            if not rule:
                self.tbl_prod.item(row, 8).setText("NOT SET")
                self.tbl_prod.item(row, 9).setText("-")
                self.tbl_prod.item(row, 10).setText("-")
                self.tbl_prod.item(row, 11).setText("-")
                self.tbl_prod.item(row, 12).setText("WAITING MCT")
                waiting += 1
                continue

            total_stations = int(rule.get("stations", 1) or 1)
            html_events = normalize_qac_events(
                self.production_existing_events,
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
                total_stations,
            )
            manual_raw = self.hourly_event_store.list_events(
                str(self.production_data.production_date),
                ctx["line"],
                ctx["model"],
                action["interval_start"],
            )
            manual_events = normalize_manual_events(
                manual_raw,
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
            )
            hour_s, hour_e = hour_datetimes(
                self.production_data.production_date,
                self.production_data.shift_start,
                action["interval_start"],
                action["interval_end"],
            )
            result = evaluate_hour(
                qty=int(action.get("qty", 0)),
                mct_sec=float(rule["mct_sec"]),
                total_stations=total_stations,
                tolerance_min=float(rule.get("tolerance_min", 5.0)),
                html_events=html_events,
                manual_events=manual_events,
                hour_start_dt=hour_s,
                hour_end_dt=hour_e,
            )
            self.production_validation_results[row] = result

            self.tbl_prod.item(row, 8).setText(f"{result.mct_sec:.2f}")
            self.tbl_prod.item(row, 9).setText(f"{result.expected_qty:.1f}")
            self.tbl_prod.item(row, 10).setText(f"{result.recorded_event_min:.1f}")
            self.tbl_prod.item(row, 11).setText(f"{result.unexplained_min:.1f}")
            self.tbl_prod.item(row, 12).setText(result.status)
            self.tbl_prod.item(row, 12).setToolTip(
                "\n".join(result.conflicts)
                if result.conflicts
                else (
                    f"Effective MCT: {result.effective_mct_sec:.2f} sec\n"
                    f"Partial Capacity: {result.partial_capacity_min:.1f} min\n"
                    f"Average Capacity: {result.average_capacity*100:.1f}%"
                )
            )

            if result.status == "TIME OK":
                ok += 1
            elif result.status == "ACTION REQUIRED":
                action_required += 1
            elif result.status == "DATA CONFLICT":
                conflict += 1
            else:
                waiting += 1

        total = ok + action_required + conflict + waiting
        self.lbl_prod_time_summary.setText(
            f"Time Validation | Hours {total} | TIME OK {ok} | "
            f"ACTION REQUIRED {action_required} | DATA CONFLICT {conflict} | "
            f"WAITING {waiting} | Double-click hourly row to add Event"
        )

    def refresh_production_status(self):
        if not self.production_data:
            return

        di = self.cmb_prod_doc.currentIndex()

        if di < 0 or di >= len(self.documents):
            return

        if (
            self.production_existing_worker
            and self.production_existing_worker.isRunning()
        ):
            return

        cfg = self.browser_cfg()
        doc = self.documents[di]

        self.production_existing_worker = ExistingAlarmWorker(
            cfg["cdp_url"],
            doc.page_index
        )
        self.production_existing_worker.progress.connect(
            self.production_log_msg
        )
        self.production_existing_worker.completed.connect(
            self._production_existing_loaded
        )
        self.production_existing_worker.failed.connect(
            lambda error: self.production_log_msg(
                f"QAC STATUS ERROR: {error}"
            )
        )
        self.production_existing_worker.start()

    def _production_existing_loaded(self, events):
        self.production_existing_events = list(
            events or []
        )

        try:
            actions = self._production_actions()
        except Exception as e:
            self.production_log_msg(
                f"STATUS ERROR: {e}"
            )
            return

        for row, action in enumerate(actions):
            kind = action["kind"]

            if kind == "production_update":
                found = None

                for event in self.production_existing_events:
                    if (
                        self._production_option_match(
                            event.get("topic_value"),
                            event.get("topic_label"),
                            action.get("downtime_value"),
                            action.get("downtime_label")
                        )
                        and
                        self._production_option_match(
                            event.get("category_value"),
                            event.get("category_label"),
                            action.get("category_value"),
                            action.get("category_label")
                        )
                        and
                        str(event.get("model_value") or "")
                        == str(action.get("model_value") or "")
                        and
                        self._norm_alarm_clock(
                            event.get("start")
                        )
                        == self._norm_alarm_clock(
                            action["qac_event_time"]
                        )
                    ):
                        found = event
                        break

                if not found:
                    self.tbl_prod.item(row, 1).setText(
                        "MISSING"
                    )
                    self.tbl_prod.item(row, 6).setText("-")
                    continue

                raw = str(
                    found.get("actual_qty", "")
                    or ""
                ).strip()

                try:
                    existing_qty = int(float(raw))
                    self.tbl_prod.item(row, 6).setText(
                        str(existing_qty)
                    )
                except Exception:
                    existing_qty = None
                    self.tbl_prod.item(row, 6).setText(
                        "UNKNOWN"
                    )

                if existing_qty == int(action["qty"]):
                    self.tbl_prod.item(row, 1).setText(
                        "COMPLETE ✓"
                    )
                    self.tbl_prod.item(row, 7).setText(
                        "SKIP"
                    )
                else:
                    self.tbl_prod.item(row, 1).setText(
                        "UPDATE"
                    )
                continue

            found = False

            for event in self.production_existing_events:
                if (
                    self._production_option_match(
                        event.get("topic_value"),
                        event.get("topic_label"),
                        action.get("downtime_value"),
                        action.get("downtime_label")
                    )
                    and
                    self._production_option_match(
                        event.get("category_value"),
                        event.get("category_label"),
                        action.get("category_value"),
                        action.get("category_label")
                    )
                    and
                    self._norm_alarm_clock(
                        event.get("start")
                    )
                    == self._norm_alarm_clock(
                        action["start"]
                    )
                    and
                    self._norm_alarm_clock(
                        event.get("end")
                    )
                    == self._norm_alarm_clock(
                        action["end"]
                    )
                ):
                    found = True
                    break

            self.tbl_prod.item(row, 1).setText(
                "EXISTS ✓" if found else "NEW"
            )

            if found:
                self.tbl_prod.item(row, 7).setText(
                    "SKIP"
                )

        self._recalculate_production_validation()

    def run_production_output(self):
        if not self._permission_or_warn(4):
            return

        try:
            all_actions = self._production_actions()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Production Output",
                str(e)
            )
            return

        actions = self._selected_production_actions(
            all_actions
        )

        if not actions:
            QMessageBox.warning(
                self,
                "Production Output",
                "กรุณาเลือกอย่างน้อย 1 Row"
            )
            return

        missing = []

        for row, action in enumerate(
            all_actions
        ):
            chk = self._production_checkbox(
                row
            )

            if (
                chk is None
                or not chk.isChecked()
            ):
                continue

            if (
                action.get("kind")
                == "production_update"
                and self.tbl_prod.item(
                    row,
                    1
                ).text()
                == "MISSING"
            ):
                missing.append(
                    self.tbl_prod.item(
                        row,
                        4
                    ).text()
                )

        if missing:
            self.production_log_msg(
                "Selected Row มี Production Output "
                "ที่ UI ยังอ่านรายละเอียดไม่ได้: "
                + ", ".join(missing)
                + " | Engine จะ Scan/Pre-flight ซ้ำ "
                "เฉพาะ Row ที่เลือกก่อน Update จริง"
            )

        # Production Output Import has no Dry Run.
        # Every execution is a confirmed live QAC update.
        dry = False

        selected_file_qty = sum(
            int(
                action.get(
                    "qty",
                    0
                )
            )
            for action in actions
            if action.get("kind")
            == "production_update"
        )

        answer = QMessageBox.question(
            self,
            "Confirm Production Output",
            (
                f"Selected Rows = {len(actions)}\n"
                f"Selected Production Qty = "
                f"{selected_file_qty}\n"
                f"File COUNTA Total = "
                f"{self.production_data.counted_total}\n"
                f"First = "
                f"{self.production_data.first_datetime.strftime('%H:%M:%S')}\n"
                f"Last = "
                f"{self.production_data.last_datetime.strftime('%H:%M:%S')}\n"
                "ต้องการ Update QAC เฉพาะ Row "
                "ที่ Check อยู่หรือไม่?"
            )
        )

        if answer != QMessageBox.Yes:
            return

        di = self.cmb_prod_doc.currentIndex()
        doc = self.documents[di]
        cfg = self.browser_cfg()

        self.prod_progress.setValue(0)
        self.lbl_prod_progress.setText(
            "Starting..."
        )
        self.btn_prod_run.setEnabled(False)

        self.audit.write(
            "PRODUCTION_OUTPUT_START",
            status="OK",
            dry_run=False,
            file=self.production_file,
            file_total=self.production_data.counted_total,
            selected_rows=len(actions),
            selected_production_qty=selected_file_qty,
            selected_actions=[
                {
                    "kind": action.get("kind"),
                    "qac_event_time": action.get(
                        "qac_event_time"
                    ),
                    "qty": action.get("qty"),
                    "start": action.get("start"),
                    "end": action.get("end"),
                }
                for action in actions
            ]
        )

        # Only checked rows reach the worker/engine. Therefore unchecked
        # Setup, hourly Production Output, or Stop Line rows are untouched.
        self.production_worker = ProductionOutputWorker(
            cfg["cdp_url"],
            doc.page_index,
            actions,
            False
        )
        self.production_worker.progress.connect(
            self.production_log_msg
        )
        self.production_worker.completed.connect(
            lambda: self.production_completed(
                False
            )
        )
        self.production_worker.failed.connect(
            self.production_failed
        )
        self.production_worker.start()

    def production_completed(self, dry):
        self.btn_prod_run.setEnabled(True)
        self.prod_progress.setValue(100)
        self.lbl_prod_progress.setText("COMPLETE")

        self.audit.write(
            "PRODUCTION_OUTPUT_COMPLETE",
            status="OK",
            dry_run=dry
        )

        QMessageBox.information(
            self,
            "Production Output",
            (
                "Dry Run เสร็จแล้ว"
                if dry
                else "Update QAC เสร็จแล้ว"
            )
        )

        self.refresh_production_status()

    def production_failed(self, error):
        self.btn_prod_run.setEnabled(True)
        self.lbl_prod_progress.setText("ERROR")

        self.audit.write(
            "PRODUCTION_OUTPUT_FAILED",
            status="ERROR",
            error=error
        )

        self.production_log_msg(
            f"ERROR: {error}"
        )

        QMessageBox.critical(
            self,
            "Production Output Error",
            error
        )

    def pause_production_output(self):
        if (
            self.production_worker
            and self.production_worker.isRunning()
        ):
            self.production_worker.request_pause()

    def resume_production_output(self):
        if (
            self.production_worker
            and self.production_worker.isRunning()
        ):
            self.production_worker.request_resume()

    def stop_production_output(self):
        if (
            self.production_worker
            and self.production_worker.isRunning()
        ):
            self.production_worker.request_stop()

    # ---------------- Settings / Access ----------------
    def _set_tab_visible_compat(
        self,
        index: int,
        visible: bool
    ):
        """
        Qt6 supports setTabVisible. Fallback keeps tab disabled if
        a deployment has an older Qt build.
        """
        try:
            self.tabs.setTabVisible(
                index,
                bool(visible)
            )
        except Exception:
            if not visible:
                self.tabs.setTabEnabled(
                    index,
                    False
                )

    def _apply_tab_access(self):
        # Tab 1: Auto Register
        self._set_tab_visible_compat(
            0,
            self.access_record.tab1_show
        )
        self.tabs.setTabEnabled(
            0,
            bool(
                self.access_record.tab1_show
                and self.access_record.tab1_enable
            )
        )

        # Tab 2: Alarm Import
        self._set_tab_visible_compat(
            1,
            self.access_record.tab2_show
        )
        self.tabs.setTabEnabled(
            1,
            bool(
                self.access_record.tab2_show
                and self.access_record.tab2_enable
            )
        )

        # Tab 3: OCR NG Import
        self._set_tab_visible_compat(
            2,
            self.access_record.tab3_show
        )
        self.tabs.setTabEnabled(
            2,
            bool(
                self.access_record.tab3_show
                and self.access_record.tab3_enable
            )
        )

        # Tab 4: Production Output Import
        self._set_tab_visible_compat(
            3,
            self.access_record.tab4_show
        )
        self.tabs.setTabEnabled(
            3,
            bool(
                self.access_record.tab4_show
                and self.access_record.tab4_enable
            )
        )

        # Tab 5: Daily Document
        self._set_tab_visible_compat(
            4,
            self.access_record.tab5_show
        )
        self.tabs.setTabEnabled(
            4,
            bool(
                self.access_record.tab5_show
                and self.access_record.tab5_enable
            )
        )

        # Tab 6: Sample Register
        sample_index = self.tabs.indexOf(self.tab_sample_register)
        if sample_index >= 0:
            self._set_tab_visible_compat(
                sample_index,
                self.access_record.tab6_show
            )
            self.tabs.setTabEnabled(
                sample_index,
                bool(
                    self.access_record.tab6_show
                    and self.access_record.tab6_enable
                )
            )

        # Settings is only created when settings_show=1. Never use a fixed
        # index because feature tabs may be added before Settings.
        if self.tab_settings is not None:
            settings_index = self.tabs.indexOf(self.tab_settings)
            if settings_index >= 0:
                self.tabs.setTabEnabled(settings_index, True)

    def _permission_or_warn(
        self,
        tab_no: int
    ) -> bool:
        if tab_no == 1:
            allowed = (
                self.access_record.tab1_show
                and self.access_record.tab1_enable
            )
            name = "Auto Register"
        elif tab_no == 2:
            allowed = (
                self.access_record.tab2_show
                and self.access_record.tab2_enable
            )
            name = "Alarm Import"
        elif tab_no == 3:
            allowed = (
                self.access_record.tab3_show
                and self.access_record.tab3_enable
            )
            name = "OCR NG Import"
        elif tab_no == 4:
            allowed = (
                self.access_record.tab4_show
                and self.access_record.tab4_enable
            )
            name = "Production Output Import"
        elif tab_no == 5:
            allowed = (
                self.access_record.tab5_show
                and self.access_record.tab5_enable
            )
            name = "Daily Document"
        elif tab_no == 6:
            allowed = (
                self.access_record.tab6_show
                and self.access_record.tab6_enable
            )
            name = "Sample Register"
        else:
            return False

        if allowed:
            return True

        self.audit.write(
            "PERMISSION_BLOCKED",
            status="DENY",
            tab=tab_no,
            tab_name=name
        )

        QMessageBox.warning(
            self,
            "Permission",
            "ไม่มีสิทธิ์ใช้งานส่วนนี้ "
            "กรุณาติดต่อผู้พัฒนา"
        )
        return False

    def _edit_access_csv(self):
        if not self._admin_unlocked:
            QMessageBox.warning(self, "Admin Mode", "กรุณาปลดล็อก Admin Mode")
            return
        path = Path(self.txt_access_config_path.text().strip())
        if not path.is_absolute():
            path = Path(self.app_root_path) / path
        try:
            fields, rows = read_access_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Access CSV", str(exc));return
        dialog = QDialog(self)
        dialog.setWindowTitle("Admin — Access Control CSV")
        dialog.resize(1100, 600)
        lay = QVBoxLayout(dialog)
        lay.addWidget(QLabel("แก้ไขค่าแล้วกด Save เพื่อเขียนกลับไฟล์เดิม (ต้องมีสิทธิ์เขียนไฟล์)"))
        table = QTableWidget(len(rows), len(fields), dialog)
        table.setHorizontalHeaderLabels(fields)
        for r, record in enumerate(rows):
            for c, field in enumerate(fields):
                item = QTableWidgetItem(str(record.get(field, "")))
                if field == "ip":
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(r, c, item)
        lay.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=dialog)
        lay.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        def commit():
            updated = []
            for ri in range(table.rowCount()):
                updated.append({field: (table.item(ri, ci).text().strip() if table.item(ri,ci) else "") for ci,field in enumerate(fields)})
            try:
                save_access_csv(path, fields, updated)
            except Exception as exc:
                QMessageBox.critical(dialog, "Save Access CSV", str(exc));return
            self.audit.write("ADMIN_ACCESS_CSV_SAVE", message=f"rows={len(updated)}")
            QMessageBox.information(dialog, "Access CSV", "บันทึกแล้ว — การเปลี่ยนสิทธิ์มีผลหลัง Reload/Restart")
            dialog.accept()
        buttons.accepted.connect(commit)
        dialog.exec()

    def _authorize_settings_tab(self, index: int) -> bool:
        """Prompt only for Settings (index 7); operators can use other workflows."""
        if index != 7 or self._admin_unlocked:
            return True
        entered, ok = QInputDialog.getText(
            self, "Admin Mode", "Security Key", QLineEdit.EchoMode.Password
        )
        if not ok:
            return False
        if entered != "12338":
            QMessageBox.warning(self, "Admin Mode", "Security Key ไม่ถูกต้อง")
            return False
        self._admin_unlocked = True
        self.audit.write("ADMIN_MODE_UNLOCK", message="Settings unlocked")
        return True

    def _build_settings_tab(self):
        w = QWidget()
        outer = QVBoxLayout(w)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        body = QWidget()
        root = QVBoxLayout(body)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        access_box = QLabel(
            f"Access Name : {self.access_record.name}\n"
            f"IP          : {self.access_record.ip}\n"
            f"Auto Register : "
            f"show={int(self.access_record.tab1_show)} / "
            f"enable={int(self.access_record.tab1_enable)}\n"
            f"Alarm Import  : "
            f"show={int(self.access_record.tab2_show)} / "
            f"enable={int(self.access_record.tab2_enable)}\n"
            f"OCR NG Import : "
            f"show={int(self.access_record.tab3_show)} / "
            f"enable={int(self.access_record.tab3_enable)}\n"
            f"Production Output : "
            f"show={int(self.access_record.tab4_show)} / "
            f"enable={int(self.access_record.tab4_enable)}\n"
            f"Daily Document : "
            f"show={int(self.access_record.tab5_show)} / "
            f"enable={int(self.access_record.tab5_enable)}\n"
            f"Sample Register : "
            f"show={int(self.access_record.tab6_show)} / "
            f"enable={int(self.access_record.tab6_enable)}\n"
            f"Access Source : "
            f"{self.access_record.source_mode}\n"
            f"Cached At : "
            f"{self.access_record.cached_at or '-'}"
        )
        access_box.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        root.addWidget(access_box)

        # Central access + QAC URL
        central_group = QGroupBox(
            "System / Central Config"
        )
        central_form = QFormLayout(
            central_group
        )

        path_widget = QWidget()
        path_row = QHBoxLayout(path_widget)
        path_row.setContentsMargins(0, 0, 0, 0)

        self.txt_access_config_path = QLineEdit(
            self.settings.get(
                "access_control",
                {}
            ).get(
                "config_path",
                ""
            )
        )
        self.btn_browse_access_config = QPushButton(
            "Browse..."
        )
        self.btn_test_access_config = QPushButton(
            "Test Connection"
        )

        self.btn_browse_access_config.clicked.connect(
            self.browse_access_config
        )
        self.btn_test_access_config.clicked.connect(
            self.test_access_config
        )

        path_row.addWidget(
            self.txt_access_config_path,
            1
        )
        path_row.addWidget(
            self.btn_browse_access_config
        )
        path_row.addWidget(
            self.btn_test_access_config
        )

        self.txt_qac_home_url = QLineEdit(
            self.settings.get(
                "qac_home_url",
                "http://159.228.251.234:8077/"
            )
        )

        central_form.addRow(
            "Central Access Config",
            path_widget
        )
        central_form.addRow(
            "QAC Home URL",
            self.txt_qac_home_url
        )
        root.addWidget(
            central_group
        )
        self.btn_edit_access_csv = QPushButton("Admin: Edit Access CSV")
        self.btn_edit_access_csv.clicked.connect(self._edit_access_csv)
        root.addWidget(self.btn_edit_access_csv)


        settings_pages = QTabWidget()
        daily_settings_page = QWidget()
        daily_settings_layout = QVBoxLayout(daily_settings_page)
        other_settings_page = QWidget()
        other_settings_layout = QVBoxLayout(other_settings_page)
        settings_pages.addTab(daily_settings_page, "Daily Document")
        settings_pages.addTab(other_settings_page, "Other Settings")
        root.addWidget(settings_pages)

        # Daily Document master source.
        daily_cfg = self.settings.get("daily_document", {})
        daily_group = QGroupBox("Daily Document / Document List Source")
        daily_form = QFormLayout(daily_group)

        daily_path_widget = QWidget()
        daily_path_row = QHBoxLayout(daily_path_widget)
        daily_path_row.setContentsMargins(0, 0, 0, 0)
        self.txt_daily_list_source = QLineEdit(
            str(daily_cfg.get("list_source", "config/List document.xlsx") or "")
        )
        self.btn_browse_daily_list = QPushButton("Browse...")
        self.btn_test_daily_list = QPushButton("Test / Load")
        self.btn_browse_daily_list.clicked.connect(self.browse_daily_list_source)
        self.btn_test_daily_list.clicked.connect(self.test_daily_list_source)
        daily_path_row.addWidget(self.txt_daily_list_source, 1)
        daily_path_row.addWidget(self.btn_browse_daily_list)
        daily_path_row.addWidget(self.btn_test_daily_list)

        self.txt_daily_sheet_name = QLineEdit(
            str(daily_cfg.get("sheet_name", "Raw") or "Raw")
        )
        self.chk_daily_active_only = QCheckBox("Load Active documents only")
        self.chk_daily_active_only.setChecked(
            bool(daily_cfg.get("active_only", True))
        )
        self.lbl_daily_source_test = QLabel("Status: not tested")
        self.lbl_daily_source_test.setTextInteractionFlags(Qt.TextSelectableByMouse)

        daily_form.addRow("List Document Source", daily_path_widget)
        daily_form.addRow("Worksheet", self.txt_daily_sheet_name)
        daily_form.addRow("", self.chk_daily_active_only)
        daily_form.addRow("Source Status", self.lbl_daily_source_test)
        daily_settings_layout.addWidget(daily_group)

        # Daily Check Sheet time rules are prompted at runtime, not configured here.
        daily_settings_layout.addStretch()

        # Auto Register record settings.
        auto_cfg = self.settings.get(
            "auto_register_records",
            {}
        )
        prod_cfg = auto_cfg.get(
            "production",
            {}
        )
        break_cfg = auto_cfg.get(
            "break",
            {}
        )

        auto_group = QGroupBox(
            "Auto Register Records (Config-driven)"
        )
        auto_form = QFormLayout(
            auto_group
        )

        self.txt_set_prod_down_value = QLineEdit(
            str(prod_cfg.get("downtime_value", ""))
        )
        self.txt_set_prod_down_label = QLineEdit(
            str(prod_cfg.get(
                "downtime_label",
                "Production Output"
            ))
        )
        self.txt_set_prod_cat_value = QLineEdit(
            str(prod_cfg.get("category_value", ""))
        )
        self.txt_set_prod_cat_label = QLineEdit(
            str(prod_cfg.get(
                "category_label",
                "Normal Production"
            ))
        )

        self.txt_set_break_down_value = QLineEdit(
            str(break_cfg.get("downtime_value", ""))
        )
        self.txt_set_break_down_label = QLineEdit(
            str(break_cfg.get(
                "downtime_label",
                "Schedule Downtime"
            ))
        )
        self.txt_set_break_cat_value = QLineEdit(
            str(break_cfg.get("category_value", ""))
        )
        self.txt_set_break_cat_label = QLineEdit(
            str(break_cfg.get(
                "category_label",
                "Break time"
            ))
        )
        self.txt_set_break_desc = QLineEdit(
            str(break_cfg.get(
                "description",
                "Break time"
            ))
        )

        auto_form.addRow(
            "Production Downtime ID",
            self.txt_set_prod_down_value
        )
        auto_form.addRow(
            "Production Downtime Name",
            self.txt_set_prod_down_label
        )
        auto_form.addRow(
            "Production Category ID",
            self.txt_set_prod_cat_value
        )
        auto_form.addRow(
            "Production Category Name",
            self.txt_set_prod_cat_label
        )
        auto_form.addRow(
            "Break Downtime ID",
            self.txt_set_break_down_value
        )
        auto_form.addRow(
            "Break Downtime Name",
            self.txt_set_break_down_label
        )
        auto_form.addRow(
            "Break Category ID",
            self.txt_set_break_cat_value
        )
        auto_form.addRow(
            "Break Category Name",
            self.txt_set_break_cat_label
        )
        auto_form.addRow(
            "Break Description",
            self.txt_set_break_desc
        )

        other_settings_layout.addWidget(
            auto_group
        )

        # Production Output Import settings.
        output_cfg = self.settings.get(
            "production_output_import",
            {}
        )
        setup_cfg = output_cfg.get(
            "setup",
            {}
        )
        stop_cfg = output_cfg.get(
            "stop_line",
            {}
        )

        output_group = QGroupBox(
            "Production Output Import Records"
        )
        output_form = QFormLayout(
            output_group
        )

        self.txt_set_day_start = QLineEdit(
            str(output_cfg.get(
                "day_shift_start",
                "08:00"
            ))
        )
        self.txt_set_day_end = QLineEdit(
            str(output_cfg.get(
                "day_shift_end",
                "20:00"
            ))
        )
        self.txt_set_night_start = QLineEdit(
            str(output_cfg.get(
                "night_shift_start",
                "20:00"
            ))
        )
        self.txt_set_night_end = QLineEdit(
            str(output_cfg.get(
                "night_shift_end",
                "08:00"
            ))
        )

        self.txt_set_setup_down_value = QLineEdit(
            str(setup_cfg.get("downtime_value", ""))
        )
        self.txt_set_setup_down_label = QLineEdit(
            str(setup_cfg.get("downtime_label", "Setup"))
        )
        self.txt_set_setup_cat_value = QLineEdit(
            str(setup_cfg.get("category_value", ""))
        )
        self.txt_set_setup_cat_label = QLineEdit(
            str(setup_cfg.get("category_label", "Run-up"))
        )
        self.txt_set_setup_machine_value = QLineEdit(
            str(setup_cfg.get("machine_value", ""))
        )
        self.txt_set_setup_machine_label = QLineEdit(
            str(setup_cfg.get(
                "machine_search_text",
                "Housing assembly"
            ))
        )
        self.txt_set_setup_desc = QLineEdit(
            str(setup_cfg.get("description", "Run Up"))
        )

        self.txt_set_stop_down_value = QLineEdit(
            str(stop_cfg.get("downtime_value", ""))
        )
        self.txt_set_stop_down_label = QLineEdit(
            str(stop_cfg.get(
                "downtime_label",
                "Schedule Downtime"
            ))
        )
        self.txt_set_stop_cat_value = QLineEdit(
            str(stop_cfg.get("category_value", ""))
        )
        self.txt_set_stop_cat_label = QLineEdit(
            str(stop_cfg.get("category_label", "Stop line"))
        )
        self.txt_set_stop_desc = QLineEdit(
            str(stop_cfg.get("description", "Stop Line"))
        )

        output_form.addRow(
            "Day Shift Start",
            self.txt_set_day_start
        )
        output_form.addRow(
            "Day Shift End",
            self.txt_set_day_end
        )
        output_form.addRow(
            "Night Shift Start",
            self.txt_set_night_start
        )
        output_form.addRow(
            "Night Shift End",
            self.txt_set_night_end
        )
        output_form.addRow(
            "Setup Downtime ID",
            self.txt_set_setup_down_value
        )
        output_form.addRow(
            "Setup Downtime Name",
            self.txt_set_setup_down_label
        )
        output_form.addRow(
            "Run-up Category ID",
            self.txt_set_setup_cat_value
        )
        output_form.addRow(
            "Run-up Category Name",
            self.txt_set_setup_cat_label
        )
        output_form.addRow(
            "Setup Machine ID",
            self.txt_set_setup_machine_value
        )
        output_form.addRow(
            "Setup Machine Search",
            self.txt_set_setup_machine_label
        )
        output_form.addRow(
            "Setup Description",
            self.txt_set_setup_desc
        )
        output_form.addRow(
            "Stop Downtime ID",
            self.txt_set_stop_down_value
        )
        output_form.addRow(
            "Stop Downtime Name",
            self.txt_set_stop_down_label
        )
        output_form.addRow(
            "Stop Category ID",
            self.txt_set_stop_cat_value
        )
        output_form.addRow(
            "Stop Category Name",
            self.txt_set_stop_cat_label
        )
        output_form.addRow(
            "Stop Description",
            self.txt_set_stop_desc
        )

        other_settings_layout.addWidget(
            output_group
        )

        hourly_cfg = self.settings.get("hourly_validation", {})
        hourly_group = QGroupBox(
            "Central MCT Master (same folder as Access Control)"
        )
        hourly_layout = QVBoxLayout(hourly_group)

        self.lbl_central_mct_path = QLabel()
        self.lbl_central_mct_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._update_central_mct_path_label()
        hourly_layout.addWidget(self.lbl_central_mct_path)

        self.tbl_set_mct_rules = QTableWidget(0, 5)
        self.tbl_set_mct_rules.setHorizontalHeaderLabels([
            "Line", "Model", "MCT sec", "Stations", "Tolerance min"
        ])
        for rule in hourly_cfg.get("mct_rules", []) or []:
            r = self.tbl_set_mct_rules.rowCount()
            self.tbl_set_mct_rules.insertRow(r)
            values = [
                rule.get("line", "*"),
                rule.get("model", "*"),
                rule.get("mct_sec", ""),
                rule.get("stations", 1),
                rule.get("tolerance_min", 5.0),
            ]
            for c, value in enumerate(values):
                self.tbl_set_mct_rules.setItem(r, c, QTableWidgetItem(str(value)))
        make_table_columns_resizable(self.tbl_set_mct_rules, persistence_key="settings_mct_master")
        self.tbl_set_mct_rules.setMaximumHeight(240)
        hourly_layout.addWidget(self.tbl_set_mct_rules)

        hourly_buttons = QHBoxLayout()
        self.btn_add_mct_rule = QPushButton("+ Add MCT Rule")
        self.btn_remove_mct_rule = QPushButton("Remove Selected Rule")
        self.btn_reload_mct_master = QPushButton("Reload Central MCT")
        self.btn_add_mct_rule.clicked.connect(self.add_mct_rule_row)
        self.btn_remove_mct_rule.clicked.connect(self.remove_mct_rule_row)
        self.btn_reload_mct_master.clicked.connect(self.reload_central_mct_master)
        hourly_buttons.addWidget(self.btn_add_mct_rule)
        hourly_buttons.addWidget(self.btn_remove_mct_rule)
        hourly_buttons.addWidget(self.btn_reload_mct_master)
        hourly_buttons.addStretch()
        hourly_layout.addLayout(hourly_buttons)
        other_settings_layout.addWidget(hourly_group)

        self.txt_access_config_path.textChanged.connect(
            self._update_central_mct_path_label
        )

        self.lbl_settings_test = QLabel(
            "Status: not tested"
        )
        self.lbl_settings_test.setTextInteractionFlags(
            Qt.TextSelectableByMouse
        )
        other_settings_layout.addWidget(
            self.lbl_settings_test
        )

        buttons = QHBoxLayout()
        buttons.addStretch()

        self.btn_save_settings = QPushButton(
            "Save Settings"
        )
        self.btn_save_settings.clicked.connect(
            self.save_local_settings
        )
        buttons.addWidget(
            self.btn_save_settings
        )

        other_settings_layout.addLayout(buttons)
        other_settings_layout.addStretch()
        root.addStretch()

        return w

    def browse_daily_list_source(self):
        current = self.txt_daily_list_source.text().strip()
        try:
            current_path = str(resolve_document_source(current, self.app_root_path))
        except Exception:
            current_path = current
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Daily Document List",
            current_path,
            "Document List (*.xlsx *.xlsm *.csv);;All Files (*.*)"
        )
        if path:
            self.txt_daily_list_source.setText(path)

    def test_daily_list_source(self):
        try:
            rows, resolved = load_document_master(
                source_path=self.txt_daily_list_source.text().strip(),
                app_root=self.app_root_path,
                sheet_name=self.txt_daily_sheet_name.text().strip() or "Raw",
                active_only=self.chk_daily_active_only.isChecked(),
            )
            lines = len({r.get("line", "") for r in rows if r.get("line")})
            self.lbl_daily_source_test.setText(
                f"Status: OK | {len(rows)} documents | {lines} lines\\n{resolved}"
            )
        except Exception as e:
            self.lbl_daily_source_test.setText(f"Status: ERROR\\n{e}")

    def browse_access_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Central Access Config",
            self.txt_access_config_path.text(),
            "CSV Files (*.csv);;All Files (*.*)"
        )

        if path:
            self.txt_access_config_path.setText(
                path
            )

    def test_access_config(self):
        path = self.txt_access_config_path.text().strip()

        try:
            record, ips, resolved = (
                load_access_record(
                    path,
                    self.app_root_path
                )
            )

            if record is None:
                self.lbl_settings_test.setText(
                    "Status: Config อ่านได้ "
                    "แต่ IP เครื่องนี้ไม่มีในรายการ\\n"
                    f"Local IP: {', '.join(ips)}\\n"
                    f"Config: {resolved}"
                )
                self.audit.write(
                    "SETTINGS_CONFIG_TEST",
                    status="DENY",
                    config_path=resolved,
                    local_ips=ips
                )
                return

            self.lbl_settings_test.setText(
                "Status: OK\\n"
                f"Name: {record.name}\\n"
                f"IP: {record.ip}\\n"
                f"Status: {record.status}\\n"
                f"Tab1 show/enable: "
                f"{int(record.tab1_show)}/"
                f"{int(record.tab1_enable)}\\n"
                f"Tab2 show/enable: "
                f"{int(record.tab2_show)}/"
                f"{int(record.tab2_enable)}\\n"
                f"Settings show: "
                f"{int(record.settings_show)}\\n"
                f"Config: {resolved}"
            )
            self.audit.write(
                "SETTINGS_CONFIG_TEST",
                status="OK",
                config_path=resolved,
                matched_name=record.name,
                matched_ip=record.ip
            )

        except Exception as e:
            self.lbl_settings_test.setText(
                f"Status: ERROR\\n{e}"
            )
            self.audit.write(
                "SETTINGS_CONFIG_TEST",
                status="ERROR",
                error=str(e),
                config_path=path
            )

    def _update_central_mct_path_label(self, *_args):
        if not hasattr(self, "lbl_central_mct_path"):
            return
        try:
            access_path = self.txt_access_config_path.text().strip()
            path = resolve_central_mct_path(access_path, self.app_root_path)
            self.lbl_central_mct_path.setText(
                f"Central MCT: {path}"
            )
        except Exception as e:
            self.lbl_central_mct_path.setText(f"Central MCT: ERROR - {e}")

    def reload_central_mct_master(self):
        try:
            access_path = self.txt_access_config_path.text().strip()
            rules, path = load_central_mct(access_path, self.app_root_path)
            self.settings["hourly_validation"] = {"mct_rules": rules}
            self.central_mct_path = str(path)
            self.tbl_set_mct_rules.setRowCount(0)
            for rule in rules:
                r = self.tbl_set_mct_rules.rowCount()
                self.tbl_set_mct_rules.insertRow(r)
                vals = [
                    rule.get("line", "*"), rule.get("model", "*"),
                    rule.get("mct_sec", ""), rule.get("stations", 1),
                    rule.get("tolerance_min", 5.0),
                ]
                for c, value in enumerate(vals):
                    self.tbl_set_mct_rules.setItem(r, c, QTableWidgetItem(str(value)))
            self._update_central_mct_path_label()
            if self.production_data:
                self._recalculate_production_validation()
            QMessageBox.information(
                self, "Central MCT Master",
                f"โหลด MCT กลางแล้ว {len(rules)} rules\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Central MCT Master", str(e))

    def add_mct_rule_row(self):
        if not hasattr(self, "tbl_set_mct_rules"):
            return
        row = self.tbl_set_mct_rules.rowCount()
        self.tbl_set_mct_rules.insertRow(row)
        defaults = ["*", "*", "", "1", "5"]
        for col, value in enumerate(defaults):
            self.tbl_set_mct_rules.setItem(row, col, QTableWidgetItem(str(value)))

    def remove_mct_rule_row(self):
        if not hasattr(self, "tbl_set_mct_rules"):
            return
        row = self.tbl_set_mct_rules.currentRow()
        if row >= 0:
            self.tbl_set_mct_rules.removeRow(row)

    def _collect_mct_rules(self):
        rules = []
        if not hasattr(self, "tbl_set_mct_rules"):
            return rules
        for row in range(self.tbl_set_mct_rules.rowCount()):
            values = []
            for col in range(5):
                item = self.tbl_set_mct_rules.item(row, col)
                values.append(item.text().strip() if item else "")
            line, model, mct_raw, stations_raw, tolerance_raw = values
            if not mct_raw:
                continue
            try:
                mct = float(mct_raw)
                stations = int(stations_raw or "1")
                tolerance = float(tolerance_raw or "0")
            except ValueError:
                raise ValueError(
                    f"MCT Rule row {row + 1}: MCT/Stations/Tolerance ต้องเป็นตัวเลข"
                )
            if mct <= 0 or stations <= 0 or tolerance < 0:
                raise ValueError(
                    f"MCT Rule row {row + 1}: ค่าไม่ถูกต้อง"
                )
            rules.append({
                "line": line or "*",
                "model": model or "*",
                "mct_sec": mct,
                "stations": stations,
                "tolerance_min": tolerance,
            })
        return rules

    def save_local_settings(self):
        if not self._admin_unlocked:
            QMessageBox.warning(self, "Admin Mode", "กรุณาปลดล็อก Admin Mode ก่อนบันทึก")
            return
        new_path = (
            self.txt_access_config_path
            .text()
            .strip()
        )
        new_url = (
            self.txt_qac_home_url
            .text()
            .strip()
        )

        if not new_path:
            QMessageBox.warning(
                self,
                "Settings",
                "Config Path ห้ามว่าง"
            )
            return

        if not new_url:
            QMessageBox.warning(
                self,
                "Settings",
                "QAC Home URL ห้ามว่าง"
            )
            return

        # Test the access file before allowing path save.
        try:
            record, _, resolved = (
                load_access_record(
                    new_path,
                    self.app_root_path
                )
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Settings",
                "ไม่สามารถ Save Config Path "
                "ที่ทดสอบไม่ผ่านได้\\n"
                f"{e}"
            )
            return

        if record is None:
            QMessageBox.critical(
                self,
                "Settings",
                "Config นี้ไม่มี IP เครื่องปัจจุบัน "
                "จึงไม่ Save เพื่อป้องกัน Lock ตัวเองออก"
            )
            return

        daily_source = self.txt_daily_list_source.text().strip()
        daily_sheet = self.txt_daily_sheet_name.text().strip() or "Raw"
        if not daily_source:
            QMessageBox.warning(
                self,
                "Settings",
                "Daily Document List Source ห้ามว่าง"
            )
            return

        try:
            daily_rows, daily_resolved = load_document_master(
                source_path=daily_source,
                app_root=self.app_root_path,
                sheet_name=daily_sheet,
                active_only=self.chk_daily_active_only.isChecked(),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Settings",
                "Daily Document List Source ทดสอบไม่ผ่าน\\n"
                f"{e}"
            )
            return

        try:
            mct_rules = self._collect_mct_rules()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Settings",
                "Hourly Validation / MCT Master ไม่ถูกต้อง\n" + str(e)
            )
            return

        required_labels = {
            "Production Downtime": self.txt_set_prod_down_label.text().strip(),
            "Production Category": self.txt_set_prod_cat_label.text().strip(),
            "Break Downtime": self.txt_set_break_down_label.text().strip(),
            "Break Category": self.txt_set_break_cat_label.text().strip(),
            "Break Description": self.txt_set_break_desc.text().strip(),
            "Setup Downtime": self.txt_set_setup_down_label.text().strip(),
            "Run-up Category": self.txt_set_setup_cat_label.text().strip(),
            "Setup Machine": self.txt_set_setup_machine_label.text().strip(),
            "Setup Description": self.txt_set_setup_desc.text().strip(),
            "Stop Downtime": self.txt_set_stop_down_label.text().strip(),
            "Stop Category": self.txt_set_stop_cat_label.text().strip(),
            "Stop Description": self.txt_set_stop_desc.text().strip(),
        }

        missing_labels = [
            name
            for name, value in required_labels.items()
            if not value
        ]

        if missing_labels:
            QMessageBox.warning(
                self,
                "Settings",
                "ค่าที่จำเป็นว่าง: "
                + ", ".join(missing_labels)
            )
            return

        for name, widget in (
            ("Day Shift Start", self.txt_set_day_start),
            ("Day Shift End", self.txt_set_day_end),
            ("Night Shift Start", self.txt_set_night_start),
            ("Night Shift End", self.txt_set_night_end),
        ):
            raw = widget.text().strip()
            try:
                datetime.strptime(raw, "%H:%M")
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Settings",
                    f"{name} ต้องเป็น HH:MM เช่น 20:00"
                )
                return

        self.settings.setdefault(
            "access_control",
            {}
        )["config_path"] = new_path
        self.settings["qac_home_url"] = new_url

        self.settings["auto_register_records"] = {
            "production": {
                "downtime_value": self.txt_set_prod_down_value.text().strip(),
                "downtime_label": self.txt_set_prod_down_label.text().strip(),
                "category_value": self.txt_set_prod_cat_value.text().strip(),
                "category_label": self.txt_set_prod_cat_label.text().strip(),
                "description": "",
                "time_rule": "start_only"
            },
            "break": {
                "downtime_value": self.txt_set_break_down_value.text().strip(),
                "downtime_label": self.txt_set_break_down_label.text().strip(),
                "category_value": self.txt_set_break_cat_value.text().strip(),
                "category_label": self.txt_set_break_cat_label.text().strip(),
                "description": self.txt_set_break_desc.text().strip(),
                "time_rule": "start_end"
            }
        }

        self.settings["production_output_import"] = {
            "day_shift_start": self.txt_set_day_start.text().strip(),
            "day_shift_end": self.txt_set_day_end.text().strip(),
            "night_shift_start": self.txt_set_night_start.text().strip(),
            "night_shift_end": self.txt_set_night_end.text().strip(),
            "setup": {
                "downtime_value": self.txt_set_setup_down_value.text().strip(),
                "downtime_label": self.txt_set_setup_down_label.text().strip(),
                "category_value": self.txt_set_setup_cat_value.text().strip(),
                "category_label": self.txt_set_setup_cat_label.text().strip(),
                "machine_value": self.txt_set_setup_machine_value.text().strip(),
                "machine_label": "",
                "machine_search_text": self.txt_set_setup_machine_label.text().strip(),
                "description": self.txt_set_setup_desc.text().strip()
            },
            "stop_line": {
                "downtime_value": self.txt_set_stop_down_value.text().strip(),
                "downtime_label": self.txt_set_stop_down_label.text().strip(),
                "category_value": self.txt_set_stop_cat_value.text().strip(),
                "category_label": self.txt_set_stop_cat_label.text().strip(),
                "description": self.txt_set_stop_desc.text().strip()
            }
        }

        # Save MCT to the central master beside access_control.csv, not local settings.
        try:
            mct_path = save_central_mct(
                new_path, self.app_root_path, mct_rules
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Central MCT Master",
                "ไม่สามารถบันทึก Central MCT Master ได้\n" + str(e)
            )
            return

        self.central_mct_path = str(mct_path)
        self.settings["hourly_validation"] = {"mct_rules": mct_rules}

        self.settings["daily_document"] = {
            "list_source": daily_source,
            "sheet_name": daily_sheet,
            "active_only": self.chk_daily_active_only.isChecked(),
        }
        # MCT rules are central-only. Do not duplicate them into local settings.json.
        runtime_hourly = self.settings.pop("hourly_validation", None)
        try:
            save_settings(self.settings)
        finally:
            self.settings["hourly_validation"] = runtime_hourly or {"mct_rules": mct_rules}

        self._update_central_mct_path_label()
        self.load_daily_document_list(show_message=False)
        if self.production_data:
            self._recalculate_production_validation()

        self.audit.write(
            "SETTINGS_SAVED",
            status="OK",
            config_path=new_path,
            qac_home_url=new_url,
            daily_document_source=str(daily_resolved),
            daily_document_rows=len(daily_rows),
            mct_rule_count=len(mct_rules),
            central_mct_path=self.central_mct_path
        )

        QMessageBox.information(
            self,
            "Settings",
            "บันทึก Settings แล้ว\\n"
            "Central permission จะอ่านใหม่ "
            "เมื่อเปิดโปรแกรมครั้งถัดไป"
        )

    # ---------------- shared browser ----------------
    def browser_key(self):
        return self.cmb_browser.currentData()

    def browser_cfg(self):
        return self.settings["browsers"][self.browser_key()]

    def log_msg(self, text):
        self.log.append(text)
        self.audit.write("AUTO_REGISTER_LOG", message=text)

    def alarm_log_msg(self, text):
        self.alarm_log.append(text)
        self.audit.write("ALARM_IMPORT_LOG", message=text)

    def refresh_browser_status(self):
        try:
            cfg = self.browser_cfg()
        except Exception:
            return

        ready = cdp_ready(cfg["cdp_url"])
        self.lbl_browser_status.setText(
            f'● Connected {cfg["cdp_url"]}'
            if ready else
            f'○ Not Connected {cfg["cdp_url"]}'
        )

    def _workflow_running(self) -> bool:
        """Block explicit scans while any write/prepare worker is active."""
        worker_names = (
            'register_worker', 'sample_register_worker', 'sample_prepare_worker',
            'daily_register_worker', 'alarm_import_worker', 'ocr_register_worker',
            'production_transfer_worker', 'production_worker',
            'daily_scan_worker', 'scan_worker', 'html_collector_worker',
        )
        for name in worker_names:
            worker = getattr(self, name, None)
            try:
                if worker is not None and worker.isRunning():
                    return True
            except (AttributeError, RuntimeError):
                continue
        return False

    def _ensure_local_action(self, title: str) -> bool:
        """Guard explicit QAC actions. Never scan here or re-navigate the page."""
        if not self._employee_id():
            QMessageBox.warning(self, title, 'กรุณากรอก Employee ID ก่อนเริ่มทำงาน')
            self.txt_employee_id.setFocus()
            return False
        try:
            result = self.local_connection.ensure(
                self.browser_cfg(),
                self.settings.get('qac_home_url', 'http://159.228.251.234:8077/'),
            )
        except Exception as exc:
            QMessageBox.warning(self, title, f'Local Web connection error: {exc}')
            return False
        if not result.ok:
            QMessageBox.warning(self, title, result.message)
            return False
        self.refresh_browser_status()
        return True

    def _employee_id(self) -> str:
        return str(getattr(self, "txt_employee_id", None).text() if hasattr(self, "txt_employee_id") else "").strip()

    def daily_log_msg(self, text):
        if hasattr(self, "daily_log"):
            self.daily_log.append(str(text))
        self.audit.write("DAILY_DOCUMENT_LOG", message=str(text))

    def _on_main_tab_changed(self, index: int):
        """Tab changes are UI-only.

        Never navigate QAC, click VIEW MORE, login, refresh, or scan merely
        because the user changed tabs. QAC actions must start only from an
        explicit button click in that tab.
        """
        if index == 0:
            self.log_msg("AUTO REGISTER READY | กด Scan QAC Tabs เมื่อต้องการเริ่มค้นหา")
        elif index == 4 and hasattr(self, "lbl_daily_status"):
            if not self.lbl_daily_status.text().strip():
                self.lbl_daily_status.setText(
                    "พร้อมใช้งาน - กด Open / Verify หรือ Scan Selected เพื่อเริ่ม"
                )
            self.daily_log_msg(
                "DAILY DOCUMENT READY | เปลี่ยนแท็บอย่างเดียว ไม่เปลี่ยนหน้า QAC"
            )
        elif index == 5 and hasattr(self, "sample_log"):
            self.sample_log_msg(
                "SAMPLE REGISTER READY | เปลี่ยนแท็บอย่างเดียว ไม่แตะ QAC จนกด Prepare/Register"
            )

    def connect_qac_session(self):
        self.ensure_qac_module(None)

    def ensure_qac_module(self, module_key=None, silent_if_no_employee=False):
        employee_id = self._employee_id()
        if not employee_id:
            if not silent_if_no_employee:
                QMessageBox.warning(self, "QAC Login", "กรุณากรอก Employee ID")
                self.txt_employee_id.setFocus()
            return

        if self.qac_session_worker and self.qac_session_worker.isRunning():
            # Avoid concurrent Playwright navigation commands against the same
            # dedicated QAC browser session.
            return

        cfg = self.browser_cfg()
        home_url = self.settings.get(
            "qac_home_url",
            "http://159.228.251.234:8077/"
        )

        if not cdp_ready(cfg["cdp_url"]):
            ok, msg = launch_browser(cfg, home_url)
            self.log_msg(msg)
            self.daily_log_msg(msg)
            self.refresh_browser_status()
            if not ok:
                QMessageBox.warning(self, "QAC Browser", msg)
                return

        self._last_module_request = module_key
        self.btn_qac_connect.setEnabled(False)
        self.lbl_qac_session.setText("QAC Session: Connecting...")
        if module_key == "daily_document":
            self.btn_daily_open.setEnabled(False)

        self.qac_session_worker = QACSessionWorker(
            cdp_url=cfg["cdp_url"],
            employee_id=employee_id,
            module_key=module_key,
            home_url=home_url,
        )
        self.qac_session_worker.progress.connect(self._qac_session_progress)
        self.qac_session_worker.completed.connect(self._qac_session_completed)
        self.qac_session_worker.failed.connect(self._qac_session_failed)
        self.qac_session_worker.start()

    def _qac_session_progress(self, message: str):
        self.lbl_qac_session.setText(str(message))
        self.log_msg(str(message))
        self.daily_log_msg(str(message))

    def _qac_session_completed(self, result):
        self.btn_qac_connect.setEnabled(True)
        if hasattr(self, "btn_daily_open"):
            self.btn_daily_open.setEnabled(True)
        module_name = str((result or {}).get("module_name") or "").strip()
        reused = bool((result or {}).get("reused"))
        if module_name:
            self.lbl_qac_session.setText(
                f"QAC Session: Connected | {module_name}" +
                (" | already open" if reused else "")
            )
            if (result or {}).get("module") == "daily_document":
                self.lbl_daily_status.setText(
                    "Production Check Sheet พร้อมใช้งาน" +
                    (" (เปิดอยู่แล้ว)" if reused else "")
                )
            elif (result or {}).get("module") == "auto_register":
                # Auto Register navigation is complete. Start the actual scan
                # only when it was requested explicitly by the Scan button.
                if getattr(self, "_pending_auto_scan", False):
                    self._pending_auto_scan = False
                    self._start_scan_tabs_worker()

            if (result or {}).get("module") == "daily_document":
                payload = getattr(self, "_pending_daily_scan_payload", None)
                if payload:
                    self._pending_daily_scan_payload = None
                    self._start_daily_scan_worker(*payload)
                html_payload = getattr(self, "_pending_html_collect_payload", None)
                if html_payload:
                    self._pending_html_collect_payload = None
                    self._start_html_collector_worker(*html_payload)
                register_payload = getattr(self, "_pending_daily_register_payload", None)
                if register_payload:
                    self._pending_daily_register_payload = None
                    self._start_daily_register_worker(*register_payload)
            if (result or {}).get("module") == "sample_register":
                sample_payload = getattr(self, "_pending_sample_prepare_payload", None)
                if sample_payload:
                    self._pending_sample_prepare_payload = None
                    self._start_sample_prepare_worker(*sample_payload)
        else:
            self.lbl_qac_session.setText(
                f"QAC Session: Connected | Employee {self._employee_id()}"
            )
        self.audit.write(
            "QAC_SESSION_READY",
            employee_id=self._employee_id(),
            module=(result or {}).get("module"),
            reused=reused,
            opened=(result or {}).get("opened"),
        )

    def _qac_session_failed(self, error: str):
        self.btn_qac_connect.setEnabled(True)
        if getattr(self, "_pending_auto_scan", False):
            self._pending_auto_scan = False
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("Scan QAC Tabs")
        if getattr(self, "_pending_daily_scan_payload", None):
            self._pending_daily_scan_payload = None
            if hasattr(self, "btn_daily_scan_selected"):
                self.btn_daily_scan_selected.setEnabled(True)
            if hasattr(self, "btn_daily_run_due"):
                self.btn_daily_run_due.setEnabled(True)
        if getattr(self, "_pending_html_collect_payload", None):
            self._pending_html_collect_payload = None
            if hasattr(self, "btn_html_collect"):
                self.btn_html_collect.setEnabled(True)
                self.btn_html_pause.setEnabled(False)
                self.btn_html_resume.setEnabled(False)
                self.btn_html_stop.setEnabled(False)
        if getattr(self, "_pending_daily_register_payload", None):
            self._pending_daily_register_payload = None
            if hasattr(self, "btn_daily_register_ok"):
                self.btn_daily_register_ok.setEnabled(True)
                self.btn_daily_register_pause.setEnabled(False)
                self.btn_daily_register_resume.setEnabled(False)
                self.btn_daily_register_stop.setEnabled(False)
        if getattr(self, "_pending_sample_prepare_payload", None):
            self._pending_sample_prepare_payload = None
            if hasattr(self, "btn_sample_prepare"):
                self.btn_sample_prepare.setEnabled(True)

        if hasattr(self, "btn_daily_open"):
            self.btn_daily_open.setEnabled(True)
        self.lbl_qac_session.setText("QAC Session: ERROR")
        if hasattr(self, "lbl_daily_status") and self._last_module_request == "daily_document":
            self.lbl_daily_status.setText("Production Check Sheet เปิดไม่สำเร็จ")
        self.log_msg(f"QAC SESSION ERROR: {error}")
        self.daily_log_msg(f"QAC SESSION ERROR: {error}")
        QMessageBox.critical(self, "QAC Session", str(error))

    def open_browser(self):
        cfg = self.browser_cfg()
        self.audit.write(
            "OPEN_QAC_BROWSER",
            browser=self.browser_key(),
            qac_home_url=self.settings.get(
                "qac_home_url",
                ""
            )
        )
        qac_url = self.settings.get(
            "qac_home_url",
            "http://159.228.251.234:8077/"
        )
        ok, msg = launch_browser(
            cfg,
            qac_url
        )
        self.log_msg(msg)
        self.alarm_log_msg(msg)
        self.refresh_browser_status()

        if not ok:
            QMessageBox.warning(self, cfg["display_name"], msg)

    def scan_tabs(self):
        """Explicit Auto Register action: enter PCB first, then scan tabs."""
        if self._workflow_running():
            QMessageBox.warning(self, 'QAC Scan', 'มี Workflow ทำงานอยู่ — ไม่อนุญาตให้ Scan ซ้ำ')
            return
        if self.qac_session_worker and self.qac_session_worker.isRunning():
            return
        if getattr(self, "scan_worker", None) and self.scan_worker.isRunning():
            return

        self._pending_auto_scan = True
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Opening QAC...")
        self.ensure_qac_module("auto_register")

    def _start_scan_tabs_worker(self):
        cfg = self.browser_cfg()
        self.audit.write(
            "SCAN_QAC_TABS",
            browser=self.browser_key()
        )

        if not cdp_ready(cfg["cdp_url"]):
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("Scan QAC Tabs")
            QMessageBox.warning(self, "QAC Browser", "QAC Browser ยังไม่พร้อม")
            return

        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("Scanning...")

        self.scan_worker = ScanWorker(cfg["cdp_url"])
        self.scan_worker.completed.connect(self.scan_completed)
        self.scan_worker.failed.connect(self.scan_failed)
        self.scan_worker.start()

    def scan_completed(self, docs):
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("Scan QAC Tabs")
        production_dates = {str(getattr(d, 'production_date', '') or '').strip() for d in docs}
        production_dates.discard('')
        if len(production_dates) == 1:
            try:
                self.reference_dates.publish(next(iter(production_dates)))
                for module, editor_name in (("sample_register", "sample_date"), ("daily_document", "daily_date")):
                    editor = getattr(self, editor_name, None)
                    published_date = self.reference_dates.date_for(module)
                    if editor is not None and published_date and editor.date().toString("yyyy-MM-dd") != published_date:
                        editor.blockSignals(True)
                        try:
                            editor.setDate(QDate.fromString(published_date, "yyyy-MM-dd"))
                        finally:
                            editor.blockSignals(False)
            except ValueError:
                pass
        self.auto_register_state.accept_explicit_scan(docs)
        self.documents = list(self.auto_register_state.documents)

        self.cmb_doc.blockSignals(True)
        self.cmb_doc.clear()

        self.cmb_alarm_doc.blockSignals(True)
        self.cmb_alarm_doc.clear()

        self.cmb_ocr_doc.blockSignals(True)
        self.cmb_ocr_doc.clear()

        self.cmb_prod_doc.blockSignals(True)
        self.cmb_prod_doc.clear()

        for doc in docs:
            self.cmb_doc.addItem(doc.label)
            self.cmb_alarm_doc.addItem(doc.label)
            self.cmb_ocr_doc.addItem(doc.label)
            self.cmb_prod_doc.addItem(doc.label)

        self.cmb_doc.blockSignals(False)
        self.cmb_alarm_doc.blockSignals(False)
        self.cmb_ocr_doc.blockSignals(False)
        self.cmb_prod_doc.blockSignals(False)

        self.log_msg(f"พบ QAC Document {len(docs)} แท็บ")
        self.alarm_log_msg(
            f"พบ QAC Document {len(docs)} แท็บ"
        )
        self.ocr_log_msg(
            f"พบ QAC Document {len(docs)} แท็บ"
        )
        self.production_log_msg(
            f"พบ QAC Document {len(docs)} แท็บ"
        )

        if not docs:
            self.log_msg(
                "ไม่พบ measure.html ใน Browser ที่เลือก "
                "หรือหน้า QAC ยังโหลดไม่สมบูรณ์"
            )
            self.alarm_log_msg(
                "ไม่พบ measure.html ใน Browser ที่เลือก "
                "หรือหน้า QAC ยังโหลดไม่สมบูรณ์"
            )

        if docs:
            self.cmb_doc.setCurrentIndex(0)
            self.document_changed(0)
            self.cmb_alarm_doc.setCurrentIndex(0)
            self.alarm_document_changed(0)
            self.cmb_ocr_doc.setCurrentIndex(0)
            self.ocr_document_changed(0)
            self.cmb_prod_doc.setCurrentIndex(0)
            self.production_document_changed(0)

    def scan_failed(self, error):
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("Scan QAC Tabs")

        self.log_msg(f"SCAN ERROR: {error}")
        self.alarm_log_msg(f"SCAN ERROR: {error}")
        self.ocr_log_msg(f"SCAN ERROR: {error}")
        self.production_log_msg(f"SCAN ERROR: {error}")
        QMessageBox.critical(self, "QAC Scan", error)

    # ---------------- auto register logic ----------------
    def _publish_document_reference_date(self, production_date):
        """Publish selected document date; never reset a module's manual override."""
        try:
            self.reference_dates.publish(production_date)
        except (ValueError, TypeError):
            return
        for module, editor_name in (("sample_register", "sample_date"),
                                    ("daily_document", "daily_date")):
            editor = getattr(self, editor_name, None)
            value = self.reference_dates.date_for(module)
            if editor is None or not value:
                continue
            next_date = QDate.fromString(value, "yyyy-MM-dd")
            if next_date.isValid() and editor.date() != next_date:
                editor.blockSignals(True)
                try:
                    editor.setDate(next_date)
                finally:
                    editor.blockSignals(False)

    def document_changed(self, index):
        self.cmb_model.clear()

        if index < 0 or index >= len(self.documents):
            return

        doc = self.documents[index]
        # Daily Document starts with the same line as Auto Register, but the
        # Daily combo remains fully editable by the user.
        self._set_daily_line_from_auto_register(force=True)
        # Sample selection is never mutated by Auto Register navigation.
        self._publish_document_reference_date(doc.production_date)

        self.lbl_doc.setText(
            f"Date: {doc.production_date}    "
            f"Line: {doc.line}    "
            f"Shift: {doc.shift}\n"
            f"Document: {doc.document_no}\n"
            f"URL: {doc.url}"
        )

        for model in doc.models:
            self.cmb_model.addItem(model.label, model)

        self.refresh_preview()

    def refresh_preview(self):
        di = self.cmb_doc.currentIndex()
        mi = self.cmb_model.currentIndex()

        self.tbl.setRowCount(0)
        self.current_actions = []

        if di < 0 or di >= len(self.documents) or mi < 0:
            return

        doc = self.documents[di]
        model = self.cmb_model.currentData()

        if not model:
            return

        actions = build_schedule(
            doc.shift,
            model.value,
            model.name,
            self.settings
        )
        self.current_actions = actions

        for action in actions:
            row = self.tbl.rowCount()
            self.tbl.insertRow(row)

            status_item = QTableWidgetItem("CHECKING...")
            status_item.setFlags(
                status_item.flags() & ~Qt.ItemIsEditable
            )
            status_item.setTextAlignment(Qt.AlignCenter)
            self.tbl.setItem(row, 0, status_item)

            self.tbl.setItem(
                row, 1,
                QTableWidgetItem(action["kind"])
            )
            self.tbl.setItem(
                row, 2,
                QTableWidgetItem(action["start"])
            )
            self.tbl.setItem(
                row, 3,
                QTableWidgetItem(action["end"])
            )
            self.tbl.setItem(
                row, 4,
                QTableWidgetItem(
                    action.get("model_name", "")
                )
            )

        self.refresh_existing_auto_status()

    @staticmethod
    def _norm_auto_clock(value):
        raw = str(value or "").strip().upper()
        for fmt in (
            "%H:%M:%S",
            "%H:%M",
            "%I:%M %p",
            "%I:%M:%S %p",
        ):
            try:
                return datetime.strptime(
                    raw,
                    fmt
                ).strftime("%H:%M")
            except ValueError:
                pass
        return raw.lower()

    @staticmethod
    def _timeline_event_type(text):
        value = " ".join(
            str(text or "").split()
        ).lower()

        if "production output" in value:
            return "production"
        if "schedule downtime" in value:
            return "break"

        return ""

    @staticmethod
    def _timeline_times(text):
        """
        Extract visible timeline clock strings such as:
        9:00 - 9:00PM
        10:00 - 10:10PM
        12:10 - 12:50AM
        """
        import re

        value = " ".join(
            str(text or "").split()
        )

        matches = re.findall(
            r'(\\d{1,2}:\\d{2}(?:\\s*[AP]M)?)',
            value,
            flags=re.IGNORECASE
        )

        if not matches:
            return "", ""

        # If only second time carries AM/PM, propagate it to first.
        if len(matches) >= 2:
            a, b = matches[0], matches[1]
            suffix = ""
            m = re.search(
                r'([AP]M)',
                b,
                flags=re.IGNORECASE
            )
            if m:
                suffix = m.group(1).upper()
            if suffix and not re.search(
                r'[AP]M',
                a,
                flags=re.IGNORECASE
            ):
                a = f"{a}{suffix}"
            return a, b

        return matches[0], matches[0]

    def refresh_existing_auto_status(self):
        if not self.current_actions:
            return

        di = self.cmb_doc.currentIndex()
        if di < 0 or di >= len(self.documents):
            return

        if (
            self.auto_existing_worker
            and self.auto_existing_worker.isRunning()
        ):
            return

        cfg = self.browser_cfg()
        doc = self.documents[di]

        self.auto_existing_worker = ExistingAlarmWorker(
            cfg["cdp_url"],
            doc.page_index
        )
        self.auto_existing_worker.progress.connect(
            self.log_msg
        )
        self.auto_existing_worker.completed.connect(
            self._auto_existing_loaded
        )
        self.auto_existing_worker.failed.connect(
            lambda e: self.log_msg(
                f"Existing QAC scan warning: {e}"
            )
        )
        self.auto_existing_worker.start()

    def _auto_existing_loaded(self, payload):
        """
        Supports both detailed form rows and timeline fallback rows.
        """
        self.auto_existing_events = list(payload or [])

        model = self.cmb_model.currentData()
        model_value = str(
            getattr(model, "value", "") or ""
        )

        matched_count = 0

        for row, action in enumerate(
            self.current_actions
        ):
            status = self.tbl.item(row, 0)
            if status is None:
                continue

            expected_start = self._norm_auto_clock(
                action["start"]
            )
            expected_end = self._norm_auto_clock(
                action["end"]
            )

            found = None

            for ev in self.auto_existing_events:
                kind = str(
                    ev.get("kind") or ""
                ).strip().lower()

                if not kind:
                    kind = self._timeline_event_type(
                        ev.get("timeline_text", "")
                    )

                # Detailed DOM values take priority.
                topic = str(
                    ev.get("topic_value") or ""
                )
                category = str(
                    ev.get("category_value") or ""
                )

                if action["kind"] == "production":
                    if topic:
                        if (
                            topic != "24217"
                            or category != "94"
                        ):
                            continue
                    elif kind != "production":
                        continue
                else:
                    if topic:
                        if (
                            topic != "24215"
                            or category != "92"
                        ):
                            continue
                    elif kind != "break":
                        continue

                ev_start = ev.get("start") or ""
                ev_end = ev.get("end") or ""

                if (
                    not ev_start
                    and ev.get("timeline_text")
                ):
                    ev_start, ev_end = (
                        self._timeline_times(
                            ev["timeline_text"]
                        )
                    )

                if (
                    self._norm_auto_clock(ev_start)
                    != expected_start
                ):
                    continue

                if action["kind"] == "break":
                    if (
                        self._norm_auto_clock(ev_end)
                        != expected_end
                    ):
                        continue

                # For Production, compare model if QAC exposes it.
                ev_model = str(
                    ev.get("model_value") or ""
                )
                if (
                    action["kind"] == "production"
                    and ev_model
                    and model_value
                    and ev_model != model_value
                ):
                    continue

                found = ev
                break

            if found:
                matched_count += 1
                action["_existing"] = True
                action["_existing_result_id"] = (
                    found.get("result_id", "")
                )

                status.setText("EXISTS ✓")
                status.setToolTip(
                    "พบรายการนี้ใน QAC แล้ว "
                    f"| Result ID: "
                    f"{found.get('result_id','')}"
                )
            else:
                action["_existing"] = False
                action["_existing_result_id"] = ""
                status.setText("NEW")
                status.setToolTip(
                    "ยังไม่พบรายการนี้ใน QAC"
                )

        self.log_msg(
            f"Existing QAC Check: "
            f"ลงแล้ว {matched_count}/"
            f"{len(self.current_actions)} events"
        )

    def run_register(self):
        if not self._ensure_local_action('Auto Register'):
            return
        if not self._permission_or_warn(1):
            return

        di = self.cmb_doc.currentIndex()

        if di < 0 or di >= len(self.documents):
            QMessageBox.warning(
                self, "Register", "กรุณาเลือก QAC Document"
            )
            return

        if not self.current_actions:
            QMessageBox.warning(
                self, "Register", "ไม่มี Schedule สำหรับ Register"
            )
            return

        actions_to_run = [
            action
            for action in self.current_actions
            if not action.get("_existing", False)
        ]

        if not actions_to_run:
            QMessageBox.information(
                self,
                "Register",
                "รายการทั้งหมดมีอยู่ใน QAC แล้ว "
                "ไม่มีรายการใหม่ให้ Register"
            )
            return

        dry = self.chk_dry.isChecked()

        if not dry:
            answer = QMessageBox.question(
                self,
                "Confirm",
                f"กำลังจะบันทึกจริง {len(actions_to_run)} รายการใหม่\n"
                f"ต้องการดำเนินการต่อหรือไม่?"
            )
            if answer != QMessageBox.Yes:
                return

        cfg = self.browser_cfg()
        doc = self.documents[di]

        self.audit.write(
            "AUTO_REGISTER_START",
            dry_run=dry,
            document=doc.label,
            action_count=len(actions_to_run)
        )

        self.btn_register.setEnabled(False)
        self.btn_register.setText("Running...")

        self.register_worker = RegisterWorker(
            cfg["cdp_url"],
            doc.page_index,
            actions_to_run,
            dry,
            expected_document={
                "production_date": doc.production_date,
                "line": doc.line,
                "shift": doc.shift,
                "document_no": doc.document_no,
                "url": doc.url,
            },
        )
        self.register_worker.progress.connect(self.log_msg)
        self.register_worker.completed.connect(
            lambda: self.register_completed(dry)
        )
        self.register_worker.failed.connect(self.register_failed)
        self.register_worker.start()

    def pause_register(self):
        if self.register_worker and self.register_worker.isRunning():
            self.register_worker.request_pause()
            self.log_msg("Pause requested - จะหยุดก่อน Event ถัดไป")

    def resume_register(self):
        if self.register_worker and self.register_worker.isRunning():
            self.register_worker.request_resume()
            self.log_msg("Resume requested")

    def stop_register(self):
        if self.register_worker and self.register_worker.isRunning():
            self.register_worker.request_stop()
            self.log_msg("Stop requested - งานที่กำลัง Save จะจบก่อนแล้วค่อยหยุด")

    def register_completed(self, dry):
        self.audit.write(
            "AUTO_REGISTER_COMPLETE",
            status="OK",
            dry_run=dry
        )
        self.btn_register.setEnabled(True)
        self.btn_register.setText("REGISTER")
        QMessageBox.information(
            self,
            "Register",
            "Dry Run เสร็จแล้ว" if dry else "Register เสร็จแล้ว"
        )

    def register_failed(self, error):
        self.audit.write(
            "AUTO_REGISTER_FAILED",
            status="ERROR",
            error=error
        )
        self.btn_register.setEnabled(True)
        self.btn_register.setText("REGISTER")
        self.log_msg(f"REGISTER ERROR: {error}")
        QMessageBox.critical(self, "Register Error", error)

    # ---------------- Alarm file/table ----------------
    def _match_itag_line(self, doc):
        """
        Match selected QAC document line to the actual I-TAG
        Production Line Found option, e.g.
        TS2-Sub -> PRODUCTION-TS2-Sub.
        """
        target = f"PRODUCTION-{doc.line}".strip().lower()
        normalized_target = target.replace(" ", "")

        for opt in doc.itag_lines:
            name = opt.name.strip().lower()
            if name == target:
                return opt
            if name.replace(" ", "") == normalized_target:
                return opt

        return None

    def alarm_document_changed(self, index):
        self.cmb_alarm_model.clear()
        self.cmb_itag_line.blockSignals(True)
        self.cmb_itag_line.clear()
        self.cmb_itag_line.addItem(
            "Select Production Line Found",
            None
        )
        self.current_itag_line = None

        if index < 0 or index >= len(self.documents):
            self.cmb_itag_line.blockSignals(False)
            return

        doc = self.documents[index]

        for model in doc.models:
            self.cmb_alarm_model.addItem(model.label, model)

        # Top selector must contain the real QAC Production Line Found options.
        for opt in doc.itag_lines:
            self.cmb_itag_line.addItem(opt.label, opt)

        matched = self._match_itag_line(doc)

        if matched is not None:
            for i in range(self.cmb_itag_line.count()):
                data = self.cmb_itag_line.itemData(i)
                if data and data.value == matched.value:
                    self.cmb_itag_line.setCurrentIndex(i)
                    self.current_itag_line = matched
                    break

        self.cmb_itag_line.blockSignals(False)

        if self.current_itag_line is None:
            self.alarm_log_msg(
                f"I-TAG: ไม่พบ Production Line Found "
                f"ที่ตรงกับเอกสาร {doc.line}"
            )
            self.itag_process_options = []
            self.rebuild_alarm_process_comboboxes()
        else:
            self.alarm_log_msg(
                f"I-TAG Production Line Found = "
                f"{self.current_itag_line.name}"
            )
            self.load_itag_process_found(
                doc,
                self.current_itag_line
            )

        if self.alarm_rows:
            self.rebuild_alarm_table()

    def itag_line_changed(self, index):
        self.current_itag_line = self.cmb_itag_line.currentData()

        di = self.cmb_alarm_doc.currentIndex()
        if (
            self.current_itag_line is None
            or di < 0
            or di >= len(self.documents)
        ):
            self.itag_process_options = []
            self.rebuild_alarm_process_comboboxes()
            return

        doc = self.documents[di]

        self.alarm_log_msg(
            f"I-TAG Production Line Found = "
            f"{self.current_itag_line.name}"
        )

        self.load_itag_process_found(
            doc,
            self.current_itag_line
        )

    def load_itag_process_found(self, doc, line_option):
        cfg = self.browser_cfg()

        self.itag_process_options = []
        self.rebuild_alarm_process_comboboxes(
            loading=True
        )

        self.itag_process_worker = ItagProcessWorker(
            cfg["cdp_url"],
            doc.page_index,
            line_option.value
        )
        self.itag_process_worker.completed.connect(
            self.itag_process_loaded
        )
        self.itag_process_worker.failed.connect(
            self.itag_process_failed
        )
        self.itag_process_worker.start()

    def itag_process_loaded(self, options):
        self.itag_process_options = options

        self.alarm_log_msg(
            f"I-TAG Process Found: {len(options)} รายการ"
        )

        self.rebuild_alarm_process_comboboxes()

    def itag_process_failed(self, error):
        self.itag_process_options = []
        self.rebuild_alarm_process_comboboxes(
            error_text="โหลด Process Found ไม่สำเร็จ"
        )

        self.alarm_log_msg(
            f"I-TAG PROCESS ERROR: {error}"
        )

        QMessageBox.warning(
            self,
            "I-TAG Process Found",
            error
        )

    def rebuild_alarm_process_comboboxes(
        self,
        loading=False,
        error_text=""
    ):
        for row in range(self.tbl_alarm.rowCount()):
            self._remember_alarm_row_selection(row)
            combo = make_searchable(QComboBox())

            if error_text:
                combo.addItem(error_text, None)
                combo.setEnabled(False)
            elif loading:
                combo.addItem("Loading Process Found...", None)
                combo.setEnabled(False)
            else:
                combo.addItem("Select Process Found", None)
                for opt in getattr(
                    self,
                    "itag_process_options",
                    []
                ):
                    combo.addItem(opt.label, opt)

            self.tbl_alarm.setCellWidget(
                row,
                8,
                combo
            )
            if not loading and not error_text:
                if row < len(self.alarm_rows):
                    self._restore_alarm_row_selection(row, self.alarm_rows[row])
                self._apply_alarm_process_suggestion(row)
            combo.currentIndexChanged.connect(
                lambda _index, table_row=row: self._remember_alarm_row_selection(table_row)
            )

    # ---------------- OCR NG logic ----------------
    def set_ocr_progress(
        self,
        percent,
        text
    ):
        value = max(
            0,
            min(
                100,
                int(percent)
            )
        )
        self.ocr_progress_bar.setValue(
            value
        )
        self.lbl_ocr_progress.setText(
            str(text)
        )

    def ocr_register_progress(
        self,
        text
    ):
        text = str(text)
        self.ocr_log_msg(
            text
        )

        # AlarmImportWorker emits [Alarm i/total] for each OCR register row.
        match = re.search(
            r"\\[Alarm\\s+(\\d+)/(\\d+)\\]",
            text
        )

        if match:
            current = int(
                match.group(1)
            )
            total = max(
                1,
                int(match.group(2))
            )

            # Event starts at its fraction; COMPLETE moves to full fraction.
            if "COMPLETE" in text:
                percent = int(
                    (current / total) * 100
                )
                status = (
                    f"Register QAC {current}/{total} COMPLETE"
                )
            else:
                percent = int(
                    ((current - 1) / total) * 100
                )
                status = (
                    f"กำลัง Register QAC {current}/{total}"
                )

            self.set_ocr_progress(
                percent,
                status
            )

    def ocr_log_msg(self, text):
        self.ocr_log.append(
            str(text)
        )
        self.audit.write(
            "OCR_NG_LOG",
            message=str(text)
        )

    def _match_ocr_itag_line(
        self,
        doc
    ):
        target = (
            f"PRODUCTION-{doc.line}"
            .strip()
            .lower()
            .replace(" ", "")
        )

        for opt in doc.itag_lines:
            if (
                opt.name
                .strip()
                .lower()
                .replace(" ", "")
                == target
            ):
                return opt

        return None

    def ocr_document_changed(
        self,
        index
    ):
        self.cmb_ocr_model.clear()

        self.cmb_ocr_itag_line.blockSignals(
            True
        )
        self.cmb_ocr_itag_line.clear()
        self.cmb_ocr_itag_line.addItem(
            "Select Production Line Found",
            None
        )

        self.ocr_itag_line = None
        self.ocr_process_options = []

        if (
            index < 0
            or index >= len(self.documents)
        ):
            self.cmb_ocr_itag_line.blockSignals(
                False
            )
            self.rebuild_ocr_process_comboboxes()
            return

        doc = self.documents[index]

        for model in doc.models:
            self.cmb_ocr_model.addItem(
                model.label,
                model
            )

        for opt in doc.itag_lines:
            self.cmb_ocr_itag_line.addItem(
                opt.label,
                opt
            )

        matched = self._match_ocr_itag_line(
            doc
        )

        if matched is not None:
            for i in range(
                self.cmb_ocr_itag_line.count()
            ):
                data = (
                    self.cmb_ocr_itag_line
                    .itemData(i)
                )
                if (
                    data
                    and data.value
                    == matched.value
                ):
                    self.cmb_ocr_itag_line.setCurrentIndex(
                        i
                    )
                    self.ocr_itag_line = matched
                    break

        self.cmb_ocr_itag_line.blockSignals(
            False
        )

        if self.ocr_itag_line is not None:
            self.load_ocr_process_found(
                doc,
                self.ocr_itag_line
            )
        else:
            self.rebuild_ocr_process_comboboxes()

        if self.ocr_rows:
            self.rebuild_ocr_table()

    def ocr_itag_line_changed(
        self,
        index
    ):
        self.ocr_itag_line = (
            self.cmb_ocr_itag_line
            .currentData()
        )

        di = self.cmb_ocr_doc.currentIndex()

        if (
            self.ocr_itag_line is None
            or di < 0
            or di >= len(self.documents)
        ):
            self.ocr_process_options = []
            self.rebuild_ocr_process_comboboxes()
            return

        self.load_ocr_process_found(
            self.documents[di],
            self.ocr_itag_line
        )

    def load_ocr_process_found(
        self,
        doc,
        line_option
    ):
        cfg = self.browser_cfg()

        self.ocr_process_options = []
        self.rebuild_ocr_process_comboboxes(
            loading=True
        )

        self.ocr_itag_worker = ItagProcessWorker(
            cfg["cdp_url"],
            doc.page_index,
            line_option.value
        )
        self.ocr_itag_worker.completed.connect(
            self.ocr_process_loaded
        )
        self.ocr_itag_worker.failed.connect(
            self.ocr_process_failed
        )
        self.ocr_itag_worker.start()

    def ocr_process_loaded(
        self,
        options
    ):
        self.ocr_process_options = list(
            options or []
        )
        self.ocr_log_msg(
            f"I-TAG Process Found: "
            f"{len(self.ocr_process_options)} รายการ"
        )
        self.rebuild_ocr_process_comboboxes()

    def ocr_process_failed(
        self,
        error
    ):
        self.ocr_process_options = []
        self.rebuild_ocr_process_comboboxes(
            error_text=(
                "โหลด Process Found ไม่สำเร็จ"
            )
        )
        self.ocr_log_msg(
            f"I-TAG PROCESS ERROR: {error}"
        )

    def rebuild_ocr_process_comboboxes(
        self,
        loading=False,
        error_text=""
    ):
        for row in range(
            self.tbl_ocr.rowCount()
        ):
            combo = make_searchable(
                QComboBox()
            )

            if error_text:
                combo.addItem(
                    error_text,
                    None
                )
                combo.setEnabled(False)
            elif loading:
                combo.addItem(
                    "Loading Process Found...",
                    None
                )
                combo.setEnabled(False)
            else:
                combo.addItem(
                    "Select Process Found",
                    None
                )
                for opt in self.ocr_process_options:
                    combo.addItem(
                        opt.label,
                        opt
                    )

            self.tbl_ocr.setCellWidget(
                row,
                10,
                combo
            )

    def add_ocr_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select NG Images",
            "",
            (
                "Images "
                "(*.jpg *.jpeg *.png *.bmp *.tif *.tiff);;"
                "All Files (*.*)"
            )
        )

        if not paths:
            return

        for path in paths:
            if path not in self.ocr_files:
                self.ocr_files.append(
                    path
                )

        self.lbl_ocr_files.setText(
            f"{len(self.ocr_files)} images | "
            f"{len(self.ocr_rows)} rows"
        )

        self.audit.write(
            "OCR_IMAGES_SELECTED",
            files=list(self.ocr_files)
        )

    def clear_ocr(self):
        self.ocr_files = []
        self.ocr_results = []
        self.ocr_rows = []
        self.tbl_ocr.setRowCount(0)
        self.lbl_ocr_files.setText(
            "0 images | 0 rows"
        )
        self.ocr_log.clear()
        self.set_ocr_progress(
            0,
            "Ready"
        )

    def run_ocr(self):
        if not self._permission_or_warn(3):
            return

        if not self.ocr_files:
            QMessageBox.warning(
                self,
                "OCR NG",
                "กรุณา Add Images ก่อน"
            )
            return

        ocr_cfg = self.settings.get(
            "ocr",
            {}
        )
        configured = ocr_cfg.get(
            "tesseract_cmd",
            ""
        )

        engine = find_tesseract(
            configured,
            self.app_root_path
        )

        if not engine:
            QMessageBox.critical(
                self,
                "OCR Engine",
                (
                    "ไม่พบ Tesseract OCR engine\\n\\n"
                    "ติดตั้ง Tesseract-OCR หรือวาง portable ที่\\n"
                    "tools\\\\Tesseract-OCR\\\\tesseract.exe"
                )
            )
            return

        self.btn_ocr_run.setEnabled(False)
        self.btn_ocr_run.setText(
            "OCR Running..."
        )
        self.set_ocr_progress(
            0,
            "กำลังเริ่ม OCR..."
        )

        self.ocr_worker = OcrBatchWorker(
            self.ocr_files,
            configured,
            str(self.app_root_path)
        )
        self.ocr_worker.progress.connect(
            self.ocr_log_msg
        )
        self.ocr_worker.progress_percent.connect(
            self.set_ocr_progress
        )
        self.ocr_worker.completed.connect(
            self.ocr_completed
        )
        self.ocr_worker.failed.connect(
            self.ocr_failed
        )
        self.ocr_worker.start()

    def ocr_completed(
        self,
        results
    ):
        self.btn_ocr_run.setEnabled(True)
        self.btn_ocr_run.setText(
            "Run OCR"
        )
        self.set_ocr_progress(
            100,
            "OCR COMPLETE"
        )

        self.ocr_results = list(
            results or []
        )
        self.ocr_rows = []

        for result in self.ocr_results:
            self.ocr_rows.extend(
                result.rows
            )

            self.ocr_log_msg(
                f"{result.source_file}: "
                f"COUNTER NG={result.counter_ng or 'OCR CHECK'} "
                f"(ไม่สร้าง Register Row)"
            )

            for warning in result.warnings:
                self.ocr_log_msg(
                    f"{result.source_file}: WARNING: "
                    f"{warning}"
                )

        self.rebuild_ocr_table()

        self.audit.write(
            "OCR_COMPLETE",
            status="OK",
            images=len(self.ocr_results),
            rows=len(self.ocr_rows),
            counter_ng={
                r.source_file: r.counter_ng
                for r in self.ocr_results
            }
        )

    def ocr_failed(
        self,
        error
    ):
        self.btn_ocr_run.setEnabled(True)
        self.btn_ocr_run.setText(
            "Run OCR"
        )
        self.lbl_ocr_progress.setText(
            "OCR ERROR"
        )

        self.audit.write(
            "OCR_FAILED",
            status="ERROR",
            error=error
        )

        QMessageBox.critical(
            self,
            "OCR NG Error",
            error
        )

    def rebuild_ocr_table(self):
        self.tbl_ocr.setRowCount(0)

        di = self.cmb_ocr_doc.currentIndex()
        doc = (
            self.documents[di]
            if 0 <= di < len(self.documents)
            else None
        )

        machines = (
            doc.machines
            if doc else []
        )
        ng_products = (
            doc.ng_products
            if doc else []
        )

        for ocr_row in self.ocr_rows:
            row = self.tbl_ocr.rowCount()
            self.tbl_ocr.insertRow(row)

            chk = QCheckBox()
            chk.setChecked(
                bool(
                    ocr_row.checked_default
                )
            )
            holder = QWidget()
            layout = QHBoxLayout(
                holder
            )
            layout.setContentsMargins(
                0, 0, 0, 0
            )
            layout.setAlignment(
                Qt.AlignCenter
            )
            layout.addWidget(chk)
            self.tbl_ocr.setCellWidget(
                row,
                0,
                holder
            )

            status = QTableWidgetItem(
                "NEW"
            )
            status.setFlags(
                status.flags()
                & ~Qt.ItemIsEditable
            )
            status.setTextAlignment(
                Qt.AlignCenter
            )
            self.tbl_ocr.setItem(
                row,
                1,
                status
            )

            source = QTableWidgetItem(
                ocr_row.source_file
            )
            source.setFlags(
                source.flags()
                & ~Qt.ItemIsEditable
            )
            source.setToolTip(
                ocr_row.source_path
            )
            self.tbl_ocr.setItem(
                row,
                2,
                source
            )

            judge = QTableWidgetItem(
                "Machine Judge"
            )
            judge.setFlags(
                judge.flags()
                & ~Qt.ItemIsEditable
            )
            self.tbl_ocr.setItem(
                row,
                3,
                judge
            )

            message_edit = QLineEdit(
                ocr_row.message
            )
            message_edit.setToolTip(
                "OCR Original: "
                + (
                    ocr_row.ocr_original
                    or ocr_row.parameter
                )
            )
            message_edit.setClearButtonEnabled(
                True
            )
            message_edit.editingFinished.connect(
                self.refresh_existing_ocr_status
            )
            self.tbl_ocr.setCellWidget(
                row,
                4,
                message_edit
            )

            counter_edit = QLineEdit(
                ocr_row.counter
            )
            counter_edit.setPlaceholderText(
                "OCR CHECK"
            )
            counter_edit.setMaximumWidth(
                90
            )
            counter_edit.editingFinished.connect(
                self.refresh_existing_ocr_status
            )
            self.tbl_ocr.setCellWidget(
                row,
                5,
                counter_edit
            )

            cmb_machine = make_searchable(
                QComboBox()
            )
            cmb_machine.addItem(
                "Select Machine",
                None
            )
            for opt in machines:
                cmb_machine.addItem(
                    opt.label,
                    opt
                )
            cmb_machine.setCurrentIndex(-1)
            cmb_machine.setPlaceholderText(
                "พิมพ์ค้นหา Machine"
            )
            self.tbl_ocr.setCellWidget(
                row,
                6,
                cmb_machine
            )

            cmb_ng = make_searchable(
                QComboBox()
            )
            cmb_ng.addItem(
                "Select NG Product",
                None
            )
            for opt in ng_products:
                cmb_ng.addItem(
                    opt.label,
                    opt
                )
            cmb_ng.setCurrentIndex(-1)
            cmb_ng.setPlaceholderText(
                "พิมพ์ค้นหา NG Product"
            )
            self.tbl_ocr.setCellWidget(
                row,
                7,
                cmb_ng
            )

            start_edit = QLineEdit(
                ocr_row.start_time
            )
            self.tbl_ocr.setCellWidget(
                row,
                8,
                start_edit
            )

            stop_edit = QLineEdit(
                ocr_row.stop_time
            )
            self.tbl_ocr.setCellWidget(
                row,
                9,
                stop_edit
            )

            process = make_searchable(
                QComboBox()
            )
            process.addItem(
                "Select Process Found",
                None
            )
            for opt in self.ocr_process_options:
                process.addItem(
                    opt.label,
                    opt
                )
            self.tbl_ocr.setCellWidget(
                row,
                10,
                process
            )

        self.lbl_ocr_files.setText(
            f"{len(self.ocr_files)} images | "
            f"{len(self.ocr_rows)} rows"
        )

        # OCR NG policy: image batches are treated as new input.
        # Do not scan QAC history before register.
        if self.ocr_rows:
            self.ocr_log_msg(
                "OCR NG: duplicate pre-scan disabled "
                "(fast write policy)"
            )

    def _ocr_checkbox(
        self,
        row
    ):
        holder = self.tbl_ocr.cellWidget(
            row,
            0
        )
        if holder is None:
            return None
        return holder.findChild(
            QCheckBox
        )

    def set_all_ocr_checks(
        self,
        checked
    ):
        for row in range(
            self.tbl_ocr.rowCount()
        ):
            chk = self._ocr_checkbox(
                row
            )
            if chk:
                chk.setChecked(
                    checked
                )

    def refresh_existing_ocr_status(self):
        di = self.cmb_ocr_doc.currentIndex()

        if (
            di < 0
            or di >= len(self.documents)
            or not self.ocr_rows
        ):
            return

        if (
            self.ocr_existing_worker
            and self.ocr_existing_worker.isRunning()
        ):
            return

        cfg = self.browser_cfg()
        doc = self.documents[di]

        self.ocr_existing_worker = ExistingAlarmWorker(
            cfg["cdp_url"],
            doc.page_index
        )
        self.ocr_existing_worker.completed.connect(
            self._ocr_existing_loaded
        )
        self.ocr_existing_worker.failed.connect(
            lambda e: self.ocr_log_msg(
                f"Existing QAC warning: {e}"
            )
        )
        self.ocr_existing_worker.start()

    def _ocr_existing_loaded(
        self,
        events
    ):
        model = self.cmb_ocr_model.currentData()
        model_value = str(
            getattr(
                model,
                "value",
                ""
            )
            or ""
        )

        matched = 0

        for row, ocr_row in enumerate(
            self.ocr_rows
        ):
            status = self.tbl_ocr.item(
                row,
                1
            )
            if status is None:
                continue

            message_widget = (
                self.tbl_ocr.cellWidget(
                    row,
                    4
                )
            )
            counter_widget = (
                self.tbl_ocr.cellWidget(
                    row,
                    5
                )
            )

            message = (
                message_widget.text()
                .strip()
                if message_widget else ""
            )
            counter = (
                counter_widget.text()
                .strip()
                if counter_widget else ""
            )

            try:
                expected_desc = (
                    build_description(
                        message,
                        counter
                    )
                    .lower()
                )
            except Exception:
                status.setText(
                    "OCR CHECK"
                )
                continue

            expected_start = (
                self._norm_alarm_clock(
                    ocr_row.start_time
                )
            )

            found = None

            for ev in events or []:
                if str(
                    ev.get(
                        "topic_value"
                    )
                    or ""
                ) != "24216":
                    continue

                if str(
                    ev.get(
                        "category_value"
                    )
                    or ""
                ) != "112":
                    continue

                if (
                    model_value
                    and str(
                        ev.get(
                            "model_value"
                        )
                        or ""
                    ) != model_value
                ):
                    continue

                if (
                    self._norm_alarm_clock(
                        ev.get("start")
                    )
                    != expected_start
                ):
                    continue

                if (
                    " ".join(
                        str(
                            ev.get(
                                "description"
                            )
                            or ""
                        )
                        .lower()
                        .split()
                    )
                    != " ".join(
                        expected_desc.split()
                    )
                ):
                    continue

                found = ev
                break

            if found:
                matched += 1
                status.setText(
                    "EXISTS ✓"
                )
                status.setToolTip(
                    "พบข้อมูลนี้ใน QAC แล้ว | "
                    f"Result ID: "
                    f"{found.get('result_id','')}"
                )
                chk = self._ocr_checkbox(
                    row
                )
                if chk:
                    chk.setChecked(
                        False
                    )
            else:
                status.setText(
                    "NEW"
                )

        self.ocr_log_msg(
            f"Existing QAC Check: "
            f"ลงแล้ว {matched}/"
            f"{len(self.ocr_rows)} OCR rows"
        )

    def collect_ocr_actions(self):
        di = self.cmb_ocr_doc.currentIndex()

        if (
            di < 0
            or di >= len(self.documents)
        ):
            raise ValueError(
                "กรุณาเลือก QAC Document"
            )

        model = self.cmb_ocr_model.currentData()

        if model is None:
            raise ValueError(
                "กรุณาเลือก Model"
            )

        self.ocr_itag_line = (
            self.cmb_ocr_itag_line
            .currentData()
        )

        if self.ocr_itag_line is None:
            raise ValueError(
                "กรุณาเลือก Production Line Found"
            )

        shift = (
            self.cmb_ocr_shift
            .currentData()
        )

        if shift not in (
            1, 2, 3, 4, 5, 6
        ):
            raise ValueError(
                "กรุณาเลือก Shift 1-6"
            )

        actions = []

        for row, ocr_row in enumerate(
            self.ocr_rows
        ):
            chk = self._ocr_checkbox(
                row
            )

            if (
                not chk
                or not chk.isChecked()
            ):
                continue

            message = (
                self.tbl_ocr
                .cellWidget(row, 4)
                .text()
                .strip()
            )
            counter = (
                self.tbl_ocr
                .cellWidget(row, 5)
                .text()
                .strip()
            )

            description = build_description(
                message,
                counter
            )

            machine = (
                self.tbl_ocr
                .cellWidget(row, 6)
                .currentData()
            )
            ng = (
                self.tbl_ocr
                .cellWidget(row, 7)
                .currentData()
            )
            start = (
                self.tbl_ocr
                .cellWidget(row, 8)
                .text()
                .strip()
            )
            # OCR NG only: Start == Time Stop.
            stop = start
            stop_widget = self.tbl_ocr.cellWidget(
                row,
                9
            )
            if stop_widget is not None:
                stop_widget.setText(start)
            process = (
                self.tbl_ocr
                .cellWidget(row, 10)
                .currentData()
            )

            if machine is None:
                raise ValueError(
                    f"Row {row + 1}: "
                    "กรุณาเลือก Machine"
                )

            if ng is None:
                raise ValueError(
                    f"Row {row + 1}: "
                    "กรุณาเลือก NG Product"
                )

            if process is None:
                raise ValueError(
                    f"Row {row + 1}: "
                    "กรุณาเลือก Process Found"
                )

            if not self._valid_alarm_time(
                start
            ):
                raise ValueError(
                    f"Row {row + 1}: "
                    f"Start ไม่ถูกต้อง ({start})"
                )

            if not self._valid_alarm_time(
                stop
            ):
                raise ValueError(
                    f"Row {row + 1}: "
                    f"Time Stop ไม่ถูกต้อง ({stop})"
                )

            actions.append({
                "source_file": (
                    ocr_row.source_file
                ),
                "source_row": row + 1,
                "alarm_code": "OCR",
                "machine_code": "OCR",
                "message": message,
                "ocr_original": (
                    ocr_row.ocr_original
                ),
                "counter": counter,
                "description": description,
                "start": start,
                "stop": stop,
                "model_value": model.value,
                "model_name": model.name,
                "machine_value": machine.value,
                "machine_name": machine.name,
                "ng_value": ng.value,
                "ng_name": ng.name,
                "ng_qty": int(counter),
                "itag_mode": "I-TAG",
                "itag_line_value": (
                    self.ocr_itag_line.value
                ),
                "itag_line_name": (
                    self.ocr_itag_line.name
                ),
                "itag_process_value": (
                    process.value
                ),
                "itag_process_name": (
                    process.name
                ),
                "itag_shift": int(
                    shift
                ),
            })

        if not actions:
            raise ValueError(
                "ไม่มี OCR Row ที่เลือกสำหรับ Register"
            )

        return actions

    def run_ocr_register(self):
        if not self._permission_or_warn(3):
            return

        try:
            actions = self.collect_ocr_actions()
        except Exception as e:
            QMessageBox.warning(
                self,
                "OCR NG Register",
                str(e)
            )
            return

        di = self.cmb_ocr_doc.currentIndex()
        doc = self.documents[di]
        dry = self.chk_ocr_dry.isChecked()

        if not dry:
            answer = QMessageBox.question(
                self,
                "Confirm OCR NG Register",
                (
                    f"กำลังจะ Register จริง "
                    f"{len(actions)} rows\\n"
                    f"Line: {doc.line}\\n"
                    f"Date: {doc.production_date}\\n"
                    "ต้องการดำเนินการต่อหรือไม่?"
                )
            )

            if answer != QMessageBox.Yes:
                return

        cfg = self.browser_cfg()

        self.audit.write(
            "OCR_REGISTER_START",
            status="OK",
            dry_run=dry,
            document=doc.label,
            rows=[
                {
                    "source": a["source_file"],
                    "ocr_original": a["ocr_original"],
                    "message_final": a["message"],
                    "counter": a["counter"],
                    "description": a["description"],
                }
                for a in actions
            ]
        )

        self.btn_ocr_register.setEnabled(
            False
        )
        self.btn_ocr_register.setText(
            "Registering..."
        )
        self.set_ocr_progress(
            0,
            f"เตรียม Register QAC 0/{len(actions)}"
        )

        self.ocr_import_worker = AlarmImportWorker(
            cfg["cdp_url"],
            doc.page_index,
            actions,
            dry,
            duplicate_check=False
        )
        self.ocr_import_worker.progress.connect(
            self.ocr_register_progress
        )
        self.ocr_import_worker.completed.connect(
            lambda: self.ocr_register_completed(
                dry
            )
        )
        self.ocr_import_worker.failed.connect(
            self.ocr_register_failed
        )
        self.ocr_import_worker.start()

    def pause_ocr_register(self):
        if (
            self.ocr_import_worker
            and self.ocr_import_worker.isRunning()
        ):
            self.ocr_import_worker.request_pause()
            self.ocr_log_msg(
                "Pause requested - "
                "จะหยุดก่อน Row ถัดไป"
            )

    def resume_ocr_register(self):
        if (
            self.ocr_import_worker
            and self.ocr_import_worker.isRunning()
        ):
            self.ocr_import_worker.request_resume()
            self.ocr_log_msg(
                "Resume requested"
            )

    def stop_ocr_register(self):
        if (
            self.ocr_import_worker
            and self.ocr_import_worker.isRunning()
        ):
            self.ocr_import_worker.request_stop()
            self.ocr_log_msg(
                "Stop requested - "
                "Row ที่กำลัง Save จะจบก่อนแล้วค่อยหยุด"
            )

    def ocr_register_completed(
        self,
        dry
    ):
        self.btn_ocr_register.setEnabled(
            True
        )
        self.btn_ocr_register.setText(
            "REGISTER OCR TO QAC"
        )
        self.set_ocr_progress(
            100,
            "REGISTER QAC COMPLETE"
        )

        self.audit.write(
            "OCR_REGISTER_COMPLETE",
            status="OK",
            dry_run=dry
        )

        QMessageBox.information(
            self,
            "OCR NG",
            (
                "Dry Run เสร็จแล้ว"
                if dry
                else "OCR NG Register เสร็จแล้ว"
            )
        )

        self.ocr_log_msg(
            "OCR NG COMPLETE: SQLite cache "
            "updated from saved Result"
        )

    def ocr_register_failed(
        self,
        error
    ):
        self.btn_ocr_register.setEnabled(
            True
        )
        self.btn_ocr_register.setText(
            "REGISTER OCR TO QAC"
        )
        self.lbl_ocr_progress.setText(
            "REGISTER QAC ERROR"
        )

        self.audit.write(
            "OCR_REGISTER_FAILED",
            status="ERROR",
            error=error
        )

        self.ocr_log_msg(
            f"OCR REGISTER ERROR: {error}"
        )

        QMessageBox.critical(
            self,
            "OCR NG Register Error",
            error
        )

    def add_alarm_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Alarm Files",
            "",
            "Alarm Files (*.csv *.xlsx *.xlsm);;"
            "CSV (*.csv);;Excel (*.xlsx *.xlsm)"
        )

        if not paths:
            return

        # Avoid adding same exact path twice in one import session.
        for path in paths:
            if path not in self.alarm_files:
                self.alarm_files.append(path)

        self.audit.write(
            "ALARM_FILES_SELECTED",
            files=list(self.alarm_files)
        )

        try:
            self.alarm_rows = load_alarm_files(self.alarm_files)
        except Exception as e:
            QMessageBox.critical(self, "Alarm File", str(e))
            return

        self.rebuild_alarm_table()
        self.alarm_log_msg(
            f"โหลด {len(self.alarm_files)} files | "
            f"{len(self.alarm_rows)} rows"
        )

    def clear_alarm_files(self):
        self.alarm_files = []
        self.alarm_rows = []
        self.tbl_alarm.setRowCount(0)
        self.lbl_alarm_files.setText("0 files | 0 rows")

    @staticmethod
    def _set_combo_by_option_value(combo, value):
        value = str(value or "")
        if not value or combo is None:
            return False
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is not None and str(getattr(data, "value", "")) == value:
                combo.setCurrentIndex(i)
                return True
        return False

    def _alarm_learning_line(self):
        di = self.cmb_alarm_doc.currentIndex() if hasattr(self, "cmb_alarm_doc") else -1
        if 0 <= di < len(self.documents):
            return str(self.documents[di].line or "").strip()
        return ""

    def _alarm_suggestion(self, alarm):
        return self.alarm_learning_store.best(
            self._alarm_learning_line(),
            str(getattr(alarm, "message", "") or "")
        )

    def _alarm_memory_key(self, alarm):
        return self._norm_alarm_text(
            str(getattr(alarm, "message", "") or "")
        )

    @staticmethod
    def _alarm_combo_value(combo):
        if combo is None:
            return ""
        return str(getattr(combo.currentData(), "value", "") or "")

    def _remember_alarm_row_selection(self, row):
        if row < 0 or row >= len(self.alarm_rows):
            return
        key = self._alarm_memory_key(self.alarm_rows[row])
        if not key:
            return
        state = dict(self._alarm_ui_memory.get(key, {}))
        state["machine_value"] = self._alarm_combo_value(
            self.tbl_alarm.cellWidget(row, 3)
        )
        state["ng_value"] = self._alarm_combo_value(
            self.tbl_alarm.cellWidget(row, 4)
        )
        process_value = self._alarm_combo_value(
            self.tbl_alarm.cellWidget(row, 8)
        )
        if process_value or "process_value" not in state:
            state["process_value"] = process_value
        self._alarm_ui_memory[key] = state

    def _restore_alarm_row_selection(self, row, alarm):
        state = self._alarm_ui_memory.get(self._alarm_memory_key(alarm), {})
        self._set_combo_by_option_value(
            self.tbl_alarm.cellWidget(row, 3), state.get("machine_value", "")
        )
        self._set_combo_by_option_value(
            self.tbl_alarm.cellWidget(row, 4), state.get("ng_value", "")
        )
        self._set_combo_by_option_value(
            self.tbl_alarm.cellWidget(row, 8), state.get("process_value", "")
        )

    def _apply_alarm_machine_ng_suggestion(self, row, alarm):
        suggestion = self._alarm_suggestion(alarm)
        if not suggestion:
            return
        machine = self.tbl_alarm.cellWidget(row, 3)
        ng = self.tbl_alarm.cellWidget(row, 4)
        if machine is not None and machine.currentData() is None:
            self._set_combo_by_option_value(machine, suggestion.machine_value)
        if ng is not None and ng.currentData() is None:
            self._set_combo_by_option_value(ng, suggestion.ng_value)
        status = self.tbl_alarm.item(row, 1)
        if status is not None:
            status.setToolTip(
                f"Learned [{suggestion.match_scope}] from {suggestion.count} successful import(s): "
                f"Machine={suggestion.machine_name}, NG={suggestion.ng_name}, "
                f"Process={suggestion.process_name}. You can still change it."
            )

    def _apply_alarm_process_suggestion(self, row):
        if row < 0 or row >= len(self.alarm_rows):
            return
        suggestion = self._alarm_suggestion(self.alarm_rows[row])
        if not suggestion:
            return
        combo = self.tbl_alarm.cellWidget(row, 8)
        if combo is not None and combo.currentData() is None:
            self._set_combo_by_option_value(combo, suggestion.process_value)

    def rebuild_alarm_table(self):
        self.tbl_alarm.setRowCount(0)

        di = self.cmb_alarm_doc.currentIndex()
        doc = (
            self.documents[di]
            if 0 <= di < len(self.documents)
            else None
        )

        machines = doc.machines if doc else []
        ng_products = doc.ng_products if doc else []

        for alarm in self.alarm_rows:
            row = self.tbl_alarm.rowCount()
            self.tbl_alarm.insertRow(row)

            chk = QCheckBox()
            chk.setChecked(True)
            chk.setToolTip(
                f"{alarm.source_file} row {alarm.source_row} | "
                f"Alarm Code {alarm.alarm_code}"
            )
            holder = QWidget()
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setAlignment(Qt.AlignCenter)
            lay.addWidget(chk)
            self.tbl_alarm.setCellWidget(row, 0, holder)

            status_item = QTableWidgetItem("NEW")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            status_item.setTextAlignment(Qt.AlignCenter)
            self.tbl_alarm.setItem(row, 1, status_item)

            item_f = QTableWidgetItem(alarm.machine_code)
            item_f.setFlags(item_f.flags() & ~Qt.ItemIsEditable)
            self.tbl_alarm.setItem(row, 2, item_f)

            cmb_machine = make_searchable(QComboBox())
            cmb_machine.addItem("Select Machine", None)
            for opt in machines:
                cmb_machine.addItem(opt.label, opt)
            cmb_machine.setCurrentIndex(-1)
            cmb_machine.setPlaceholderText("พิมพ์ค้นหา Machine ได้ทันที")
            if cmb_machine.lineEdit():
                cmb_machine.lineEdit().setClearButtonEnabled(True)
            self.tbl_alarm.setCellWidget(row, 3, cmb_machine)

            cmb_ng = make_searchable(QComboBox())
            cmb_ng.addItem("Select NG Product", None)
            for opt in ng_products:
                cmb_ng.addItem(opt.label, opt)
            cmb_ng.setCurrentIndex(-1)
            cmb_ng.setPlaceholderText("พิมพ์ค้นหา NG Product ได้ทันที")
            if cmb_ng.lineEdit():
                cmb_ng.lineEdit().setClearButtonEnabled(True)
            self.tbl_alarm.setCellWidget(row, 4, cmb_ng)

            item_e = QTableWidgetItem(alarm.message)
            item_e.setFlags(item_e.flags() & ~Qt.ItemIsEditable)
            item_e.setToolTip(alarm.description)
            self.tbl_alarm.setItem(row, 5, item_e)

            item_b = QTableWidgetItem(alarm.column_b_time)
            item_b.setFlags(item_b.flags() & ~Qt.ItemIsEditable)
            self.tbl_alarm.setItem(row, 6, item_b)

            stop_edit = QLineEdit(alarm.time_stop)
            stop_edit.setPlaceholderText("HH:MM:SS")
            self.tbl_alarm.setCellWidget(row, 7, stop_edit)

            cmb_process = make_searchable(QComboBox())
            cmb_process.addItem("Select Process Found", None)

            for opt in getattr(
                self,
                "itag_process_options",
                []
            ):
                cmb_process.addItem(opt.label, opt)

            self.tbl_alarm.setCellWidget(
                row,
                8,
                cmb_process
            )

            self._restore_alarm_row_selection(row, alarm)
            self._apply_alarm_machine_ng_suggestion(row, alarm)
            self._apply_alarm_process_suggestion(row)

            cmb_machine.currentIndexChanged.connect(
                lambda _index, table_row=row: self._remember_alarm_row_selection(table_row)
            )
            cmb_ng.currentIndexChanged.connect(
                lambda _index, table_row=row: self._remember_alarm_row_selection(table_row)
            )
            cmb_process.currentIndexChanged.connect(
                lambda _index, table_row=row: self._remember_alarm_row_selection(table_row)
            )

            cmb_action = QComboBox()
            cmb_action.addItem("No Action", "NO_ACTION")
            cmb_action.addItem("Action Taken", "ACTION_TAKEN")
            self.tbl_alarm.setCellWidget(
                row,
                9,
                cmb_action
            )

            action_edit = QLineEdit()
            action_edit.setPlaceholderText(
                "กรอกรายละเอียดการแก้ไข"
            )
            action_edit.setEnabled(False)
            self.tbl_alarm.setCellWidget(
                row,
                10,
                action_edit
            )

            def action_mode_changed(
                _index,
                combo=cmb_action,
                edit=action_edit,
                table_row=row
            ):
                is_action = (
                    combo.currentData()
                    == "ACTION_TAKEN"
                )
                edit.setEnabled(is_action)

                if not is_action:
                    edit.clear()

                status = self.tbl_alarm.item(
                    table_row,
                    1
                )
                if status is not None:
                    status.setText("NEW")
                    status.setToolTip(
                        "Action ถูกแก้ไข กรุณา Import/ตรวจสอบตามข้อมูลล่าสุด"
                    )

            cmb_action.currentIndexChanged.connect(
                action_mode_changed
            )

            action_edit.textChanged.connect(
                lambda _text, table_row=row:
                    self._alarm_action_edited(
                        table_row
                    )
            )

        self.lbl_alarm_files.setText(
            f"{len(self.alarm_files)} files | "
            f"{len(self.alarm_rows)} rows"
        )
        if self.alarm_rows:
            self.refresh_existing_alarm_status()

    def _alarm_checkbox(self, row):
        holder = self.tbl_alarm.cellWidget(row, 0)
        if holder is None:
            return None
        return holder.findChild(QCheckBox)

    def set_all_alarm_checks(self, checked):
        for row in range(self.tbl_alarm.rowCount()):
            chk = self._alarm_checkbox(row)
            if chk:
                chk.setChecked(checked)

    @staticmethod
    def _valid_alarm_time(value):
        value = value.strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                datetime.strptime(value, fmt)
                return True
            except ValueError:
                pass
        return False

    @staticmethod
    def _norm_alarm_clock(value):
        raw = str(value or "").strip().upper()
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
            try:
                return datetime.strptime(raw, fmt).strftime("%H:%M")
            except ValueError:
                pass
        return raw.lower()

    @staticmethod
    def _norm_alarm_text(value):
        return " ".join(str(value or "").strip().lower().split())

    def _alarm_action_edited(self, row):
        status = self.tbl_alarm.item(
            row,
            1
        )

        if status is not None:
            status.setText("NEW")
            status.setToolTip(
                "Action ถูกแก้ไข กรุณา Import/ตรวจสอบตามข้อมูลล่าสุด"
            )

    def _alarm_description_for_row(
        self,
        row,
        alarm
    ):
        action_combo = self.tbl_alarm.cellWidget(
            row,
            9
        )
        action_edit = self.tbl_alarm.cellWidget(
            row,
            10
        )

        action_mode = (
            action_combo.currentData()
            if action_combo is not None
            else "NO_ACTION"
        )

        if action_mode == "ACTION_TAKEN":
            detail = (
                action_edit.text().strip()
                if action_edit is not None
                else ""
            )

            if not detail:
                raise ValueError(
                    f"Row {row + 1} ({alarm.machine_code}): "
                    "เลือก Action Taken แล้ว กรุณากรอก Action Detail"
                )

            return (
                f"Machine Alarm {alarm.message} "
                f"Action: {detail}"
            )

        return (
            f"Machine Alarm {alarm.message} "
            "No Action Monitor Run"
        )

    def refresh_existing_alarm_status(self):
        di = self.cmb_alarm_doc.currentIndex()
        if di < 0 or di >= len(self.documents) or not self.alarm_rows:
            return
        if self.existing_alarm_worker and self.existing_alarm_worker.isRunning():
            return
        cfg = self.browser_cfg()
        doc = self.documents[di]
        self.existing_alarm_worker = ExistingAlarmWorker(cfg["cdp_url"], doc.page_index)
        self.existing_alarm_worker.progress.connect(
            self.alarm_log_msg
        )
        self.existing_alarm_worker.completed.connect(
            self._existing_alarm_loaded
        )
        self.existing_alarm_worker.failed.connect(
            lambda e: self.alarm_log_msg(f"Existing QAC scan warning: {e}")
        )
        self.existing_alarm_worker.start()

    def _existing_alarm_loaded(self, events):
        self.existing_alarm_events = list(events or [])
        model = self.cmb_alarm_model.currentData()
        model_value = str(getattr(model, "value", "") or "")
        matched = 0
        for row, alarm in enumerate(self.alarm_rows):
            status = self.tbl_alarm.item(row, 1)
            if status is None:
                continue
            expected_start = self._norm_alarm_clock(
                alarm.column_b_time
            )
            stop_widget = self.tbl_alarm.cellWidget(
                row,
                7
            )
            expected_stop = self._norm_alarm_clock(
                stop_widget.text()
                if stop_widget is not None
                else ""
            )
            try:
                current_description = (
                    self._alarm_description_for_row(
                        row,
                        alarm
                    )
                )
            except ValueError:
                current_description = ""

            expected_desc = self._norm_alarm_text(
                current_description
            )

            found = None

            for ev in self.existing_alarm_events:
                topic_ok = (
                    str(ev.get("topic_value") or "")
                    == "24216"
                    or self._norm_alarm_text(
                        ev.get("topic_label")
                    ) == "trouble"
                )
                if not topic_ok:
                    continue

                category_ok = (
                    str(ev.get("category_value") or "")
                    == "112"
                    or self._norm_alarm_text(
                        ev.get("category_label")
                    ) == "machine"
                )
                if not category_ok:
                    continue

                if (
                    model_value
                    and str(
                        ev.get("model_value")
                        or ""
                    ) != model_value
                ):
                    continue

                if (
                    self._norm_alarm_clock(
                        ev.get("start")
                    ) != expected_start
                ):
                    continue

                if (
                    expected_stop
                    and self._norm_alarm_clock(
                        ev.get("end")
                    ) != expected_stop
                ):
                    continue

                if not expected_desc:
                    continue

                if (
                    self._norm_alarm_text(
                        ev.get("description")
                    ) != expected_desc
                ):
                    continue

                found = ev
                break
            if found:
                matched += 1
                status.setText("EXISTS ✓")
                status.setToolTip(f"ลงใน QAC แล้ว | Result ID: {found.get('result_id','')}")
                chk = self._alarm_checkbox(row)
                if chk:
                    chk.setChecked(False)
                    chk.setToolTip("พบข้อมูลเดิม จึงยกเลิก Check อัตโนมัติ")
            else:
                status.setText("NEW")
                status.setToolTip("ยังไม่พบข้อมูลตรงกันใน QAC")
        detailed = sum(
            1
            for event in self.existing_alarm_events
            if str(
                event.get("description", "")
                or ""
            ).strip()
        )

        self.alarm_log_msg(
            f"Existing QAC Check: ลงแล้ว "
            f"{matched}/{len(self.alarm_rows)} rows "
            f"| detailed={detailed}/"
            f"{len(self.existing_alarm_events)}"
        )

    def collect_alarm_actions(self):
        di = self.cmb_alarm_doc.currentIndex()
        mi = self.cmb_alarm_model.currentIndex()

        if di < 0 or di >= len(self.documents):
            raise ValueError("กรุณาเลือก QAC Document")
        if mi < 0:
            raise ValueError("กรุณาเลือก Model")

        model = self.cmb_alarm_model.currentData()
        if model is None:
            raise ValueError("กรุณาเลือก Model")

        self.current_itag_line = self.cmb_itag_line.currentData()
        itag_shift = self.cmb_itag_shift.currentData()
        if itag_shift not in (1, 2, 3, 4, 5, 6):
            raise ValueError("กรุณาเลือก Shift 1-6")

        actions = []

        for row, alarm in enumerate(self.alarm_rows):
            chk = self._alarm_checkbox(row)
            if not chk or not chk.isChecked():
                continue

            itag_mode = "I-TAG"
            machine = self.tbl_alarm.cellWidget(row, 3).currentData()
            ng = self.tbl_alarm.cellWidget(row, 4).currentData()
            stop = self.tbl_alarm.cellWidget(row, 7).text().strip()
            itag_process = self.tbl_alarm.cellWidget(row, 8).currentData()
            description = self._alarm_description_for_row(
                row,
                alarm
            )

            if machine is None:
                raise ValueError(
                    f"Row {row + 1} ({alarm.machine_code}): "
                    f"กรุณาเลือก Machine"
                )

            if ng is None:
                raise ValueError(
                    f"Row {row + 1} ({alarm.machine_code}): "
                    f"กรุณาเลือก NG Product"
                )

            if self.current_itag_line is None:
                raise ValueError(
                    f"Row {row + 1}: กรุณาเลือก Production Line Found"
                )
            if itag_process is None:
                raise ValueError(
                    f"Row {row + 1} ({alarm.machine_code}): "
                    f"กรุณาเลือก Process Found สำหรับ I-TAG"
                )

            if not self._valid_alarm_time(alarm.column_b_time):
                raise ValueError(
                    f"Row {row + 1}: Column B time ไม่ถูกต้อง "
                    f"({alarm.column_b_time})"
                )

            if not self._valid_alarm_time(stop):
                raise ValueError(
                    f"Row {row + 1}: Time Stop ไม่ถูกต้อง ({stop})"
                )

            actions.append({
                "source_file": alarm.source_file,
                "source_row": alarm.source_row,
                "alarm_code": alarm.alarm_code,
                "machine_code": alarm.machine_code,
                "message": alarm.message,
                "description": description,
                "start": alarm.column_b_time,
                "stop": stop,
                "model_value": model.value,
                "model_name": model.name,
                "machine_value": machine.value,
                "machine_name": machine.name,
                "ng_value": ng.value,
                "ng_name": ng.name,
                "ng_qty": 1,
                "itag_mode": "I-TAG",
                "itag_line_value": self.current_itag_line.value if self.current_itag_line else "",
                "itag_line_name": self.current_itag_line.name if self.current_itag_line else "",
                "itag_process_value": itag_process.value if itag_process else "",
                "itag_process_name": itag_process.name if itag_process else "",
                "itag_shift": int(itag_shift),
            })

        if not actions:
            raise ValueError("ไม่มี Row ที่เลือกสำหรับ Import")

        return actions

    def run_alarm_import(self):
        if not self._ensure_local_action('Alarm Import'):
            return
        if not self._permission_or_warn(2):
            return

        try:
            actions = self.collect_alarm_actions()
        except Exception as e:
            QMessageBox.warning(self, "Alarm Import", str(e))
            return

        di = self.cmb_alarm_doc.currentIndex()
        doc = self.documents[di]
        dry = False

        answer = QMessageBox.question(
            self,
            "Confirm Alarm Import",
            f"กำลังจะบันทึก Trouble จริง {len(actions)} rows\n"
            f"Line: {doc.line}\n"
            f"Date: {doc.production_date}\n"
            f"ต้องการดำเนินการต่อหรือไม่?"
        )
        if answer != QMessageBox.Yes:
            return

        cfg = self.browser_cfg()

        self.audit.write(
            "ALARM_IMPORT_START",
            dry_run=dry,
            document=doc.label,
            row_count=len(actions),
            files=list(self.alarm_files)
        )

        self.btn_alarm_import.setEnabled(False)
        self.btn_alarm_import.setText("Importing...")

        # Keep exactly what was submitted; statistics are recorded only after
        # the QAC worker reports successful completion.
        self._pending_alarm_learning_actions = [dict(a) for a in actions]

        self.alarm_worker = AlarmImportWorker(
            cfg["cdp_url"],
            doc.page_index,
            actions,
            dry
        )
        self.alarm_worker.progress.connect(self.alarm_log_msg)
        self.alarm_worker.completed.connect(
            lambda: self.alarm_import_completed(dry)
        )
        self.alarm_worker.failed.connect(
            self.alarm_import_failed
        )
        self.alarm_worker.start()

    def pause_alarm_import(self):
        if self.alarm_worker and self.alarm_worker.isRunning():
            self.alarm_worker.request_pause()
            self.alarm_log_msg("Pause requested - จะหยุดก่อน Row ถัดไป")

    def resume_alarm_import(self):
        if self.alarm_worker and self.alarm_worker.isRunning():
            self.alarm_worker.request_resume()
            self.alarm_log_msg("Resume requested")

    def stop_alarm_import(self):
        if self.alarm_worker and self.alarm_worker.isRunning():
            self.alarm_worker.request_stop()
            self.alarm_log_msg("Stop requested - Row ที่กำลัง Save จะจบก่อนแล้วค่อยหยุด")

    def alarm_import_completed(self, dry):
        if not dry:
            line = self._alarm_learning_line()
            for action in list(getattr(self, "_pending_alarm_learning_actions", []) or []):
                self.alarm_learning_store.record_success(
                    line,
                    action.get("message", ""),
                    machine_value=action.get("machine_value", ""),
                    machine_name=action.get("machine_name", ""),
                    ng_value=action.get("ng_value", ""),
                    ng_name=action.get("ng_name", ""),
                    process_value=action.get("itag_process_value", ""),
                    process_name=action.get("itag_process_name", ""),
                )
            if getattr(self, "_pending_alarm_learning_actions", None):
                self.alarm_log_msg(
                    f"ALARM LEARNING | recorded {len(self._pending_alarm_learning_actions)} successful mapping(s)"
                )
        self._pending_alarm_learning_actions = []
        self.audit.write(
            "ALARM_IMPORT_COMPLETE",
            status="OK",
            dry_run=dry
        )
        self.btn_alarm_import.setEnabled(True)
        self.btn_alarm_import.setText("IMPORT TO QAC")

        QMessageBox.information(
            self,
            "Alarm Import",
            "Dry Run เสร็จแล้ว"
            if dry else
            "Alarm Import เสร็จแล้ว"
        )

    def alarm_import_failed(self, error):
        self._pending_alarm_learning_actions = []
        self.audit.write(
            "ALARM_IMPORT_FAILED",
            status="ERROR",
            error=error
        )
        self.btn_alarm_import.setEnabled(True)
        self.btn_alarm_import.setText("IMPORT TO QAC")
        self.alarm_log_msg(f"IMPORT ERROR: {error}")

        QMessageBox.critical(
            self,
            "Alarm Import Error",
            error
        )

    def _sync_alarm_learning_on_close(self):
        """Upload only alarm_learning.db to the central folder on normal shutdown."""
        try:
            access_cfg = (self.settings or {}).get("access_control", {}) or {}
            central_access = (
                getattr(getattr(self, "access_record", None), "source_path", "")
                or access_cfg.get("config_path", "")
            )
            record = getattr(self, "access_record", None)
            machine_name = getattr(record, "name", "") or os.environ.get("COMPUTERNAME", "unknown")
            machine_ip = getattr(record, "ip", "") or "unknown"
            result = upload_alarm_learning_snapshot(
                central_access,
                machine_name=machine_name,
                machine_ip=machine_ip,
                local_db_path=getattr(self.alarm_learning_store, "db_path", None),
            )
            if result.ok:
                self.audit.write(
                    "ALARM_LEARNING_UPLOAD",
                    status="SKIP" if result.skipped else "OK",
                    central_path=result.central_path,
                    detail=result.error,
                )
            else:
                self.audit.write(
                    "ALARM_LEARNING_UPLOAD",
                    status="ERROR",
                    central_path=result.central_path,
                    error=result.error,
                )
            return result
        except Exception as e:
            try:
                self.audit.write("ALARM_LEARNING_UPLOAD", status="ERROR", error=str(e))
            except Exception:
                pass
            return None

    def closeEvent(self, event):
        self.audit.write(
            "PROGRAM_CLOSE",
            status="OK"
        )

        if (
            self.register_worker
            and self.register_worker.isRunning()
        ):
            self.register_worker.request_stop()

        if (
            self.alarm_worker
            and self.alarm_worker.isRunning()
        ):
            self.alarm_worker.request_stop()

        if (
            self.ocr_import_worker
            and self.ocr_import_worker.isRunning()
        ):
            self.ocr_import_worker.request_stop()

        if (
            self.production_worker
            and self.production_worker.isRunning()
        ):
            self.production_worker.request_stop()

        if (
            self.html_collector_worker
            and self.html_collector_worker.isRunning()
        ):
            self.html_collector_worker.request_stop()

        # Local-first policy: only Alarm Learning is uploaded centrally on normal close.
        # qac_cache.db and hourly_validation.db always remain local.
        self._sync_alarm_learning_on_close()

        event.accept()


if __name__ == "__main__":
    set_windows_app_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(
        QIcon(str(resource_path("Auto.ico")))
    )
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
