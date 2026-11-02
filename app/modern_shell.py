"""Presentation-only PySide6 shell. Does not access QAC or start workers."""
from datetime import datetime
from .build_info import DISPLAY_VERSION, BUILD_DATE, RELEASE_CHANNEL
from pathlib import Path
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QGridLayout, QFrame, QStackedWidget,
                               QScrollArea, QSizePolicy, QDialog)

NAV = [(0, 'Auto Register', '▣'), (1, 'Alarm Import', '◫'),
       (2, 'OCR NG Import', '▧'), (3, 'Production Output', '▤'),
       (4, 'Daily Document', '▱'), (5, 'Sample Register', '◇'),
       (6, 'Electrode Control', '◈'), (7, 'Settings', '⚙')]

STYLE = """
QWidget#appShell { background:#F2F6FC; color:#14294A; font-family:'Segoe UI','Tahoma'; font-size:12px; }
QFrame#sidebar { background:#152B4E; border:none; }
QLabel#brand { color:white; font-size:21px; font-weight:800; }
QLabel#brandSub, QLabel#sideFooter { color:#A9BFDC; font-size:11px; }
QPushButton#aboutDeveloper { background:transparent; border:0; color:#C5D8F0; font-size:11px; text-align:left; padding:4px 0; }
QPushButton#aboutDeveloper:hover { color:white; text-decoration:underline; }
QPushButton[role="nav"] { background:transparent; text-align:left; border:0; border-radius:11px; color:#D5E4F8; padding:12px 13px; font-size:13px; }
QPushButton[role="nav"]:hover { background:#28466F; }
QPushButton[role="nav"]:checked { background:#3270D8; color:white; font-weight:700; }
QPushButton[role="nav"]:disabled { color:#6B83A1; }
QFrame[role="card"] { border:1px solid #E1E8F3; background:white; border-radius:14px; }
QLabel[role="muted"] { color:#60718C; }
QLabel[role="metric"] { color:#162C50; font-size:22px; font-weight:800; }
QLabel[role="section"] { font-size:16px; font-weight:750; color:#162D53; }
QLabel#heroTitle { color:#FFFFFF; font-size:31px; font-weight:800; }
QLabel#heroSub { color:#E5F1FF; font-size:14px; }
QFrame#hero { background-color:#183F77; border-radius:16px; }
QWidget#dashboardBody { background-color:#F2F6FC; }
QPushButton[role="tile"] { background:white; border:1px solid #DCE5F0; border-radius:13px; color:#183660; font-size:14px; text-align:left; padding:18px; font-weight:700; }
QPushButton[role="tile"]:hover { background:#EAF2FE; border-color:#8AB5F7; }
QPushButton[role="tile"]:disabled { color:#99A9BD; background:#F5F7FA; }
QWidget#workspace QGroupBox { background:white; border:1px solid #DDE6F1; border-radius:10px; margin-top:12px; padding:12px; font-weight:600; }
QWidget#workspace QGroupBox::title { subcontrol-origin:margin; left:15px; padding:0 5px; color:#204776; }
QWidget#workspace QPushButton { border:1px solid #CFDAEA; border-radius:7px; padding:7px 11px; background:#F7FAFE; color:#183A69; }
QWidget#workspace QPushButton:hover { background:#E6F1FF; }
QWidget#workspace QPushButton:disabled { color:#9BA7B8; }
QWidget#workspace QLineEdit, QWidget#workspace QComboBox, QWidget#workspace QDateEdit, QWidget#workspace QSpinBox { border:1px solid #CBD7E7; border-radius:6px; padding:5px; background:white; color:#1C3457; min-height:21px; }
QWidget#workspace QTableWidget, QWidget#workspace QTextEdit { border:1px solid #DCE5F0; border-radius:7px; background:white; color:#233750; alternate-background-color:#F5F8FC; }
QWidget#workspace QHeaderView::section { background:#EAF1FB; color:#28496F; border:0; border-bottom:1px solid #D3DFEC; padding:7px; font-weight:600; }
QWidget#workspace QTabWidget::pane { border:1px solid #DDE6F1; background:white; border-radius:9px; }
QWidget#workspace QTabBar::tab { background:#E9EFF7; color:#476486; padding:9px 15px; margin:2px; border-radius:7px; }
QWidget#workspace QTabBar::tab:selected { background:#2D6BCE; color:white; }
QFrame#topbar { background:white; border-bottom:1px solid #E0E9F3; }
QLabel#topTitle { color:#19345A; font-size:19px; font-weight:700; }
QLabel#health { background:#FFF5E3; color:#8B5B13; border-radius:9px; padding:7px 12px; }
"""

def label(text, role=None):
    w = QLabel(text)
    if role: w.setProperty('role', role)
    w.setWordWrap(True)
    return w

def card(title, message):
    c=QFrame(); c.setProperty('role','card')
    v=QVBoxLayout(c); v.setContentsMargins(18,15,18,15); v.setSpacing(9)
    v.addWidget(label(title,'section')); v.addWidget(label(message,'muted')); v.addStretch()
    return c

class ModernShell(QWidget):
    def __init__(self, tabs, on_navigate, access_checker, parent=None, before_navigate=None):
        super().__init__(parent)
        self.setObjectName('appShell')
        self.tabs=tabs; self.on_navigate=on_navigate; self.access_checker=access_checker; self.before_navigate=before_navigate
        self.setStyleSheet(STYLE)
        outer=QHBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        sidebar=QFrame(); sidebar.setObjectName('sidebar'); sidebar.setMinimumWidth(180)
        side=QVBoxLayout(sidebar); side.setContentsMargins(14,24,14,16); side.setSpacing(5)
        icon_path=Path(__file__).resolve().parent.parent / 'Auto.png'
        if icon_path.is_file():
            icon_label=QLabel();icon_label.setPixmap(QPixmap(str(icon_path)).scaled(48,48,Qt.KeepAspectRatio,Qt.SmoothTransformation))
            side.addWidget(icon_label)
        side.addWidget(label('QAC Auto Register','brand'))
        side.itemAt(side.count()-1).widget().setObjectName('brand')
        subtitle=label('Quality Assurance Control'); subtitle.setObjectName('brandSub'); side.addWidget(subtitle)
        side.addSpacing(25)
        self.buttons={}
        home=QPushButton('⌂    Home'); self._nav_style(home); home.clicked.connect(self.show_home); side.addWidget(home); self.buttons[-1]=home
        for index,name,icon in NAV:
            if index >= tabs.count(): continue
            b=QPushButton(f'{icon}    {name}'); self._nav_style(b)
            b.setEnabled(bool(access_checker(index)))
            b.clicked.connect(lambda _checked=False, i=index: self.navigate(i))
            side.addWidget(b); self.buttons[index]=b
            if index==6: side.addSpacing(16)
        side.addStretch()
        footer=label(f'QAC Auto Register  •  Desktop\n{DISPLAY_VERSION}\nBuild {BUILD_DATE}  •  {RELEASE_CHANNEL}'); footer.setObjectName('sideFooter'); side.addWidget(footer)
        developer=QPushButton('Developed by OMBiz™  ·  About'); developer.setObjectName('aboutDeveloper')
        developer.clicked.connect(self.show_about_developer); side.addWidget(developer)
        from PySide6.QtWidgets import QSplitter
        self.workspace_splitter=QSplitter(Qt.Horizontal, self)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.addWidget(sidebar)
        content=QWidget(); content_col=QVBoxLayout(content);content_col.setContentsMargins(0,0,0,0);content_col.setSpacing(0)
        top=QFrame();top.setObjectName('topbar');tl=QHBoxLayout(top);tl.setContentsMargins(26,15,26,15)
        self.title=QLabel('Overview');self.title.setObjectName('topTitle');tl.addWidget(self.title);tl.addStretch()
        self.health=QLabel('QAC: Not verified');self.health.setObjectName('health');tl.addWidget(self.health)
        content_col.addWidget(top)
        self.stack=QStackedWidget()
        self.dashboard=self._make_dashboard();self.stack.addWidget(self.dashboard)
        workspace=QWidget();workspace.setObjectName('workspace');wv=QVBoxLayout(workspace);wv.setContentsMargins(12,10,12,10)
        # The numerous module pages contain wide fixed-width form rows. Do not
        # let their combined sizeHint force the *main window* to stay large:
        # contain overflowing page content in a responsive workspace viewport.
        tabs.tabBar().hide()
        module_viewport=QScrollArea(workspace)
        module_viewport.setWidgetResizable(True)
        module_viewport.setFrameShape(QFrame.Shape.NoFrame)
        module_viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        module_viewport.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        module_viewport.setMinimumSize(0,0)
        module_viewport.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        module_viewport.setWidget(tabs)
        wv.addWidget(module_viewport,1)
        self.stack.addWidget(workspace)
        content_col.addWidget(self.stack,1)
        self.workspace_splitter.addWidget(content)
        self.workspace_splitter.setStretchFactor(0, 0)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([230, 1050])
        outer.addWidget(self.workspace_splitter, 1)
        self.show_home()

    def _nav_style(self, b):
        b.setProperty('role','nav'); b.setCheckable(True); b.setMinimumHeight(43)

    def _make_dashboard(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        body=QWidget();body.setObjectName('dashboardBody')
        lay=QVBoxLayout(body);lay.setContentsMargins(26,25,26,25);lay.setSpacing(18)
        hero=QFrame();hero.setObjectName('hero');h=QVBoxLayout(hero);h.setContentsMargins(28,25,28,25)
        ht=label('QAC Auto Register');ht.setObjectName('heroTitle');h.addWidget(ht)
        hs=label('Quality Data, Smarter Workflow');hs.setObjectName('heroSub');h.addWidget(hs)
        hs2=label('ระบบช่วยลงทะเบียนและจัดการข้อมูล QAC อย่างเป็นระบบ');hs2.setObjectName('heroSub');h.addWidget(hs2)
        lay.addWidget(hero)
        lay.addWidget(label('Quick Access','section'))
        quick=QGridLayout();quick.setSpacing(12)
        for col,(index,title,desc) in enumerate([(0,'Auto Register','Scan / Register'),(4,'Daily Document','Check Sheet'),(5,'Sample Register','Sample Plan'),(6,'Electrode Control','No. / Shot / History')]):
            b=QPushButton(f'{title}\n\n{desc}');b.setProperty('role','tile');b.setMinimumHeight(108)
            b.setEnabled(bool(self.access_checker(index)))
            b.clicked.connect(lambda _checked=False, i=index:self.navigate(i))
            quick.addWidget(b,0,col)
        lay.addLayout(quick)
        lay.addWidget(label('Workflow Status','section'))
        states=QGridLayout();states.setSpacing(12)
        for i,(name,desc) in enumerate([('QAC Session 1  —  Auto Register','สถานะ Session ตรวจสอบเมื่อเปิดใช้งานจริง'),('QAC Session 2  —  Daily Document','แยก Browser Workflow'),('QAC Session 3  —  Sample Register','แยก Browser Workflow')]):
            states.addWidget(card(name,desc),0,i)
        lay.addLayout(states)
        note=card('System overview','ข้อมูลผลการลงทะเบียนและสถิติจะปรากฏเมื่อมีแหล่งข้อมูลที่ตรวจสอบได้ — ไม่แสดงสถิติจำลอง')
        lay.addWidget(note);lay.addStretch()
        scroll.setWidget(body); return scroll

    def show_about_developer(self):
        """Display developer credit without modifying tabs or QAC sessions."""
        dialog = QDialog(self)
        dialog.setWindowTitle('About QAC Auto Register')
        dialog.setMinimumWidth(380)
        dialog.setStyleSheet('QDialog { background:#F2F6FC; color:#14294A; } QLabel { color:#14294A; }')
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)
        title = label('QAC Auto Register')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('font-size:20px;font-weight:700;')
        layout.addWidget(title)
        version = label(f'{DISPLAY_VERSION}  |  Build {BUILD_DATE}  |  {RELEASE_CHANNEL}')
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        logo_path = Path(__file__).resolve().parent.parent / 'assets' / 'branding' / 'ombiz_logo.png'
        if logo_path.is_file():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                image = QLabel()
                image.setAlignment(Qt.AlignCenter)
                image.setPixmap(pixmap.scaled(340, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                layout.addWidget(image)
        credit = label('Developed by OMBiz™')
        credit.setAlignment(Qt.AlignCenter)
        credit.setStyleSheet('font-size:15px;font-weight:700;')
        layout.addWidget(credit)
        close = QPushButton('Close')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def show_home(self):
        self.stack.setCurrentIndex(0);self.title.setText('Home  /  Overview');self._select(-1)

    def navigate(self,index):
        if not self.access_checker(index):return
        if self.before_navigate and not self.before_navigate(index):return
        self.tabs.setCurrentIndex(index)
        self.stack.setCurrentIndex(1)
        self.title.setText(self.tabs.tabText(index))
        self._select(index)
        self.on_navigate(index)

    def _select(self,index):
        for i,b in self.buttons.items():b.setChecked(i==index)

    def sync_tab(self,index):
        if self.stack.currentIndex()==1 and index in self.buttons:
            self.title.setText(self.tabs.tabText(index));self._select(index)
