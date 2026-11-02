"""Self-contained three-tab Electrode Issue / Return user interface."""
import csv
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QTabWidget,
    QComboBox,QSpinBox,QTableWidget,QTableWidgetItem,QMessageBox,QFormLayout,QGroupBox,QInputDialog,QCheckBox)
from .electrode_issue_return import IssueReturnStore,ElectrodeLedgerError

class ElectrodeIssueReturnPage(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.store=IssueReturnStore(db_path)
        self.current_scan=None
        self.admin_open=False
        layout=QVBoxLayout(self)
        title=QLabel('Electrode Control — Scan to Issue / Return')
        title.setStyleSheet('font-size:19px;font-weight:700')
        layout.addWidget(title)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)
        self._build_scan();self._build_history();self._build_admin()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.refresh()

    def _build_scan(self):
        p=QWidget();l=QVBoxLayout(p)
        l.addWidget(QLabel('สแกนครั้งแรก = เบิก   •   สแกนครั้งที่สอง (ยังเบิกค้าง) = คืน'))
        self.barcode=QLineEdit();self.barcode.setPlaceholderText('สแกน Electrode No. เช่น 749C-03250225-R1')
        self.barcode.setMinimumHeight(45);self.barcode.returnPressed.connect(self.check_barcode)
        l.addWidget(self.barcode)
        b=QPushButton('ตรวจสอบ Barcode');b.clicked.connect(self.check_barcode);l.addWidget(b)
        self.scan_status=QLabel('พร้อมสแกน');l.addWidget(self.scan_status)
        self.issue_group=QGroupBox('ISSUE — เลือกตำแหน่งที่อนุญาต');f=QFormLayout(self.issue_group)
        self.destination=QComboBox();f.addRow('Machine / Station / Position',self.destination)
        self.issue_button=QPushButton('บันทึกการเบิก (สำหรับกรณีหลายตำแหน่ง)');self.issue_button.clicked.connect(self.issue);f.addRow(self.issue_button)
        l.addWidget(self.issue_group)
        self.return_group=QGroupBox('RETURN — กรอกจำนวน Shot ที่ใช้จริง');f=QFormLayout(self.return_group)
        self.target_label=QLabel('-');f.addRow('Target ณ วันเบิก',self.target_label)
        self.final_counter=QSpinBox();self.final_counter.setRange(0,2_000_000_000);f.addRow('Final Counter (Used Shots)',self.final_counter)
        self.reason=QLineEdit();self.reason.setPlaceholderText('ระบุสาเหตุหากต่ำกว่า Target');f.addRow('Return Reason',self.reason)
        self.return_button=QPushButton('ยืนยันคืน Electrode');self.return_button.clicked.connect(self.return_item);f.addRow(self.return_button)
        l.addWidget(self.return_group);l.addStretch()
        self.issue_group.hide();self.return_group.hide()
        self.tabs.addTab(p,'1. เบิก / คืน')

    def _build_history(self):
        p=QWidget();l=QVBoxLayout(p)
        h=QHBoxLayout();self.history_search=QLineEdit();self.history_search.setPlaceholderText('Barcode / Base No. / Machine')
        self.history_search.returnPressed.connect(self.refresh_history)
        h.addWidget(self.history_search)
        export=QPushButton('Export CSV');export.clicked.connect(self.export_history);h.addWidget(export)
        b=QPushButton('ค้นหา / Refresh');b.clicked.connect(self.refresh_history);h.addWidget(b);l.addLayout(h)
        self.history_table=QTableWidget(0,9)
        self.history_table.setHorizontalHeaderLabels(['Barcode','Line','Machine','Station','Status','Target at Issue','Used Shots','Reason','Issued At'])
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.history_table)
        self.sync_label=QLabel('Local SQLite — Pending Sync');l.addWidget(self.sync_label)
        self.tabs.addTab(p,'2. ประวัติ')

    def _build_admin(self):
        p=QWidget();l=QVBoxLayout(p)
        self.admin_lock=QLabel('Admin PIN required — ไม่มีสิทธิ์แก้ Master จนกว่าจะปลดล็อก');l.addWidget(self.admin_lock)
        unlock=QPushButton('ปลดล็อก Admin');unlock.clicked.connect(self.unlock);l.addWidget(unlock)
        self.admin_form=QGroupBox('Electrode Master & Machine Mapping');f=QFormLayout(self.admin_form)
        self.master_code=QLineEdit();self.master_code.setPlaceholderText('Electrode code เช่น 749C')
        self.master_target=QSpinBox();self.master_target.setRange(1,2_000_000_000);self.master_target.setValue(60000)
        self.master_line=QLineEdit();self.master_machine=QLineEdit();self.master_station=QLineEdit();self.master_position=QLineEdit()
        for name,w in [('Electrode Code',self.master_code),('Target Shot',self.master_target),('Line',self.master_line),('Machine',self.master_machine),('Station',self.master_station),('Position',self.master_position)]:f.addRow(name,w)
        b=QPushButton('บันทึก Target / Mapping');b.clicked.connect(self.save_master);f.addRow(b)
        l.addWidget(self.admin_form)
        self.interlock_checkbox=QCheckBox('เปิด Interlock: ต้องพบประวัติ RETURN ของ Original / -R ก่อนหน้า')
        self.interlock_checkbox.setToolTip('ปิดได้ชั่วคราวเพื่อบันทึก Regrind ที่ไม่มีประวัติเก่า ไม่ยกเลิกการตรวจ Barcode ซ้ำหรือการเบิกค้าง')
        self.interlock_checkbox.toggled.connect(self._save_interlock)
        f.addRow(self.interlock_checkbox)
        l.addWidget(QLabel('Master / Mapping ที่บันทึกไว้ (อ่านอย่างเดียว)'))
        self.admin_table=QTableWidget(0,7)
        self.admin_table.setHorizontalHeaderLabels(['Code','Target','Line','Machine','Station','Position','Active'])
        self.admin_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.admin_table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.admin_table)
        l.addWidget(QLabel('Target ใหม่มีผลเฉพาะ ISSUE ใหม่; รอบเบิกเก่าเก็บ target_shots_at_issue ถาวร'))
        l.addWidget(QLabel('Multi-PC: เก็บ Pending Outbox ใน SQLite เครื่องนี้เท่านั้น — ต้องตั้ง Central Sync Service ก่อนแชร์สถานะข้ามเครื่อง'))
        self.admin_form.setEnabled(False)
        self.tabs.addTab(p,'3. Admin Settings')

    def _lock_admin(self):
        self.admin_open=False
        self.admin_form.setEnabled(False)
        self.admin_lock.setText('Admin PIN required — ล็อกอัตโนมัติเมื่อออกจากหน้านี้')
        self._clear_master_form()

    def _tab_changed(self, index):
        if index!=2:self._lock_admin()
        if index==1:self.refresh_history()
        if index==2:self._refresh_admin_table()

    def hideEvent(self, event):
        self._lock_admin()
        super().hideEvent(event)

    def _clear_master_form(self):
        for field in (self.master_code,self.master_line,self.master_machine,self.master_station,self.master_position):field.clear()
        self.master_target.setValue(self.master_target.minimum())

    def _refresh_admin_table(self):
        rows=self.store.master_summary()
        self.admin_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            for j,v in enumerate([r['code'],r['target_shots'],r['line'],r['machine'],r['station'],r['position'],r['active']]):
                self.admin_table.setItem(i,j,QTableWidgetItem(str(v)))
        self.interlock_checkbox.blockSignals(True)
        self.interlock_checkbox.setChecked(self.store.regrind_interlock_enabled())
        self.interlock_checkbox.blockSignals(False)

    def _save_interlock(self, enabled):
        if not self.admin_open:return
        try:self.store.set_regrind_interlock(enabled)
        except Exception as exc:QMessageBox.warning(self,'Interlock',str(exc))

    def unlock(self):
        pin,ok=QInputDialog.getText(self,'Admin','Admin PIN',QLineEdit.Password)
        if not ok:return
        # Local UI compatibility only; production deployment must move admin authorization server-side.
        if pin!='12338':
            QMessageBox.warning(self,'Admin','PIN ไม่ถูกต้อง');return
        self.admin_open=True;self.admin_form.setEnabled(True);self.admin_lock.setText('Admin unlocked (local only)');self._refresh_admin_table()

    def save_master(self):
        if not self.admin_open:return
        try:
            self.store.save_master_mapping(self.master_code.text(),self.master_target.value(),self.master_line.text(),self.master_machine.text(),self.master_station.text(),self.master_position.text())
            self._refresh_admin_table()
            self._clear_master_form()
            QMessageBox.information(self,'Master','บันทึก Master และ Mapping สำเร็จ')
        except Exception as exc:QMessageBox.warning(self,'Master',str(exc))

    def check_barcode(self):
        self.current_scan=None;self.issue_group.hide();self.return_group.hide()
        try:
            result=self.store.scan(self.barcode.text())
            self.current_scan=result
            if result['action']=='ISSUE':
                self.destination.clear()
                for d in result['options']:
                    name=' / '.join(filter(None,[d['line'],d['machine'],d['station'],d['position']]))
                    self.destination.addItem(f'{name} — Target {d["target_shots"]:,}',d['id'])
                self.scan_status.setText(f'ISSUE | {result["barcode"]} | {len(result["options"])} mapped position(s)')
                if len(result['options'])==1:
                    # Scanners send Enter: persist immediately only for an unambiguous mapping.
                    self._issue_selected()
                else:
                    self.destination.setCurrentIndex(-1)  # No implicit first-machine choice.
                    self.issue_group.show()
                    self.scan_status.setText('เลือกเครื่อง / Station ที่ต้องการก่อนบันทึก: '+result['barcode'])
            else:
                old=result['cycle'];self.target_label.setText(f'{old["target_shots_at_issue"]:,} Shots')
                self.final_counter.setValue(0);self.reason.clear();self.return_group.show()
                self.scan_status.setText('RETURN | '+old['barcode']+' | '+old['machine']+' / '+old['station'])
        except Exception as exc:
            self.scan_status.setText('ตรวจสอบไม่ได้: '+str(exc))
            QMessageBox.warning(self,'Electrode Scan',str(exc))

    def issue(self):
        # Multiple destinations require a deliberate selection but no redundant confirm dialog.
        self._issue_selected()

    def _issue_selected(self):
        if not self.current_scan or self.current_scan['action']!='ISSUE':return
        no=self.current_scan['barcode']
        try:
            destination=self.destination.currentData()
            if destination is None:raise ElectrodeLedgerError('กรุณาเลือก Machine / Station')
            self.store.issue(no,destination)
            self.scan_status.setText('ISSUED | '+no+' | Saved to local SQLite / Pending central sync')
            self.issue_group.hide();self.current_scan=None;self.barcode.clear();self.barcode.setFocus();self.refresh_history()
        except Exception as exc:
            self.scan_status.setText('ISSUE FAILED | '+str(exc))
            QMessageBox.warning(self,'Issue',str(exc))

    def return_item(self):
        if not self.current_scan or self.current_scan['action']!='RETURN':return
        old=self.current_scan['cycle'];shot=self.final_counter.value()
        if shot<old['target_shots_at_issue'] and not self.reason.text().strip():
            QMessageBox.warning(self,'Return','คืนก่อน Target กรุณาระบุเหตุผล');return
        if QMessageBox.question(self,'Confirm RETURN',f'คืน {old["barcode"]}\nUsed Shots: {shot:,}\nTarget at issue: {old["target_shots_at_issue"]:,} ?')!=QMessageBox.Yes:return
        try:
            reason=self.store.return_electrode(old['barcode'],shot,self.reason.text())
            self.scan_status.setText('RETURNED | '+old['barcode']+' | '+reason+' | Pending central sync')
            self.return_group.hide();self.current_scan=None;self.barcode.clear();self.barcode.setFocus();self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,'Return',str(exc))

    def refresh_history(self):
        rows=self.store.history(self.history_search.text())
        self.history_table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            vals=[r['barcode'],r['line'],r['machine'],r['station'],r['state'],r['target_shots_at_issue'],r['final_counter'] if r['final_counter'] is not None else '',r['return_reason'] or '',r['issued_at']]
            for j,value in enumerate(vals):self.history_table.setItem(i,j,QTableWidgetItem(str(value)))
        self.sync_label.setText(f'Local SQLite | {self.store.pending_count()} event(s) pending sync — not yet shared across PCs')

    def export_history(self):
        from PySide6.QtWidgets import QFileDialog
        path,_=QFileDialog.getSaveFileName(self,'Export Electrode History','electrode_issue_return.csv','CSV (*.csv)')
        if not path:return
        rows=self.store.history(self.history_search.text())
        try:
            with open(path,'w',newline='',encoding='utf-8-sig') as file:
                writer=csv.DictWriter(file,fieldnames=['id','barcode','base_barcode','regrind','code','line','machine','station','position','target_shots_at_issue','issued_at','returned_at','final_counter','return_reason','state'])
                writer.writeheader()
                for row in rows:writer.writerow({k:row.get(k) for k in writer.fieldnames})
            QMessageBox.information(self,'Export',f'Exported {len(rows)} records')
        except Exception as exc:QMessageBox.warning(self,'Export',str(exc))

    def refresh(self):self.refresh_history()
