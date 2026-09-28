"""Library Window for Tucknote.

Displays notes in an Apple- and ChatGPT-inspired minimalist interface:
- Left Sidebar: Brand, Category filters (All, Tasks, Bugs, Ideas, Notes, Screenshots), Settings nav
- Main Area (QStackedWidget):
  - Page 0: Notes workspace (Search & note card list | Note detail inspector)
  - Page 1: Dedicated Settings view with Apple-style grouped cards, ToggleSwitches, and Model Manager
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QUrl, QSize
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QLabel,
    QPushButton,
    QMessageBox,
    QApplication,
    QFrame,
    QStatusBar,
    QComboBox,
    QListView,
    QProgressBar,
    QStackedWidget,
    QScrollArea,
)
from PySide6.QtGui import QFont, QColor, QDesktopServices, QPixmap, QIcon

from tucknote.config import AppSettings, get_data_dir, APP_DISPLAY_NAME

from tucknote.storage.models import Note
from tucknote.storage.repository import NoteRepository
from tucknote.transcription.transcriber import (
    is_whisper_model_cached,
    get_whisper_model_size_mb,
    delete_whisper_model,
)
from tucknote.transcription.llm_processor import (
    is_llm_model_cached,
    get_llm_model_size_mb,
    delete_llm_model,
)
from tucknote.transcription.processor import get_default_text_processor
from tucknote.ui.vector_icons import (
    get_vector_icon,
    get_vector_pixmap,
    get_chevron_icon_path,
    CATEGORY_THEMES,
)
from tucknote.ui.toggle_switch import ToggleSwitch

logger = logging.getLogger("tucknote")


def _build_global_stylesheet() -> str:
    chevron_path = get_chevron_icon_path()
    return f"""
QWidget {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #18181b;
}}

/* Disable all default borders and backgrounds on text labels */
QLabel {{
    border: none;
    background: transparent;
}}

/* Apple / ChatGPT Grouped Card */
QFrame#settingsCard {{
    background-color: #ffffff;
    border: 1px solid #e4e4e7;
    border-radius: 12px;
}}

/* Sleek Apple-style Dropdown */
QComboBox {{
    border: 1px solid #e4e4e7;
    border-radius: 8px;
    background-color: #ffffff;
    padding: 6px 30px 6px 12px;
    font-size: 12px;
    font-weight: 500;
    color: #18181b;
}}
QComboBox:hover {{
    border-color: #a1a1aa;
    background-color: #fafafa;
}}
QComboBox:focus {{
    border-color: #18181b;
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border: none;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url({chevron_path});
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView,
QComboBox QListView,
QFrame.QComboBoxPrivateContainer {{
    background-color: #ffffff;
    color: #18181b;
    border: 1px solid #e4e4e7;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item,
QComboBox QListView::item {{
    background-color: #ffffff;
    color: #18181b;
    padding: 7px 12px;
    border-radius: 6px;
    min-height: 22px;
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected,
QComboBox QListView::item:hover,
QComboBox QListView::item:selected {{
    background-color: #f4f4f5;
    color: #09090b;
}}


/* Minimalist Ultra-Thin 6px Scrollbars */

QScrollBar:vertical {{
    border: none;
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #d4d4d8;
    min-height: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: #a1a1aa;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    border: none;
    background: none;
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    border: none;
    background: transparent;
    height: 6px;
    margin: 0px;
}}
QScrollBar::handle:horizontal {{
    background: #d4d4d8;
    min-width: 24px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #a1a1aa;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    border: none;
    background: none;
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}
"""


def _setup_apple_combobox(cb: QComboBox) -> None:
    """Ensure combobox uses a styled QListView popup matching Apple/ChatGPT aesthetics."""
    view = QListView()
    view.setStyleSheet(
        "QListView { background-color: #ffffff; color: #18181b; border: 1px solid #e4e4e7; border-radius: 8px; padding: 4px; outline: none; }"
        "QListView::item { background-color: #ffffff; color: #18181b; padding: 7px 12px; border-radius: 6px; min-height: 22px; }"
        "QListView::item:hover, QListView::item:selected { background-color: #f4f4f5; color: #09090b; }"
    )
    cb.setView(view)


class NoteListItemWidget(QWidget):
    """Modern, minimalist card widget for each note in the list."""

    def __init__(self, note: Note, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.note = note
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        # Header: Category Badge + Timestamp + App Chip + Attachments
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # Category badge (modern vector icon + clean text)
        cat = note.category or "Note"
        theme = CATEGORY_THEMES.get(cat, CATEGORY_THEMES["Note"])
        cat_badge = QLabel()
        cat_badge.setPixmap(get_vector_pixmap(theme["icon"], color=theme["color"], size=13))
        header_layout.addWidget(cat_badge)

        cat_name = QLabel(theme["label"])
        cat_name.setStyleSheet(
            f"color: {theme['color']}; font-size: 11px; font-weight: 600;"
        )
        header_layout.addWidget(cat_name)

        header_layout.addSpacing(4)

        # Local time
        local_dt = note.captured_at_local
        time_str = local_dt.strftime("%d %b %H:%M")
        self.time_label = QLabel(time_str)
        self.time_label.setStyleSheet("color: #71717a; font-size: 11px;")
        header_layout.addWidget(self.time_label)

        header_layout.addStretch()

        # Screenshot indicator (clean vector camera icon)
        if note.has_screenshot:
            cam_badge = QLabel()
            cam_badge.setPixmap(get_vector_pixmap("camera", color="#71717a", size=13))
            cam_badge.setToolTip("Screenshot attached")
            header_layout.addWidget(cam_badge)

        # Processed indicator (vector sparkles)
        if note.is_processed:
            proc_badge = QLabel()
            proc_badge.setPixmap(get_vector_pixmap("sparkles", color="#16a34a", size=13))
            proc_badge.setToolTip("Categorized by AI")
            header_layout.addWidget(proc_badge)

        # Application chip
        if note.application:
            app_chip = QLabel(note.application.replace(".exe", ""))
            app_chip.setStyleSheet(
                "background-color: #f4f4f5; color: #52525b; border: 1px solid #e4e4e7; "
                "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 500;"
            )
            header_layout.addWidget(app_chip)

        layout.addLayout(header_layout)

        # Window title if present
        if note.window_title:
            title_text = note.window_title
            if len(title_text) > 48:
                title_text = title_text[:45] + "..."
            title_row = QHBoxLayout()
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setSpacing(4)
            win_ico = QLabel()
            win_ico.setPixmap(get_vector_pixmap("app-window", color="#a1a1aa", size=12))
            title_row.addWidget(win_ico)

            self.title_label = QLabel(title_text)
            self.title_label.setStyleSheet("color: #71717a; font-size: 11px; font-weight: 400;")
            title_row.addWidget(self.title_label)
            title_row.addStretch()
            layout.addLayout(title_row)

        # Text preview
        display_text = note.display_text(self.settings.default_text_version)
        preview_text = display_text.replace("\n", " ").strip()
        if len(preview_text) > 85:
            preview_text = preview_text[:82] + "..."
        if not preview_text:
            preview_text = "(No text captured)"
        self.preview_label = QLabel(preview_text)
        self.preview_label.setStyleSheet("color: #18181b; font-size: 12px; line-height: 1.35;")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        # Tags if present
        if note.tags:
            tags_row = QHBoxLayout()
            tags_row.setContentsMargins(0, 2, 0, 0)
            tags_row.setSpacing(4)
            for t in note.tags[:3]:
                tag_lbl = QLabel(f"#{t}")
                tag_lbl.setStyleSheet(
                    "background: #f4f4f5; color: #52525b; border: 1px solid #e4e4e7; "
                    "border-radius: 3px; padding: 0px 5px; font-size: 10px; font-weight: 500;"
                )
                tags_row.addWidget(tag_lbl)
            tags_row.addStretch()
            layout.addLayout(tags_row)


class SidebarItem(QWidget):
    """Sidebar category navigation button with icon, label, and live count badge."""

    def __init__(self, key: str, label: str, icon_name: str, icon_color: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.is_active = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        self.icon_label.setPixmap(get_vector_pixmap(icon_name, color=icon_color, size=15))
        layout.addWidget(self.icon_label)

        self.text_label = QLabel(label)
        self.text_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #3f3f46;")
        layout.addWidget(self.text_label)

        layout.addStretch()

        self.count_badge = QLabel("0")
        self.count_badge.setStyleSheet(
            "background: #e4e4e7; color: #52525b; font-size: 11px; font-weight: 600; "
            "border-radius: 9px; padding: 1px 7px;"
        )
        layout.addWidget(self.count_badge)

        self.update_style()

    def set_count(self, count: int) -> None:
        self.count_badge.setText(str(count))
        self.count_badge.setVisible(count > 0 or self.key == "all")

    def set_active(self, active: bool) -> None:
        self.is_active = active
        self.update_style()

    def update_style(self) -> None:
        if self.is_active:
            self.setStyleSheet(
                "SidebarItem { background: #e4e4e7; border-radius: 6px; }"
            )
            self.text_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #09090b;")
        else:
            self.setStyleSheet(
                "SidebarItem { background: transparent; border-radius: 6px; }"
                "SidebarItem:hover { background: #f4f4f5; }"
            )
            self.text_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #3f3f46;")


class LibraryWindow(QMainWindow):
    """Tucknote Library and Settings desktop window."""

    note_deleted = Signal(str)
    note_updated = Signal(str, str)
    overlay_visibility_toggled = Signal(bool)
    notifications_enabled_toggled = Signal(bool)
    whisper_model_changed = Signal(str)
    whisper_language_changed = Signal(str)
    refinement_engine_changed = Signal(str)
    llm_model_changed = Signal(str)
    streaming_transcription_toggled = Signal(bool)
    refinement_finished = Signal(str, object)  # (note_id, ProcessedTextResult)

    def __init__(self, repository: NoteRepository, settings: AppSettings | None = None, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.settings = settings or AppSettings.load()
        self.selected_note: Note | None = None
        self._active_filter_category: str | None = None
        self._active_filter_screenshot: bool | None = None
        self._text_processor = get_default_text_processor(
            engine=self.settings.refinement_engine,
            model_key=self.settings.llm_model,
        )

        self.refinement_finished.connect(self._on_refinement_finished)

        self.setWindowTitle(f"{APP_DISPLAY_NAME} — Library")
        self.setWindowIcon(get_vector_icon("mic", color="#18181b", size=24))
        self.resize(1060, 680)
        self.setMinimumSize(880, 520)

        self.setStyleSheet(_build_global_stylesheet())
        self._init_ui()
        self.refresh_notes()

    def set_text_processor(self, processor) -> None:
        """Update active text processor instance."""
        self._text_processor = processor

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        central_widget.setStyleSheet("background: #fafafa;")

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Left Sidebar
        self.sidebar_widget = self._build_sidebar()
        root_layout.addWidget(self.sidebar_widget)

        # 2. Main Stacked Widget (Page 0: Notes Workspace, Page 1: Dedicated Settings View)
        self.main_stack = QStackedWidget()
        self.main_stack.setStyleSheet("background: #fafafa;")

        # Page 0: Notes Splitter (Note List | Detail Inspector)
        self.notes_workspace = QSplitter(Qt.Horizontal)
        self.notes_workspace.setStyleSheet(
            "QSplitter::handle { background: #e4e4e7; width: 1px; }"
        )
        self.note_list_container = self._build_note_list_pane()
        self.notes_workspace.addWidget(self.note_list_container)

        self.detail_container = self._build_detail_pane()
        self.notes_workspace.addWidget(self.detail_container)

        self.notes_workspace.setSizes([380, 500])
        self.notes_workspace.setStretchFactor(0, 4)
        self.notes_workspace.setStretchFactor(1, 6)

        self.main_stack.addWidget(self.notes_workspace)

        # Page 1: Apple-style Settings View
        self.settings_panel = self._build_settings_view()
        self.main_stack.addWidget(self.settings_panel)

        # Default to notes view
        self.main_stack.setCurrentIndex(0)
        self.settings_panel.setVisible(False)

        root_layout.addWidget(self.main_stack, 1)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(
            "QStatusBar { background: #ffffff; border-top: 1px solid #e4e4e7; color: #71717a; font-size: 11px; padding: 2px 12px; }"
        )
        self.setStatusBar(self.status_bar)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(190)
        sidebar.setMaximumWidth(230)
        sidebar.setStyleSheet("background: #f4f4f5; border-right: 1px solid #e4e4e7;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 14)
        layout.setSpacing(6)

        # App Brand Header
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 6, 10)
        brand_row.setSpacing(8)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(get_vector_pixmap("sparkles", color="#18181b", size=18))
        brand_row.addWidget(logo_lbl)

        title_lbl = QLabel(APP_DISPLAY_NAME)
        title_lbl.setStyleSheet("font-size: 14px; font-weight: 700; color: #09090b; letter-spacing: -0.2px;")
        brand_row.addWidget(title_lbl)
        brand_row.addStretch()

        layout.addLayout(brand_row)

        # Section: CATEGORIES
        sec_views = QLabel("CATEGORIES")
        sec_views.setStyleSheet("font-size: 10px; font-weight: 700; color: #a1a1aa; padding: 8px 8px 2px 8px; letter-spacing: 0.5px;")
        layout.addWidget(sec_views)

        self.sidebar_items: dict[str, SidebarItem] = {}
        categories_meta = [
            ("all", "All Thoughts", "inbox", "#18181b"),
            ("Task", "Tasks", "check-square", "#2563eb"),
            ("Bug", "Bugs", "bug", "#dc2626"),
            ("Idea", "Ideas", "lightbulb", "#d97706"),
            ("Note", "Notes", "file-text", "#71717a"),
        ]

        for key, label, icon_name, color in categories_meta:
            item = SidebarItem(key, label, icon_name, color)
            item.mousePressEvent = lambda e, k=key: self._on_sidebar_item_clicked(k)
            self.sidebar_items[key] = item
            layout.addWidget(item)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("border: none; border-top: 1px solid #e4e4e7; margin: 4px 6px; max-height: 1px;")
        layout.addWidget(sep)

        sec_media = QLabel("ATTACHMENTS")
        sec_media.setStyleSheet("font-size: 10px; font-weight: 700; color: #a1a1aa; padding: 2px 8px; letter-spacing: 0.5px;")
        layout.addWidget(sec_media)

        item_ss = SidebarItem("screenshot", "Screenshots", "image", "#71717a")
        item_ss.mousePressEvent = lambda e: self._on_sidebar_item_clicked("screenshot")
        self.sidebar_items["screenshot"] = item_ss
        layout.addWidget(item_ss)

        layout.addStretch()

        # Settings Toggle Button in Sidebar Footer
        self.toggle_settings_btn = QPushButton(" Settings")
        self.toggle_settings_btn.setIcon(get_vector_icon("settings", color="#52525b", size=15))
        self.toggle_settings_btn.setStyleSheet(
            "QPushButton { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; padding: 8px 12px; font-size: 12px; color: #27272a; font-weight: 500; text-align: left; }"
            "QPushButton:hover { background: #e4e4e7; color: #09090b; }"
            "QPushButton:checked { background: #18181b; color: #ffffff; border-color: #18181b; font-weight: 600; }"
        )
        self.toggle_settings_btn.setCheckable(True)
        self.toggle_settings_btn.toggled.connect(self._on_toggle_settings_bar)
        layout.addWidget(self.toggle_settings_btn)

        # Default select "all"
        self.sidebar_items["all"].set_active(True)

        return sidebar

    def _build_note_list_pane(self) -> QWidget:
        pane = QWidget()
        pane.setStyleSheet("background: #ffffff;")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        # Search Bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search thoughts, apps, tags...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setStyleSheet(
            "QLineEdit { padding: 8px 12px; font-size: 12px; border: 1px solid #e4e4e7; border-radius: 8px; background: #fafafa; color: #18181b; }"
            "QLineEdit:focus { border: 1px solid #18181b; background: #ffffff; }"
        )
        layout.addWidget(self.search_input)

        # Active Category Filter Pill
        self.filter_indicator_frame = QFrame()
        self.filter_indicator_frame.setStyleSheet(
            "QFrame { background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 6px; padding: 2px 8px; }"
        )
        filter_layout = QHBoxLayout(self.filter_indicator_frame)
        filter_layout.setContentsMargins(6, 3, 6, 3)
        filter_layout.setSpacing(6)

        self.filter_indicator_label = QLabel("Filtered: All")
        self.filter_indicator_label.setStyleSheet("color: #18181b; font-size: 11px; font-weight: 600;")
        filter_layout.addWidget(self.filter_indicator_label)
        filter_layout.addStretch()

        clear_filter_btn = QPushButton("✕ Clear filter")
        clear_filter_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #71717a; font-size: 11px; font-weight: 500; padding: 0 4px; }"
            "QPushButton:hover { color: #09090b; }"
        )
        clear_filter_btn.clicked.connect(lambda: self._on_sidebar_item_clicked("all"))
        filter_layout.addWidget(clear_filter_btn)

        self.filter_indicator_frame.setVisible(False)
        layout.addWidget(self.filter_indicator_frame)

        # Note List
        self.note_list = QListWidget()
        self.note_list.setStyleSheet(
            "QListWidget { border: 1px solid #e4e4e7; border-radius: 8px; background: #ffffff; padding: 4px; outline: none; }"
            "QListWidget::item { border-bottom: 1px solid #f4f4f5; border-radius: 6px; margin: 2px 0px; }"
            "QListWidget::item:selected { background: #f4f4f5; border: 1px solid #e4e4e7; }"
            "QListWidget::item:hover:!selected { background: #fafafa; }"
        )
        self.note_list.currentRowChanged.connect(self._on_note_selected)
        layout.addWidget(self.note_list)

        return pane

    def _build_detail_pane(self) -> QWidget:
        pane = QWidget()
        pane.setStyleSheet("background: #fafafa;")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # Top Bar: Editable Category Selector + Actions (Save, Copy, Delete)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)

        cat_select_lbl = QLabel("Category:")
        cat_select_lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #71717a;")
        top_bar.addWidget(cat_select_lbl)

        self.category_combo = QComboBox()
        _setup_apple_combobox(self.category_combo)
        self.category_combo.addItem(get_vector_icon("file-text", color="#71717a"), "Note", "Note")
        self.category_combo.addItem(get_vector_icon("check-square", color="#2563eb"), "Task", "Task")
        self.category_combo.addItem(get_vector_icon("bug", color="#dc2626"), "Bug", "Bug")
        self.category_combo.addItem(get_vector_icon("lightbulb", color="#d97706"), "Idea", "Idea")
        self.category_combo.addItem(get_vector_icon("tag", color="#a1a1aa"), "(None)", "")
        self.category_combo.currentIndexChanged.connect(self._on_category_dropdown_changed)
        top_bar.addWidget(self.category_combo)

        top_bar.addStretch()

        # Save Button
        self.save_btn = QPushButton(" Save")
        self.save_btn.setIcon(get_vector_icon("save", color="#ffffff", size=13))
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            "QPushButton { background: #18181b; color: white; border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #27272a; }"
            "QPushButton:disabled { background: #e4e4e7; color: #a1a1aa; }"
        )
        self.save_btn.clicked.connect(self._save_changes)
        top_bar.addWidget(self.save_btn)

        # Copy Active Button
        self.copy_main_btn = QPushButton(" Copy")
        self.copy_main_btn.setIcon(get_vector_icon("copy", color="#27272a", size=13))
        self.copy_main_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #27272a; border: 1px solid #e4e4e7; border-radius: 6px; padding: 6px 12px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #f4f4f5; }"
        )
        self.copy_main_btn.clicked.connect(self._copy_current_active_text)
        top_bar.addWidget(self.copy_main_btn)

        # Delete Button
        self.delete_btn = QPushButton(" Delete")
        self.delete_btn.setIcon(get_vector_icon("trash-2", color="#dc2626", size=13))
        self.delete_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #dc2626; border: 1px solid #fecdd3; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #fef2f2; }"
        )
        self.delete_btn.clicked.connect(self._delete_current_note)
        top_bar.addWidget(self.delete_btn)

        layout.addLayout(top_bar)

        # Context Card (Time, App, Window title, Tags)
        meta_frame = QFrame()
        meta_frame.setObjectName("metaCard")
        meta_frame.setStyleSheet(
            "QFrame#metaCard { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; padding: 8px 10px; }"
        )
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.setSpacing(4)

        meta_row1 = QHBoxLayout()
        meta_row1.setSpacing(6)
        time_ico = QLabel()
        time_ico.setPixmap(get_vector_pixmap("clock", color="#71717a", size=13))
        meta_row1.addWidget(time_ico)
        self.meta_time_label = QLabel("Captured: -")
        self.meta_time_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #18181b;")
        meta_row1.addWidget(self.meta_time_label)

        meta_row1.addSpacing(12)
        app_ico = QLabel()
        app_ico.setPixmap(get_vector_pixmap("app-window", color="#71717a", size=13))
        meta_row1.addWidget(app_ico)
        self.meta_app_label = QLabel("Application: -")
        self.meta_app_label.setStyleSheet("font-size: 11px; color: #52525b;")
        meta_row1.addWidget(self.meta_app_label)
        meta_row1.addStretch()
        meta_layout.addLayout(meta_row1)

        self.meta_window_label = QLabel("Window Title: -")
        self.meta_window_label.setWordWrap(True)
        self.meta_window_label.setStyleSheet("font-size: 11px; color: #71717a; margin-left: 2px;")
        meta_layout.addWidget(self.meta_window_label)

        # Tags and Category labels
        tags_sub_row = QHBoxLayout()
        tags_sub_row.setContentsMargins(0, 2, 0, 0)
        tags_sub_row.setSpacing(8)

        tag_ico = QLabel()
        tag_ico.setPixmap(get_vector_pixmap("tag", color="#71717a", size=12))
        tags_sub_row.addWidget(tag_ico)

        self.meta_tags_label = QLabel("Tags: None")
        self.meta_tags_label.setStyleSheet("font-size: 11px; color: #52525b; font-weight: 500;")
        tags_sub_row.addWidget(self.meta_tags_label)
        tags_sub_row.addStretch()

        self.meta_category_label = QLabel("Category: Note")
        self.meta_category_label.setStyleSheet("font-size: 11px; color: #52525b; font-weight: 600;")
        tags_sub_row.addWidget(self.meta_category_label)

        meta_layout.addLayout(tags_sub_row)
        layout.addWidget(meta_frame)

        # Screenshot Preview Card (if attached)
        self.screenshot_frame = QFrame()
        self.screenshot_frame.setObjectName("screenshotCard")
        self.screenshot_frame.setStyleSheet(
            "QFrame#screenshotCard { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; padding: 6px; }"
        )
        screenshot_layout = QHBoxLayout(self.screenshot_frame)
        screenshot_layout.setContentsMargins(6, 6, 6, 6)
        screenshot_layout.setSpacing(10)

        self.screenshot_thumb = QLabel()
        self.screenshot_thumb.setFixedSize(110, 68)
        self.screenshot_thumb.setScaledContents(True)
        self.screenshot_thumb.setStyleSheet("border: 1px solid #e4e4e7; border-radius: 4px;")
        screenshot_layout.addWidget(self.screenshot_thumb)

        screenshot_info_layout = QVBoxLayout()
        screenshot_info_layout.setSpacing(4)
        self.screenshot_title = QLabel("Attached Screenshot")
        self.screenshot_title.setStyleSheet("font-size: 11px; font-weight: 600; color: #18181b;")
        screenshot_info_layout.addWidget(self.screenshot_title)

        screenshot_actions = QHBoxLayout()
        screenshot_actions.setSpacing(6)
        self.view_screenshot_btn = QPushButton(" Open Image")
        self.view_screenshot_btn.setIcon(get_vector_icon("external-link", color="#27272a", size=12))
        self.view_screenshot_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; background: white; border: 1px solid #e4e4e7; border-radius: 4px; }"
            "QPushButton:hover { background: #f4f4f5; }"
        )
        self.view_screenshot_btn.clicked.connect(self._open_screenshot_file)
        screenshot_actions.addWidget(self.view_screenshot_btn)

        self.delete_screenshot_btn = QPushButton(" Remove")
        self.delete_screenshot_btn.setIcon(get_vector_icon("x", color="#dc2626", size=12))
        self.delete_screenshot_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; color: #dc2626; background: #ffffff; border: 1px solid #fecdd3; border-radius: 4px; }"
            "QPushButton:hover { background: #fef2f2; }"
        )
        self.delete_screenshot_btn.clicked.connect(self._remove_screenshot_from_note)
        screenshot_actions.addWidget(self.delete_screenshot_btn)
        screenshot_actions.addStretch()

        screenshot_info_layout.addLayout(screenshot_actions)
        screenshot_layout.addLayout(screenshot_info_layout)
        screenshot_layout.addStretch()

        self.screenshot_frame.setVisible(False)
        layout.addWidget(self.screenshot_frame)

        # Single Clean Transcript Card
        transcript_frame = QFrame()
        transcript_frame.setObjectName("transcriptCard")
        transcript_frame.setStyleSheet(
            "QFrame#transcriptCard { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 8px; padding: 10px; }"
        )
        t_layout = QVBoxLayout(transcript_frame)
        t_layout.setContentsMargins(10, 10, 10, 10)
        t_layout.setSpacing(6)

        t_header = QHBoxLayout()
        t_title = QLabel("TRANSCRIPT")
        t_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #71717a; letter-spacing: 0.5px;")
        t_header.addWidget(t_title)

        self.edited_badge = QLabel("Edited manually")
        self.edited_badge.setStyleSheet(
            "background: #f4f4f5; color: #71717a; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        self.edited_badge.setVisible(False)
        t_header.addWidget(self.edited_badge)
        t_header.addStretch()

        self.copy_transcript_btn = QPushButton(" Copy Text")
        self.copy_transcript_btn.setIcon(get_vector_icon("copy", color="#52525b", size=12))
        self.copy_transcript_btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; font-size: 11px; background: #fafafa; border: 1px solid #e4e4e7; border-radius: 4px; }"
            "QPushButton:hover { background: #f4f4f5; }"
        )
        self.copy_transcript_btn.clicked.connect(self._copy_original_transcript)
        t_header.addWidget(self.copy_transcript_btn)
        t_layout.addLayout(t_header)

        self.transcript_edit = QPlainTextEdit()
        self.transcript_edit.setStyleSheet(
            "QPlainTextEdit { border: none; font-size: 13px; line-height: 1.5; color: #18181b; background: transparent; padding: 4px; }"
        )
        self.transcript_edit.textChanged.connect(self._on_text_modified)
        t_layout.addWidget(self.transcript_edit)

        self.original_box = QLabel()
        self.original_box.setWordWrap(True)
        self.original_box.setStyleSheet(
            "background: #fafafa; color: #71717a; border: 1px dashed #e4e4e7; border-radius: 4px; padding: 6px; font-size: 11px;"
        )
        self.original_box.setVisible(False)
        t_layout.addWidget(self.original_box)

        layout.addWidget(transcript_frame)

        return pane

    def _build_settings_view(self) -> QWidget:
        """Build Apple / ChatGPT style dedicated Settings view with grouped cards."""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: #fafafa; }")

        container = QWidget()
        container.setStyleSheet("background: #fafafa;")
        scroll_area.setWidget(container)

        main_vbox = QVBoxLayout(container)
        main_vbox.setContentsMargins(32, 28, 32, 32)
        main_vbox.setSpacing(24)

        # Header Title & Subtitle
        header_vbox = QVBoxLayout()
        header_vbox.setSpacing(4)

        title_row = QHBoxLayout()
        title_lbl = QLabel("Settings")
        title_lbl.setStyleSheet("font-size: 22px; font-weight: 700; color: #09090b; letter-spacing: -0.4px;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        back_btn = QPushButton("✕ Close")
        back_btn.setStyleSheet(
            "QPushButton { border: 1px solid #e4e4e7; background: #ffffff; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 500; color: #52525b; }"
            "QPushButton:hover { background: #f4f4f5; color: #09090b; }"
        )
        back_btn.clicked.connect(lambda: self._on_toggle_settings_bar(False))
        title_row.addWidget(back_btn)
        header_vbox.addLayout(title_row)

        desc_lbl = QLabel("Manage recording behavior, audio streaming, Whisper transcription, and AI models.")
        desc_lbl.setStyleSheet("font-size: 13px; color: #71717a;")
        header_vbox.addWidget(desc_lbl)
        main_vbox.addLayout(header_vbox)

        # Section 1: GENERAL
        sec_gen_lbl = QLabel("GENERAL")
        sec_gen_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        main_vbox.addWidget(sec_gen_lbl)

        card_gen = self._create_settings_card()
        cg_layout = QVBoxLayout(card_gen)
        cg_layout.setContentsMargins(16, 6, 16, 6)
        cg_layout.setSpacing(0)

        # Row 1: Overlay Switch
        self.overlay_cb = ToggleSwitch()
        self.overlay_cb.setChecked(self.settings.overlay_visible)
        self.overlay_cb.toggled.connect(self._on_overlay_cb_toggled)
        cg_layout.addWidget(
            self._create_setting_row(
                "Floating Recording Overlay",
                "Displays a minimalist status bar on the screen edge while recording.",
                self.overlay_cb,
            )
        )
        cg_layout.addWidget(self._create_card_divider())

        # Row 2: Windows Notifications
        self.notifications_cb = ToggleSwitch()
        self.notifications_cb.setChecked(self.settings.show_notifications)
        self.notifications_cb.toggled.connect(self._on_notifications_cb_toggled)
        cg_layout.addWidget(
            self._create_setting_row(
                "Windows Notifications",
                "Show a discreet notification popup upon successful transcription.",
                self.notifications_cb,
            )
        )
        cg_layout.addWidget(self._create_card_divider())

        # Row 3: Auto-copy
        self.auto_copy_cb = ToggleSwitch()
        self.auto_copy_cb.setChecked(self.settings.auto_copy_clipboard)
        self.auto_copy_cb.toggled.connect(self._on_auto_copy_toggled)
        cg_layout.addWidget(
            self._create_setting_row(
                "Auto-copy to Clipboard",
                "Copies transcribed thoughts directly to clipboard immediately after capture.",
                self.auto_copy_cb,
            )
        )

        main_vbox.addWidget(card_gen)

        # Section 2: SPEECH RECOGNITION & WHISPER
        sec_whisp_lbl = QLabel("SPEECH RECOGNITION & WHISPER")
        sec_whisp_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        main_vbox.addWidget(sec_whisp_lbl)

        card_whisp = self._create_settings_card()
        cw_layout = QVBoxLayout(card_whisp)
        cw_layout.setContentsMargins(16, 6, 16, 6)
        cw_layout.setSpacing(0)

        # Live-Streaming Toggle
        self.streaming_cb = ToggleSwitch()
        self.streaming_cb.setChecked(self.settings.streaming_transcription)
        self.streaming_cb.toggled.connect(self._on_streaming_cb_toggled)
        cw_layout.addWidget(
            self._create_setting_row(
                "Live-Streaming Transcription",
                "Transcribes chunks in background while speaking for near-instant results when you finish.",
                self.streaming_cb,
            )
        )
        cw_layout.addWidget(self._create_card_divider())

        # Language combo
        self.lang_combo = QComboBox()
        _setup_apple_combobox(self.lang_combo)
        for label, val in [
            ("German (Recommended for German & Denglish)", "de"),
            ("English", "en"),
            ("Auto-detect", "auto"),
        ]:
            self.lang_combo.addItem(label, val)
        l_idx = self.lang_combo.findData(self.settings.whisper_language or "de")
        if l_idx >= 0:
            self.lang_combo.setCurrentIndex(l_idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)

        cw_layout.addWidget(
            self._create_setting_row(
                "Spoken Language",
                "Select language or allow automatic detection.",
                self.lang_combo,
            )
        )
        cw_layout.addWidget(self._create_card_divider())

        # Active Whisper Model Dropdown
        self.model_combo = QComboBox()
        _setup_apple_combobox(self.model_combo)
        self._refresh_model_combo_items()
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)

        cw_layout.addWidget(
            self._create_setting_row(
                "Active Whisper Model",
                "Select which model is currently used for all speech transcriptions.",
                self.model_combo,
            )
        )

        main_vbox.addWidget(card_whisp)

        # Dedicated Model Status Frame (Progress bar & ready/error badge)
        self.model_status_frame = QFrame()
        self.model_status_frame.setObjectName("statusFrame")
        self.model_status_frame.setStyleSheet(
            "QFrame#statusFrame { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 8px 14px; }"
        )
        status_layout = QHBoxLayout(self.model_status_frame)
        status_layout.setContentsMargins(8, 4, 8, 4)
        status_layout.setSpacing(10)

        self.model_status_icon = QLabel()
        self.model_status_icon.setPixmap(get_vector_pixmap("check-circle", color="#16a34a", size=15))
        status_layout.addWidget(self.model_status_icon)

        self.model_status_label = QLabel(f"Model '{self.settings.whisper_model or 'small'}' active and ready.")
        self.model_status_label.setStyleSheet("color: #15803d; font-size: 12px; font-weight: 600;")
        status_layout.addWidget(self.model_status_label)

        self.model_progress = QProgressBar()
        self.model_progress.setRange(0, 0)
        self.model_progress.setFixedHeight(4)
        self.model_progress.setFixedWidth(140)
        self.model_progress.setTextVisible(False)
        self.model_progress.setStyleSheet(
            "QProgressBar { border: none; border-radius: 2px; background: #e4e4e7; }"
            "QProgressBar::chunk { background: #18181b; border-radius: 2px; }"
        )
        self.model_progress.setVisible(False)
        status_layout.addWidget(self.model_progress)
        status_layout.addStretch()

        main_vbox.addWidget(self.model_status_frame)

        # Section 3: WHISPER MODELS & STORAGE
        sec_storage_lbl = QLabel("WHISPER MODELS & STORAGE")
        sec_storage_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        main_vbox.addWidget(sec_storage_lbl)

        self.whisper_models_card = self._create_settings_card()
        self.whisper_models_layout = QVBoxLayout(self.whisper_models_card)
        self.whisper_models_layout.setContentsMargins(16, 6, 16, 6)
        self.whisper_models_layout.setSpacing(0)
        self._refresh_whisper_models_card()
        main_vbox.addWidget(self.whisper_models_card)

        # Section 4: AI CATEGORIZATION & LLM
        sec_llm_lbl = QLabel("AI CATEGORIZATION & LLM")
        sec_llm_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        main_vbox.addWidget(sec_llm_lbl)

        card_llm = self._create_settings_card()
        cl_layout = QVBoxLayout(card_llm)
        cl_layout.setContentsMargins(16, 6, 16, 6)
        cl_layout.setSpacing(0)

        # Engine Combo
        self.engine_combo = QComboBox()
        _setup_apple_combobox(self.engine_combo)
        for label, val in [
            ("Local LLM (Auto-categorization & Tags)", "llm"),
            ("Rule-based (Heuristics)", "rules"),
        ]:
            self.engine_combo.addItem(label, val)
        e_idx = self.engine_combo.findData(self.settings.refinement_engine or "llm")
        if e_idx >= 0:
            self.engine_combo.setCurrentIndex(e_idx)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_combo_changed)

        cl_layout.addWidget(
            self._create_setting_row(
                "Categorization Method",
                "Determines how thoughts, tasks, and bugs are automatically categorized.",
                self.engine_combo,
            )
        )
        cl_layout.addWidget(self._create_card_divider())

        # LLM Model Combo
        self.llm_model_combo = QComboBox()
        _setup_apple_combobox(self.llm_model_combo)
        self._refresh_llm_combo_items()
        self.llm_model_combo.currentIndexChanged.connect(self._on_llm_model_combo_changed)

        cl_layout.addWidget(
            self._create_setting_row(
                "Active LLM Model",
                "Choose between Qwen 2.5 0.5B (instant) and 1.5B (higher precision).",
                self.llm_model_combo,
            )
        )

        main_vbox.addWidget(card_llm)

        # Section 5: LLM MODELS & STORAGE
        sec_llm_store_lbl = QLabel("LLM MODELS & STORAGE")
        sec_llm_store_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #a1a1aa; letter-spacing: 0.5px;")
        main_vbox.addWidget(sec_llm_store_lbl)

        self.llm_models_card = self._create_settings_card()
        self.llm_models_layout = QVBoxLayout(self.llm_models_card)
        self.llm_models_layout.setContentsMargins(16, 6, 16, 6)
        self.llm_models_layout.setSpacing(0)
        self._refresh_llm_models_card()
        main_vbox.addWidget(self.llm_models_card)

        # Section 6: ABOUT TUCKNOTE
        sec_about = QLabel(f"{APP_DISPLAY_NAME} v0.2.0 · 100% local & offline on your computer.")
        sec_about.setStyleSheet("font-size: 11px; color: #a1a1aa; text-align: center; padding: 12px 4px;")
        sec_about.setAlignment(Qt.AlignCenter)
        main_vbox.addWidget(sec_about)

        main_vbox.addStretch()

        return scroll_area

    def _create_settings_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("settingsCard")
        return card

    def _create_card_divider(self) -> QFrame:
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setFrameShadow(QFrame.Plain)
        div.setStyleSheet("border: none; border-top: 1px solid #f4f4f5; max-height: 1px; margin: 0px;")
        return div

    def _create_setting_row(self, title: str, subtitle: str, control_widget: QWidget) -> QWidget:
        row = QWidget()
        row.setStyleSheet("border: none; background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(16)

        text_vbox = QVBoxLayout()
        text_vbox.setSpacing(2)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #09090b;")
        text_vbox.addWidget(t_lbl)

        s_lbl = QLabel(subtitle)
        s_lbl.setStyleSheet("font-size: 12px; color: #71717a;")
        s_lbl.setWordWrap(True)
        text_vbox.addWidget(s_lbl)

        layout.addLayout(text_vbox, 1)
        layout.addWidget(control_widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        return row

    def _refresh_whisper_models_card(self) -> None:
        """Populate Whisper model items with size, status badge, activation, and deletion buttons."""
        while self.whisper_models_layout.count():
            item = self.whisper_models_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        models = [
            ("small", "Whisper Small (Recommended)", "Optimal balance of speed and accuracy on CPU (~460 MB)"),
            ("base", "Whisper Base (Fast)", "Ultra fast (~0.3s), minimal resource usage (~74 MB)"),
            ("medium", "Whisper Medium (Accurate)", "High precision, requires more CPU power (~1.5 GB)"),
            ("large-v3-turbo", "Whisper Large v3 Turbo", "Maximum accuracy for complex speech and accents (~1.6 GB)"),
        ]

        active_model = self.settings.whisper_model or "small"

        for idx, (m_val, m_name, m_desc) in enumerate(models):
            is_active = (m_val == active_model)
            is_cached = is_whisper_model_cached(m_val)
            size_mb = get_whisper_model_size_mb(m_val)

            row = QWidget()
            row.setStyleSheet("border: none; background: transparent;")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 10, 0, 10)
            layout.setSpacing(14)

            # Left: Details
            info_vbox = QVBoxLayout()
            info_vbox.setSpacing(3)

            title_row = QHBoxLayout()
            title_row.setSpacing(8)

            t_lbl = QLabel(m_name)
            t_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #09090b;")
            title_row.addWidget(t_lbl)

            # Badges
            if is_active:
                badge = QLabel("Active")
                badge.setStyleSheet(
                    "background: #18181b; color: #ffffff; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700;"
                )
                title_row.addWidget(badge)
            elif is_cached:
                badge = QLabel("Installed")
                badge.setStyleSheet(
                    "background: #f4f4f5; color: #52525b; border: 1px solid #e4e4e7; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
                )
                title_row.addWidget(badge)
            else:
                badge = QLabel("Not downloaded")
                badge.setStyleSheet(
                    "background: transparent; color: #a1a1aa; border: 1px solid #e4e4e7; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 500;"
                )
                title_row.addWidget(badge)

            if is_cached and size_mb > 0:
                size_lbl = QLabel(f"{size_mb:.0f} MB")
                size_lbl.setStyleSheet("font-size: 11px; color: #71717a; font-weight: 500;")
                title_row.addWidget(size_lbl)

            title_row.addStretch()
            info_vbox.addLayout(title_row)

            d_lbl = QLabel(m_desc)
            d_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
            info_vbox.addWidget(d_lbl)
            layout.addLayout(info_vbox, 1)

            # Right: Actions
            actions_row = QHBoxLayout()
            actions_row.setSpacing(6)

            if not is_active:
                activate_btn = QPushButton("Activate")
                activate_btn.setStyleSheet(
                    "QPushButton { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600; color: #18181b; }"
                    "QPushButton:hover { background: #f4f4f5; }"
                )
                activate_btn.clicked.connect(lambda _, m=m_val: self._activate_whisper_model(m))
                actions_row.addWidget(activate_btn)

            if is_cached:
                del_btn = QPushButton("Delete")
                del_btn.setIcon(get_vector_icon("trash-2", color="#dc2626", size=12))
                del_btn.setStyleSheet(
                    "QPushButton { background: #ffffff; border: 1px solid #fecdd3; border-radius: 6px; padding: 5px 10px; font-size: 11px; font-weight: 500; color: #dc2626; }"
                    "QPushButton:hover { background: #fef2f2; }"
                )
                del_btn.clicked.connect(lambda _, m=m_val: self._on_delete_whisper_model(m))
                actions_row.addWidget(del_btn)

            layout.addLayout(actions_row)
            self.whisper_models_layout.addWidget(row)

            if idx < len(models) - 1:
                self.whisper_models_layout.addWidget(self._create_card_divider())

    def _refresh_llm_models_card(self) -> None:
        """Populate LLM model items with size, status, activation, and deletion buttons."""
        while self.llm_models_layout.count():
            item = self.llm_models_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        models = [
            ("qwen2.5-0.5b", "Qwen 2.5 0.5B Instruct", "Minimal RAM usage, instant classification (~0.3s, ~390 MB)"),
            ("qwen2.5-1.5b", "Qwen 2.5 1.5B Instruct", "Higher precision for complex thoughts & tags (~1s, ~980 MB)"),
        ]

        active_model = self.settings.llm_model or "qwen2.5-0.5b"

        for idx, (m_val, m_name, m_desc) in enumerate(models):
            is_active = (m_val == active_model)
            is_cached = is_llm_model_cached(m_val)
            size_mb = get_llm_model_size_mb(m_val)

            row = QWidget()
            row.setStyleSheet("border: none; background: transparent;")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 10, 0, 10)
            layout.setSpacing(14)

            info_vbox = QVBoxLayout()
            info_vbox.setSpacing(3)

            title_row = QHBoxLayout()
            title_row.setSpacing(8)

            t_lbl = QLabel(m_name)
            t_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #09090b;")
            title_row.addWidget(t_lbl)

            if is_active:
                badge = QLabel("Active")
                badge.setStyleSheet(
                    "background: #18181b; color: #ffffff; border-radius: 4px; padding: 2px 7px; font-size: 10px; font-weight: 700;"
                )
                title_row.addWidget(badge)
            elif is_cached:
                badge = QLabel("Installed")
                badge.setStyleSheet(
                    "background: #f4f4f5; color: #52525b; border: 1px solid #e4e4e7; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
                )
                title_row.addWidget(badge)
            else:
                badge = QLabel("Not downloaded")
                badge.setStyleSheet(
                    "background: transparent; color: #a1a1aa; border: 1px solid #e4e4e7; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 500;"
                )
                title_row.addWidget(badge)

            if is_cached and size_mb > 0:
                size_lbl = QLabel(f"{size_mb:.0f} MB")
                size_lbl.setStyleSheet("font-size: 11px; color: #71717a; font-weight: 500;")
                title_row.addWidget(size_lbl)

            title_row.addStretch()
            info_vbox.addLayout(title_row)

            d_lbl = QLabel(m_desc)
            d_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
            info_vbox.addWidget(d_lbl)
            layout.addLayout(info_vbox, 1)

            actions_row = QHBoxLayout()
            actions_row.setSpacing(6)

            if not is_active:
                activate_btn = QPushButton("Activate")
                activate_btn.setStyleSheet(
                    "QPushButton { background: #ffffff; border: 1px solid #e4e4e7; border-radius: 6px; padding: 5px 12px; font-size: 11px; font-weight: 600; color: #18181b; }"
                    "QPushButton:hover { background: #f4f4f5; }"
                )
                activate_btn.clicked.connect(lambda _, m=m_val: self._activate_llm_model(m))
                actions_row.addWidget(activate_btn)

            if is_cached:
                del_btn = QPushButton("Delete")
                del_btn.setIcon(get_vector_icon("trash-2", color="#dc2626", size=12))
                del_btn.setStyleSheet(
                    "QPushButton { background: #ffffff; border: 1px solid #fecdd3; border-radius: 6px; padding: 5px 10px; font-size: 11px; font-weight: 500; color: #dc2626; }"
                    "QPushButton:hover { background: #fef2f2; }"
                )
                del_btn.clicked.connect(lambda _, m=m_val: self._on_delete_llm_model(m))
                actions_row.addWidget(del_btn)

            layout.addLayout(actions_row)
            self.llm_models_layout.addWidget(row)

            if idx < len(models) - 1:
                self.llm_models_layout.addWidget(self._create_card_divider())

    def _activate_whisper_model(self, model_name: str) -> None:
        idx = self.model_combo.findData(model_name)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        else:
            self.settings.whisper_model = model_name
            self.settings.save()
            self.whisper_model_changed.emit(model_name)
            self._refresh_model_combo_items()
            self._refresh_whisper_models_card()

    def _activate_llm_model(self, model_key: str) -> None:
        idx = self.llm_model_combo.findData(model_key)
        if idx >= 0:
            self.llm_model_combo.setCurrentIndex(idx)
        else:
            self.settings.llm_model = model_key
            self.settings.save()
            self.llm_model_changed.emit(model_key)
            self._refresh_llm_combo_items()
            self._refresh_llm_models_card()

    def _on_delete_whisper_model(self, model_name: str) -> None:
        size_mb = get_whisper_model_size_mb(model_name)
        confirm = QMessageBox.question(
            self,
            "Delete Whisper Model",
            f"Are you sure you want to delete the Whisper model '{model_name}' ({size_mb:.0f} MB)?\n"
            "It will be removed from disk and can be re-downloaded at any time.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            success = delete_whisper_model(model_name)
            if success:
                # If deleted model was active, fallback to small or base
                if self.settings.whisper_model == model_name:
                    fallback = "base" if model_name != "base" else "small"
                    self._activate_whisper_model(fallback)
                self._refresh_model_combo_items()
                self._refresh_whisper_models_card()
                self.status_bar.showMessage(f"Model '{model_name}' deleted. {size_mb:.0f} MB freed.", 3500)
            else:
                QMessageBox.warning(self, "Error", f"Could not delete model '{model_name}'.")

    def _on_delete_llm_model(self, model_key: str) -> None:
        size_mb = get_llm_model_size_mb(model_key)
        confirm = QMessageBox.question(
            self,
            "Delete LLM Model",
            f"Are you sure you want to delete the LLM model '{model_key}' ({size_mb:.0f} MB) from disk?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            success = delete_llm_model(model_key)
            if success:
                if self.settings.llm_model == model_key:
                    fallback = "qwen2.5-0.5b" if model_key != "qwen2.5-0.5b" else "qwen2.5-1.5b"
                    self._activate_llm_model(fallback)
                self._refresh_llm_combo_items()
                self._refresh_llm_models_card()
                self.status_bar.showMessage(f"LLM model '{model_key}' deleted. {size_mb:.0f} MB freed.", 3500)
            else:
                QMessageBox.warning(self, "Error", f"Could not delete model '{model_key}'.")

    # Sidebar Filter Handling
    def _on_sidebar_item_clicked(self, key: str) -> None:
        # Switch stack back to Notes Workspace
        self.main_stack.setCurrentIndex(0)
        self.settings_panel.setVisible(False)
        self.toggle_settings_btn.setChecked(False)

        for k, item in self.sidebar_items.items():
            item.set_active(k == key)

        if key == "all":
            self._active_filter_category = None
            self._active_filter_screenshot = None
            self.filter_indicator_frame.setVisible(False)
        elif key == "screenshot":
            self._active_filter_category = None
            self._active_filter_screenshot = True
            self.filter_indicator_label.setText("Filtered: Screenshots")
            self.filter_indicator_frame.setVisible(True)
        else:
            self._active_filter_category = key
            self._active_filter_screenshot = None
            self.filter_indicator_label.setText(f"Category: {key}s")
            self.filter_indicator_frame.setVisible(True)

        self.refresh_notes()

    def _update_sidebar_counts(self) -> None:
        counts = self.repository.get_category_counts()
        for key, item in self.sidebar_items.items():
            if key == "all":
                item.set_count(counts.get("all", 0))
            elif key == "screenshot":
                item.set_count(counts.get("screenshot", 0))
            else:
                item.set_count(counts.get(key, 0))

    # Note Loading & Filtering
    def refresh_notes(self) -> None:
        query = self.search_input.text()
        notes = self.repository.search(
            query=query,
            category=self._active_filter_category,
            has_screenshot=self._active_filter_screenshot,
        )

        current_id = self.selected_note.id if self.selected_note else None
        self.note_list.clear()
        found_idx = -1

        for idx, note in enumerate(notes):
            item = QListWidgetItem(self.note_list)
            card = NoteListItemWidget(note, self.settings)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, note)
            self.note_list.addItem(item)
            self.note_list.setItemWidget(item, card)

            if current_id and note.id == current_id:
                found_idx = idx

        if found_idx >= 0:
            self.note_list.setCurrentRow(found_idx)
        elif self.note_list.count() > 0:
            self.note_list.setCurrentRow(0)
        else:
            self._clear_detail_view()

        self._update_sidebar_counts()
        self._update_status_bar(len(notes))

    def _on_search_changed(self, text: str) -> None:
        self.refresh_notes()

    def _on_note_selected(self, row: int) -> None:
        if row < 0 or row >= self.note_list.count():
            self._clear_detail_view()
            return

        item = self.note_list.item(row)
        note: Note = item.data(Qt.UserRole)
        self.selected_note = note

        # Update metadata
        local_dt = note.captured_at_local
        self.meta_time_label.setText(f"Captured: {local_dt.strftime('%d %b %Y %H:%M:%S')}")
        self.meta_app_label.setText(f"Application: {note.application or '(not detected)'}")
        self.meta_window_label.setText(f"Window Title: {note.window_title or '(no title)'}")

        cat_str = f"Category: {note.category}" if note.category else "Category: (None)"
        self.meta_category_label.setText(cat_str)
        tags_str = f"Tags: {', '.join('#' + t for t in note.tags)}" if note.tags else "Tags: None"
        self.meta_tags_label.setText(tags_str)

        # Update Category Dropdown without triggering change signal
        self.category_combo.blockSignals(True)
        idx = self.category_combo.findData(note.category or "")
        if idx >= 0:
            self.category_combo.setCurrentIndex(idx)
        else:
            self.category_combo.setCurrentIndex(4)  # None
        self.category_combo.blockSignals(False)

        # Update screenshot frame
        if note.has_screenshot:
            pix = QPixmap(note.screenshot_path)
            if not pix.isNull():
                self.screenshot_thumb.setPixmap(pix.scaled(110, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.screenshot_frame.setVisible(True)
            else:
                self.screenshot_frame.setVisible(False)
        else:
            self.screenshot_frame.setVisible(False)

        # Update Transcript
        self.transcript_edit.blockSignals(True)
        self.transcript_edit.setPlainText(note.transcript)
        self.transcript_edit.blockSignals(False)

        # Original transcript indicator
        if note.is_edited:
            self.edited_badge.setVisible(True)
            self.original_box.setVisible(True)
            self.original_box.setText(f"Original Transcript:\n{note.original_transcript}")
        else:
            self.edited_badge.setVisible(False)
            self.original_box.setVisible(False)

        self.save_btn.setEnabled(False)
        self.copy_main_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _clear_detail_view(self) -> None:
        self.selected_note = None
        self.meta_time_label.setText("Captured: -")
        self.meta_app_label.setText("Application: -")
        self.meta_window_label.setText("Window Title: -")
        self.meta_category_label.setText("Category: -")
        self.meta_tags_label.setText("Tags: -")
        self.screenshot_frame.setVisible(False)

        self.category_combo.blockSignals(True)
        self.category_combo.setCurrentIndex(4)
        self.category_combo.blockSignals(False)

        self.transcript_edit.blockSignals(True)
        self.transcript_edit.setPlainText("")
        self.transcript_edit.blockSignals(False)

        self.edited_badge.setVisible(False)
        self.original_box.setVisible(False)
        self.save_btn.setEnabled(False)
        self.copy_main_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

    def _on_category_dropdown_changed(self, idx: int) -> None:
        """User changed the category dropdown directly in note details."""
        if not self.selected_note:
            return
        new_cat = self.category_combo.currentData() or None
        updated = self.repository.update_category(self.selected_note.id, new_cat)
        if updated:
            self.selected_note.category = new_cat
            self.meta_category_label.setText(f"Category: {new_cat or '(None)'}")
            self.note_updated.emit(updated.id, updated.transcript)
            self.refresh_notes()
            self.status_bar.showMessage(f"Category updated to '{new_cat or 'None'}'.", 3000)

    def _on_text_modified(self) -> None:
        if not self.selected_note:
            return
        modified = self.transcript_edit.toPlainText().strip() != self.selected_note.transcript.strip()
        self.save_btn.setEnabled(modified)

    def _save_changes(self) -> None:
        if not self.selected_note:
            return
        new_text = self.transcript_edit.toPlainText().strip()
        updated = self.repository.update_transcript(self.selected_note.id, new_text)
        if updated:
            self.selected_note = updated
            self.note_updated.emit(updated.id, new_text)
            self.refresh_notes()
            self.status_bar.showMessage("Changes saved successfully.", 3000)

    def _run_text_refinement(self, async_mode: bool = True) -> None:
        """Run AI categorization and tagging on current note."""
        if not self.selected_note:
            return

        target_note = self.selected_note

        if not async_mode:
            try:
                res = self._text_processor.process(
                    target_note.transcript,
                    context_app=target_note.application,
                    context_window=target_note.window_title,
                    language=self.settings.whisper_language,
                )
                self._on_refinement_finished(target_note.id, res)
            except Exception as e:
                logger.error("Error during categorization: %s", e)
                self._on_refinement_finished(target_note.id, None)
            return

        def worker():
            try:
                res = self._text_processor.process(
                    target_note.transcript,
                    context_app=target_note.application,
                    context_window=target_note.window_title,
                    language=self.settings.whisper_language,
                )
                self.refinement_finished.emit(target_note.id, res)
            except Exception as e:
                logger.error("Error during categorization: %s", e)
                self.refinement_finished.emit(target_note.id, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_refinement_finished(self, note_id: str, res) -> None:
        if not res or not res.success:
            return

        updated = self.repository.update_processed_text(
            note_id,
            res.text or "",
            res.processor_id,
            category=res.category,
            tags=res.tags,
        )
        if updated and self.selected_note and self.selected_note.id == note_id:
            self.selected_note = updated
            self.category_combo.blockSignals(True)
            idx = self.category_combo.findData(updated.category or "")
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
            self.category_combo.blockSignals(False)

            self.meta_category_label.setText(f"Category: {updated.category or '(None)'}")
            self.meta_tags_label.setText(f"Tags: {', '.join('#' + t for t in updated.tags)}" if updated.tags else "Tags: None")
            self.refresh_notes()

    def _copy_original_transcript(self) -> None:
        text = self.transcript_edit.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage("Transcript copied to clipboard.", 3000)

    def _copy_current_active_text(self) -> None:
        self._copy_original_transcript()

    def _open_screenshot_file(self) -> None:
        if self.selected_note and self.selected_note.has_screenshot:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.selected_note.screenshot_path))

    def _remove_screenshot_from_note(self) -> None:
        if not self.selected_note or not self.selected_note.has_screenshot:
            return
        confirm = QMessageBox.question(
            self,
            "Remove Screenshot",
            "Are you sure you want to remove and delete this screenshot?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.repository.remove_screenshot(self.selected_note.id)
            self.selected_note.screenshot_path = None
            self.screenshot_frame.setVisible(False)
            self.refresh_notes()
            self.status_bar.showMessage("Screenshot removed.", 3000)

    def _delete_current_note(self) -> None:
        if not self.selected_note:
            return
        confirm = QMessageBox.question(
            self,
            "Delete Thought",
            "Are you sure you want to permanently delete this thought?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            note_id = self.selected_note.id
            success = self.repository.delete(note_id)
            if success:
                self.note_deleted.emit(note_id)
                self.refresh_notes()
                self.status_bar.showMessage("Thought deleted.", 3000)

    def _update_status_bar(self, filtered_count: int | None = None) -> None:
        total = self.repository.count()
        if filtered_count is not None and (self.search_input.text().strip() or self._active_filter_category or self._active_filter_screenshot):
            self.status_bar.showMessage(f"{filtered_count} of {total} thoughts shown")
        else:
            self.status_bar.showMessage(f"{total} thoughts saved")

    # Settings callbacks and helpers
    def _on_toggle_settings_bar(self, checked: bool) -> None:
        if checked:
            self.main_stack.setCurrentIndex(1)
            self.settings_panel.setVisible(True)
            self.toggle_settings_btn.setChecked(True)
            for item in self.sidebar_items.values():
                item.set_active(False)
            self._refresh_model_combo_items()
            self._refresh_whisper_models_card()
            self._refresh_llm_combo_items()
            self._refresh_llm_models_card()
        else:
            self.main_stack.setCurrentIndex(0)
            self.settings_panel.setVisible(False)
            self.toggle_settings_btn.setChecked(False)
            active_key = self._active_filter_category or ("screenshot" if self._active_filter_screenshot else "all")
            if active_key in self.sidebar_items:
                self.sidebar_items[active_key].set_active(True)

    def open_settings(self) -> None:
        self._on_toggle_settings_bar(True)

    def _on_auto_copy_toggled(self, checked: bool) -> None:
        self.settings.auto_copy_clipboard = checked
        self.settings.save()
        self.status_bar.showMessage("Auto-copy enabled." if checked else "Auto-copy disabled.", 2500)

    def _on_overlay_cb_toggled(self, checked: bool) -> None:
        self.settings.overlay_visible = checked
        self.settings.save()
        self.overlay_visibility_toggled.emit(checked)
        self.status_bar.showMessage("Recording overlay visible." if checked else "Recording overlay hidden.", 2500)

    def _on_notifications_cb_toggled(self, checked: bool) -> None:
        self.settings.show_notifications = checked
        self.settings.save()
        self.notifications_enabled_toggled.emit(checked)
        self.status_bar.showMessage("Notifications enabled." if checked else "Notifications disabled.", 2500)

    def update_overlay_checkbox(self, visible: bool) -> None:
        self.overlay_cb.blockSignals(True)
        self.overlay_cb.setChecked(visible)
        self.overlay_cb.blockSignals(False)

    def update_notifications_checkbox(self, enabled: bool) -> None:
        self.notifications_cb.blockSignals(True)
        self.notifications_cb.setChecked(enabled)
        self.notifications_cb.blockSignals(False)

    def _on_streaming_cb_toggled(self, checked: bool) -> None:
        self.settings.streaming_transcription = checked
        self.settings.save()
        self.streaming_transcription_toggled.emit(checked)
        msg = "Live-streaming transcription enabled." if checked else "Batch transcription enabled."
        self.status_bar.showMessage(msg, 2500)

    def update_streaming_checkbox(self, enabled: bool) -> None:
        self.streaming_cb.blockSignals(True)
        self.streaming_cb.setChecked(enabled)
        self.streaming_cb.blockSignals(False)

    def _refresh_model_combo_items(self) -> None:
        current_val = self.settings.whisper_model or "small"
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        models = [
            ("small", "small", "Recommended: ~0.8s, best balance on CPU (460 MB)"),
            ("base", "base", "Ultra fast: ~0.3s (74 MB)"),
            ("medium", "medium", "High precision: ~4-6s on CPU (1.5 GB)"),
            ("large-v3-turbo", "large-v3-turbo", "Maximum accuracy: ~15-20s on CPU (1.6 GB)"),
        ]
        for val, name, detail in models:
            is_cached = is_whisper_model_cached(val)
            badge = "✓ Installed" if is_cached else "⬇ Download required"
            label = f"{name}  [{badge}]  —  {detail}"
            self.model_combo.addItem(label, val)

        idx = self.model_combo.findData(current_val)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.blockSignals(False)

    def _refresh_llm_combo_items(self) -> None:
        current_val = self.settings.llm_model or "qwen2.5-0.5b"
        self.llm_model_combo.blockSignals(True)
        self.llm_model_combo.clear()
        models = [
            ("qwen2.5-0.5b", "Qwen 2.5 0.5B", "Instant classification (~0.3s, ~390 MB)"),
            ("qwen2.5-1.5b", "Qwen 2.5 1.5B", "High precision (~1s, ~980 MB)"),
        ]
        for val, name, detail in models:
            is_cached = is_llm_model_cached(val)
            badge = "✓ Installed" if is_cached else "⬇ Download required"
            label = f"{name}  [{badge}]  —  {detail}"
            self.llm_model_combo.addItem(label, val)

        idx = self.llm_model_combo.findData(current_val)
        if idx >= 0:
            self.llm_model_combo.setCurrentIndex(idx)
        self.llm_model_combo.blockSignals(False)

    def show_model_loading(self, model_name: str) -> None:
        """Display animated loading progress bar and status when switching/loading model."""
        is_cached = is_whisper_model_cached(model_name)
        text = (
            f"Loading model '{model_name}'..."
            if is_cached
            else f"Downloading and preparing model '{model_name}' (may take a moment)..."
        )
        self.model_status_frame.setStyleSheet(
            "QFrame#statusFrame { background: #f4f4f5; border: 1px solid #e4e4e7; border-radius: 8px; padding: 8px 14px; }"
        )
        self.model_status_icon.setPixmap(get_vector_pixmap("sparkles", color="#18181b", size=15))
        self.model_status_label.setText(text)
        self.model_status_label.setStyleSheet("color: #18181b; font-size: 12px; font-weight: 600;")
        self.model_progress.setVisible(True)
        self.model_status_frame.setVisible(True)
        self.model_combo.setEnabled(False)

    def hide_model_loading(self, model_name: str, success: bool = True, error_message: str | None = None) -> None:
        """Update UI when model loading completes or fails."""
        self.model_progress.setVisible(False)
        self.model_combo.setEnabled(True)
        if success:
            self.model_status_frame.setStyleSheet(
                "QFrame#statusFrame { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 8px 14px; }"
            )
            self.model_status_icon.setPixmap(get_vector_pixmap("check-circle", color="#16a34a", size=15))
            self.model_status_label.setText(f"Model '{model_name}' active and ready.")
            self.model_status_label.setStyleSheet("color: #15803d; font-size: 12px; font-weight: 600;")
            self._refresh_model_combo_items()
            self._refresh_whisper_models_card()
        else:
            self.model_status_frame.setStyleSheet(
                "QFrame#statusFrame { background: #fef2f2; border: 1px solid #fecdd3; border-radius: 8px; padding: 8px 14px; }"
            )
            self.model_status_icon.setPixmap(get_vector_pixmap("alert-circle", color="#dc2626", size=15))
            err_text = f"Error loading model '{model_name}': {error_message}" if error_message else f"Error loading model '{model_name}'"
            self.model_status_label.setText(err_text)
            self.model_status_label.setStyleSheet("color: #b91c1c; font-size: 12px; font-weight: 600;")

    def _on_model_combo_changed(self, idx: int) -> None:
        model = self.model_combo.currentData()
        if not model:
            return
        self.show_model_loading(model)
        self.settings.whisper_model = model
        self.settings.save()
        self.whisper_model_changed.emit(model)
        self._refresh_whisper_models_card()
        self.status_bar.showMessage(f"Preparing Whisper model '{model}'...", 3000)

    def _on_lang_combo_changed(self, idx: int) -> None:
        lang = self.lang_combo.currentData()
        self.settings.whisper_language = lang
        self.settings.save()
        self.whisper_language_changed.emit(lang)
        self.status_bar.showMessage(f"Spoken language: '{self.lang_combo.currentText()}'.", 2500)

    def _on_engine_combo_changed(self, idx: int) -> None:
        engine = self.engine_combo.currentData()
        self.settings.refinement_engine = engine
        self.settings.save()
        self.refinement_engine_changed.emit(engine)
        self.status_bar.showMessage(f"Method: '{self.engine_combo.currentText()}'.", 2500)

    def _on_llm_model_combo_changed(self, idx: int) -> None:
        model = self.llm_model_combo.currentData()
        self.settings.llm_model = model
        self.settings.save()
        self.llm_model_changed.emit(model)
        self._refresh_llm_models_card()
        self.status_bar.showMessage(f"LLM model: '{model}'.", 2500)
