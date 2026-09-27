"""Library Window for Thought Capture (tucknote).

Displays notes in a clean, modern, minimalist three-pane interface:
- Left Sidebar: Category filters (All, Tasks, Bugs, Ideas, Notes, Screenshots) with live counts
- Center Pane: Search & filterable note card list
- Right Pane: Note detail inspector with instant category editing, dual transcripts, screenshot actions, and settings.
"""

from __future__ import annotations

import logging
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
    QTabWidget,
    QCheckBox,
    QComboBox,
)
from PySide6.QtGui import QFont, QColor, QDesktopServices, QPixmap, QIcon

from tucknote.config import AppSettings
from tucknote.storage.models import Note
from tucknote.storage.repository import NoteRepository
from tucknote.transcription.processor import get_default_text_processor
from tucknote.ui.vector_icons import get_vector_icon, get_vector_pixmap, CATEGORY_THEMES

logger = logging.getLogger("tucknote")


class NoteListItemWidget(QWidget):
    """Modern, minimalist card widget for each note in the list."""

    def __init__(self, note: Note, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.note = note
        self.settings = settings

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header: Category Badge + Timestamp + App Chip + Attachments
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        # Category badge (modern vector icon + subtle pill)
        cat = note.category or "Note"
        theme = CATEGORY_THEMES.get(cat, CATEGORY_THEMES["Note"])
        cat_badge = QLabel()
        cat_badge.setPixmap(get_vector_pixmap(theme["icon"], color=theme["color"], size=13))
        header_layout.addWidget(cat_badge)

        cat_name = QLabel(theme["label"])
        cat_name.setStyleSheet(
            f"color: {theme['color']}; font-size: 11px; font-weight: 700;"
        )
        header_layout.addWidget(cat_name)

        header_layout.addSpacing(4)

        # Local time
        local_dt = note.captured_at_local
        time_str = local_dt.strftime("%d %b %H:%M")
        self.time_label = QLabel(time_str)
        self.time_label.setStyleSheet("color: #64748b; font-size: 11px;")
        header_layout.addWidget(self.time_label)

        header_layout.addStretch()

        # Screenshot indicator (clean vector icon)
        if note.has_screenshot:
            cam_badge = QLabel()
            cam_badge.setPixmap(get_vector_pixmap("camera", color="#7c3aed", size=13))
            cam_badge.setToolTip("Screenshot attached")
            header_layout.addWidget(cam_badge)

        # Processed indicator (vector sparkles)
        if note.is_processed:
            proc_badge = QLabel()
            proc_badge.setPixmap(get_vector_pixmap("sparkles", color="#16a34a", size=13))
            proc_badge.setToolTip("Refined with AI")
            header_layout.addWidget(proc_badge)

        # Application chip
        if note.application:
            app_chip = QLabel(note.application.replace(".exe", ""))
            app_chip.setStyleSheet(
                "background-color: #f1f5f9; color: #475569; border: 1px solid #e2e8f0; "
                "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
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
            win_ico.setPixmap(get_vector_pixmap("app-window", color="#94a3b8", size=12))
            title_row.addWidget(win_ico)

            self.title_label = QLabel(title_text)
            self.title_label.setStyleSheet("color: #475569; font-size: 11px; font-weight: 500;")
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
        self.preview_label.setStyleSheet("color: #1e293b; font-size: 12px; line-height: 1.3;")
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
                    "background: #f8fafc; color: #6366f1; border: 1px solid #e0e7ff; "
                    "border-radius: 3px; padding: 0px 4px; font-size: 10px; font-weight: 500;"
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
        self.text_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #334155;")
        layout.addWidget(self.text_label)

        layout.addStretch()

        self.count_badge = QLabel("0")
        self.count_badge.setStyleSheet(
            "background: #e2e8f0; color: #475569; font-size: 11px; font-weight: 600; "
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
                "SidebarItem { background: #e2e8f0; border-radius: 6px; }"
            )
            self.text_label.setStyleSheet("font-size: 12px; font-weight: 700; color: #0f172a;")
        else:
            self.setStyleSheet(
                "SidebarItem { background: transparent; border-radius: 6px; }"
                "SidebarItem:hover { background: #f1f5f9; }"
            )
            self.text_label.setStyleSheet("font-size: 12px; font-weight: 500; color: #334155;")


class LibraryWindow(QMainWindow):
    """Thought Capture Library desktop window."""

    note_deleted = Signal(str)
    note_updated = Signal(str, str)
    overlay_visibility_toggled = Signal(bool)
    notifications_enabled_toggled = Signal(bool)
    whisper_model_changed = Signal(str)
    whisper_language_changed = Signal(str)
    refinement_engine_changed = Signal(str)
    llm_model_changed = Signal(str)

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

        self.setWindowTitle("Thought Capture — Library")
        self.setWindowIcon(get_vector_icon("mic", color="#2563eb", size=24))
        self.resize(1020, 640)
        self.setMinimumSize(850, 500)

        self._init_ui()
        self.refresh_notes()

    def set_text_processor(self, processor) -> None:
        """Update active text processor instance."""
        self._text_processor = processor

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        central_widget.setStyleSheet("background: #f8fafc;")

        window_layout = QVBoxLayout(central_widget)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(0)

        # 1. Collapsible Settings Drawer
        self._build_settings_panel()
        window_layout.addWidget(self.settings_panel)

        # 2. Main Three-Pane Workspace (Sidebar | Note List | Details)
        workspace = QSplitter(Qt.Horizontal)
        workspace.setStyleSheet(
            "QSplitter::handle { background: #e2e8f0; width: 1px; }"
        )

        # Pane 1: Left Navigation Sidebar
        self.sidebar_widget = self._build_sidebar()
        workspace.addWidget(self.sidebar_widget)

        # Pane 2: Middle Note List
        list_container = self._build_note_list_pane()
        workspace.addWidget(list_container)

        # Pane 3: Right Note Inspector
        detail_container = self._build_detail_pane()
        workspace.addWidget(detail_container)

        # Splitter ratios: Sidebar 20%, List 35%, Details 45%
        workspace.setSizes([200, 350, 470])
        workspace.setStretchFactor(0, 0)
        workspace.setStretchFactor(1, 4)
        workspace.setStretchFactor(2, 6)

        window_layout.addWidget(workspace)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet(
            "QStatusBar { background: #ffffff; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 11px; padding: 2px 10px; }"
        )
        self.setStatusBar(self.status_bar)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(230)
        sidebar.setStyleSheet("background: #f8fafc; border-right: 1px solid #e2e8f0;")

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 14, 10, 12)
        layout.setSpacing(6)

        # App Brand Header
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 0, 6, 8)
        brand_row.setSpacing(8)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(get_vector_pixmap("sparkles", color="#2563eb", size=18))
        brand_row.addWidget(logo_lbl)

        title_lbl = QLabel("Thought Capture")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #0f172a;")
        brand_row.addWidget(title_lbl)
        brand_row.addStretch()

        layout.addLayout(brand_row)

        # Section: FILTERS
        sec_views = QLabel("CATEGORIES")
        sec_views.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; padding: 6px 8px 2px 8px;")
        layout.addWidget(sec_views)

        self.sidebar_items: dict[str, SidebarItem] = {}
        categories_meta = [
            ("all", "All Thoughts", "inbox", "#3b82f6"),
            ("Task", "Tasks", "check-square", "#2563eb"),
            ("Bug", "Bugs", "bug", "#e11d48"),
            ("Idea", "Ideas", "lightbulb", "#d97706"),
            ("Note", "Notes", "file-text", "#64748b"),
        ]

        for key, label, icon_name, color in categories_meta:
            item = SidebarItem(key, label, icon_name, color)
            item.mousePressEvent = lambda e, k=key: self._on_sidebar_item_clicked(k)
            self.sidebar_items[key] = item
            layout.addWidget(item)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #e2e8f0; margin: 4px 6px;")
        layout.addWidget(sep)

        sec_media = QLabel("ATTACHMENTS")
        sec_media.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; padding: 2px 8px;")
        layout.addWidget(sec_media)

        item_ss = SidebarItem("screenshot", "Screenshots", "image", "#7c3aed")
        item_ss.mousePressEvent = lambda e: self._on_sidebar_item_clicked("screenshot")
        self.sidebar_items["screenshot"] = item_ss
        layout.addWidget(item_ss)

        layout.addStretch()

        # Settings Toggle Button in Sidebar Footer
        self.toggle_settings_btn = QPushButton(" Settings")
        self.toggle_settings_btn.setIcon(get_vector_icon("settings", color="#475569", size=15))
        self.toggle_settings_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #e2e8f0; border-radius: 6px; padding: 7px 10px; font-size: 12px; color: #334155; font-weight: 500; text-align: left; }"
            "QPushButton:hover { background: #f1f5f9; color: #0f172a; }"
            "QPushButton:checked { background: #e2e8f0; font-weight: 700; }"
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
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        # Search Bar
        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search thoughts, applications, tags...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setStyleSheet(
            "QLineEdit { padding: 7px 10px 7px 28px; font-size: 12px; border: 1px solid #cbd5e1; border-radius: 6px; background: #ffffff; }"
            "QLineEdit:focus { border: 1px solid #2563eb; }"
        )
        search_row.addWidget(self.search_input)

        layout.addLayout(search_row)

        # Active Category Filter Pill
        self.filter_indicator_frame = QFrame()
        self.filter_indicator_frame.setStyleSheet(
            "QFrame { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 5px; padding: 2px 8px; }"
        )
        filter_layout = QHBoxLayout(self.filter_indicator_frame)
        filter_layout.setContentsMargins(4, 2, 4, 2)
        filter_layout.setSpacing(6)

        self.filter_indicator_label = QLabel("Filtered by: All")
        self.filter_indicator_label.setStyleSheet("color: #1e40af; font-size: 11px; font-weight: 600;")
        filter_layout.addWidget(self.filter_indicator_label)
        filter_layout.addStretch()

        clear_filter_btn = QPushButton("✕ Clear")
        clear_filter_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #3b82f6; font-size: 11px; font-weight: bold; padding: 0 4px; }"
            "QPushButton:hover { color: #1d4ed8; text-decoration: underline; }"
        )
        clear_filter_btn.clicked.connect(lambda: self._on_sidebar_item_clicked("all"))
        filter_layout.addWidget(clear_filter_btn)

        self.filter_indicator_frame.setVisible(False)
        layout.addWidget(self.filter_indicator_frame)

        # Note List
        self.note_list = QListWidget()
        self.note_list.setStyleSheet(
            "QListWidget { border: 1px solid #e2e8f0; border-radius: 6px; background: #ffffff; padding: 2px; outline: none; }"
            "QListWidget::item { border-bottom: 1px solid #f1f5f9; border-radius: 6px; margin: 2px 2px; }"
            "QListWidget::item:selected { background: #eff6ff; border: 1px solid #bfdbfe; }"
            "QListWidget::item:hover:!selected { background: #f8fafc; }"
        )
        self.note_list.currentRowChanged.connect(self._on_note_selected)
        layout.addWidget(self.note_list)

        return pane

    def _build_detail_pane(self) -> QWidget:
        pane = QWidget()
        pane.setStyleSheet("background: #f8fafc;")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Top Bar: Editable Category Selector + Actions (Save, Copy, Delete)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(8)

        # Editable Category Selector
        cat_select_lbl = QLabel("Category:")
        cat_select_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #64748b;")
        top_bar.addWidget(cat_select_lbl)

        self.category_combo = QComboBox()
        self.category_combo.setStyleSheet(
            "QComboBox { padding: 4px 10px; font-size: 12px; font-weight: 600; border: 1px solid #cbd5e1; border-radius: 6px; background: #ffffff; min-width: 110px; }"
            "QComboBox:hover { border: 1px solid #94a3b8; }"
            "QComboBox::drop-down { border: none; }"
        )
        self.category_combo.addItem(get_vector_icon("file-text", color="#64748b"), "Note", "Note")
        self.category_combo.addItem(get_vector_icon("check-square", color="#2563eb"), "Task", "Task")
        self.category_combo.addItem(get_vector_icon("bug", color="#e11d48"), "Bug", "Bug")
        self.category_combo.addItem(get_vector_icon("lightbulb", color="#d97706"), "Idea", "Idea")
        self.category_combo.addItem(get_vector_icon("tag", color="#94a3b8"), "(None)", "")
        self.category_combo.currentIndexChanged.connect(self._on_category_dropdown_changed)
        top_bar.addWidget(self.category_combo)

        top_bar.addStretch()

        # Save Button
        self.save_btn = QPushButton(" Save")
        self.save_btn.setIcon(get_vector_icon("save", color="#ffffff", size=13))
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #cbd5e1; color: #94a3b8; }"
        )
        self.save_btn.clicked.connect(self._save_changes)
        top_bar.addWidget(self.save_btn)

        # Copy Active Button
        self.copy_main_btn = QPushButton(" Copy")
        self.copy_main_btn.setIcon(get_vector_icon("copy", color="#334155", size=13))
        self.copy_main_btn.setStyleSheet(
            "QPushButton { background: #ffffff; color: #334155; border: 1px solid #cbd5e1; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #f1f5f9; }"
        )
        self.copy_main_btn.clicked.connect(self._copy_current_active_text)
        top_bar.addWidget(self.copy_main_btn)

        # Delete Button
        self.delete_btn = QPushButton(" Delete")
        self.delete_btn.setIcon(get_vector_icon("trash-2", color="#dc2626", size=13))
        self.delete_btn.setStyleSheet(
            "QPushButton { background: #fff1f2; color: #e11d48; border: 1px solid #fecdd3; border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 500; }"
            "QPushButton:hover { background: #ffe4e6; }"
        )
        self.delete_btn.clicked.connect(self._delete_current_note)
        top_bar.addWidget(self.delete_btn)

        layout.addLayout(top_bar)

        # Context Card (Time, App, Window title, Tags)
        meta_frame = QFrame()
        meta_frame.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px 10px; }"
        )
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.setSpacing(4)

        meta_row1 = QHBoxLayout()
        meta_row1.setSpacing(6)
        time_ico = QLabel()
        time_ico.setPixmap(get_vector_pixmap("clock", color="#64748b", size=13))
        meta_row1.addWidget(time_ico)
        self.meta_time_label = QLabel("Captured: -")
        self.meta_time_label.setStyleSheet("font-size: 11px; font-weight: 600; color: #1e293b;")
        meta_row1.addWidget(self.meta_time_label)

        meta_row1.addSpacing(12)
        app_ico = QLabel()
        app_ico.setPixmap(get_vector_pixmap("app-window", color="#64748b", size=13))
        meta_row1.addWidget(app_ico)
        self.meta_app_label = QLabel("Application: -")
        self.meta_app_label.setStyleSheet("font-size: 11px; color: #475569;")
        meta_row1.addWidget(self.meta_app_label)
        meta_row1.addStretch()
        meta_layout.addLayout(meta_row1)

        self.meta_window_label = QLabel("Window Title: -")
        self.meta_window_label.setWordWrap(True)
        self.meta_window_label.setStyleSheet("font-size: 11px; color: #64748b; margin-left: 2px;")
        meta_layout.addWidget(self.meta_window_label)

        # Tags and Category labels
        tags_sub_row = QHBoxLayout()
        tags_sub_row.setContentsMargins(0, 2, 0, 0)
        tags_sub_row.setSpacing(8)

        tag_ico = QLabel()
        tag_ico.setPixmap(get_vector_pixmap("tag", color="#6366f1", size=12))
        tags_sub_row.addWidget(tag_ico)

        self.meta_tags_label = QLabel("Tags: None")
        self.meta_tags_label.setStyleSheet("font-size: 11px; color: #6366f1; font-weight: 500;")
        tags_sub_row.addWidget(self.meta_tags_label)
        tags_sub_row.addStretch()

        self.meta_category_label = QLabel("Category: Note")
        self.meta_category_label.setStyleSheet("font-size: 11px; color: #475569; font-weight: 600;")
        tags_sub_row.addWidget(self.meta_category_label)

        meta_layout.addLayout(tags_sub_row)
        layout.addWidget(meta_frame)

        # Screenshot Preview Card (if attached)
        self.screenshot_frame = QFrame()
        self.screenshot_frame.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px; }"
        )
        screenshot_layout = QHBoxLayout(self.screenshot_frame)
        screenshot_layout.setContentsMargins(6, 6, 6, 6)
        screenshot_layout.setSpacing(10)

        self.screenshot_thumb = QLabel()
        self.screenshot_thumb.setFixedSize(110, 68)
        self.screenshot_thumb.setScaledContents(True)
        self.screenshot_thumb.setStyleSheet("border: 1px solid #cbd5e1; border-radius: 4px;")
        screenshot_layout.addWidget(self.screenshot_thumb)

        screenshot_info_layout = QVBoxLayout()
        screenshot_info_layout.setSpacing(4)
        self.screenshot_title = QLabel("Attached Screenshot")
        self.screenshot_title.setStyleSheet("font-size: 11px; font-weight: 700; color: #334155;")
        screenshot_info_layout.addWidget(self.screenshot_title)

        screenshot_actions = QHBoxLayout()
        screenshot_actions.setSpacing(6)
        self.view_screenshot_btn = QPushButton(" Open Image")
        self.view_screenshot_btn.setIcon(get_vector_icon("external-link", color="#334155", size=12))
        self.view_screenshot_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; background: white; border: 1px solid #cbd5e1; border-radius: 4px; }"
            "QPushButton:hover { background: #f1f5f9; }"
        )
        self.view_screenshot_btn.clicked.connect(self._open_screenshot_file)
        screenshot_actions.addWidget(self.view_screenshot_btn)

        self.delete_screenshot_btn = QPushButton(" Remove")
        self.delete_screenshot_btn.setIcon(get_vector_icon("x", color="#dc2626", size=12))
        self.delete_screenshot_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 3px 8px; color: #dc2626; background: #fff1f2; border: 1px solid #fecdd3; border-radius: 4px; }"
            "QPushButton:hover { background: #ffe4e6; }"
        )
        self.delete_screenshot_btn.clicked.connect(self._remove_screenshot_from_note)
        screenshot_actions.addWidget(self.delete_screenshot_btn)
        screenshot_actions.addStretch()

        screenshot_info_layout.addLayout(screenshot_actions)
        screenshot_layout.addLayout(screenshot_info_layout)
        screenshot_layout.addStretch()

        self.screenshot_frame.setVisible(False)
        layout.addWidget(self.screenshot_frame)

        # Tabbed Text View: Original vs Refined
        self.text_tabs = QTabWidget()
        self.text_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #e2e8f0; border-radius: 6px; background: white; }"
            "QTabBar::tab { padding: 6px 16px; font-size: 12px; font-weight: 500; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #64748b; background: #f1f5f9; margin-right: 4px; }"
            "QTabBar::tab:selected { background: white; color: #2563eb; font-weight: 700; border: 1px solid #e2e8f0; border-bottom: none; }"
        )

        # Tab 1: Original Transcript
        tab1_widget = QWidget()
        tab1_layout = QVBoxLayout(tab1_widget)
        tab1_layout.setContentsMargins(8, 8, 8, 8)
        tab1_layout.setSpacing(6)

        tab1_header = QHBoxLayout()
        self.edited_badge = QLabel("Edited manually")
        self.edited_badge.setStyleSheet(
            "background: #fef3c7; color: #92400e; border-radius: 3px; padding: 1px 6px; font-size: 10px; font-weight: 600;"
        )
        self.edited_badge.setVisible(False)
        tab1_header.addWidget(self.edited_badge)
        tab1_header.addStretch()

        self.copy_original_btn = QPushButton(" Copy Original")
        self.copy_original_btn.setIcon(get_vector_icon("copy", color="#475569", size=12))
        self.copy_original_btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; font-size: 11px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 4px; }"
            "QPushButton:hover { background: #f1f5f9; }"
        )
        self.copy_original_btn.clicked.connect(self._copy_original_transcript)
        tab1_header.addWidget(self.copy_original_btn)
        tab1_layout.addLayout(tab1_header)

        self.transcript_edit = QPlainTextEdit()
        self.transcript_edit.setStyleSheet(
            "QPlainTextEdit { border: none; font-size: 13px; line-height: 1.45; color: #0f172a; background: transparent; padding: 4px; }"
        )
        self.transcript_edit.textChanged.connect(self._on_text_modified)
        tab1_layout.addWidget(self.transcript_edit)

        self.original_box = QLabel()
        self.original_box.setWordWrap(True)
        self.original_box.setStyleSheet(
            "background: #f8fafc; color: #64748b; border: 1px dashed #cbd5e1; border-radius: 4px; padding: 6px; font-size: 11px;"
        )
        self.original_box.setVisible(False)
        tab1_layout.addWidget(self.original_box)

        self.text_tabs.addTab(tab1_widget, "Original Transcript")

        # Tab 2: Refined Text
        tab2_widget = QWidget()
        tab2_layout = QVBoxLayout(tab2_widget)
        tab2_layout.setContentsMargins(8, 8, 8, 8)
        tab2_layout.setSpacing(6)

        tab2_header = QHBoxLayout()
        self.processed_by_label = QLabel("Method: None")
        self.processed_by_label.setStyleSheet("color: #64748b; font-size: 11px;")
        tab2_header.addWidget(self.processed_by_label)
        tab2_header.addStretch()

        self.refine_btn = QPushButton(" Refine with AI")
        self.refine_btn.setIcon(get_vector_icon("sparkles", color="#166534", size=13))
        self.refine_btn.setStyleSheet(
            "QPushButton { padding: 3px 9px; font-size: 11px; font-weight: 600; background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; border-radius: 4px; }"
            "QPushButton:hover { background: #dcfce7; }"
        )
        self.refine_btn.clicked.connect(self._run_text_refinement)
        tab2_header.addWidget(self.refine_btn)

        self.copy_processed_btn = QPushButton(" Copy Refined")
        self.copy_processed_btn.setIcon(get_vector_icon("copy", color="#475569", size=12))
        self.copy_processed_btn.setStyleSheet(
            "QPushButton { padding: 3px 8px; font-size: 11px; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 4px; }"
            "QPushButton:hover { background: #f1f5f9; }"
        )
        self.copy_processed_btn.clicked.connect(self._copy_processed_text)
        tab2_header.addWidget(self.copy_processed_btn)
        tab2_layout.addLayout(tab2_header)

        self.processed_edit = QPlainTextEdit()
        self.processed_edit.setStyleSheet(
            "QPlainTextEdit { border: none; font-size: 13px; line-height: 1.45; color: #0f172a; background: transparent; padding: 4px; }"
        )
        self.processed_edit.textChanged.connect(self._on_processed_text_modified)
        tab2_layout.addWidget(self.processed_edit)

        self.text_tabs.addTab(tab2_widget, "Refined Text")
        layout.addWidget(self.text_tabs)

        return pane

    def _build_settings_panel(self) -> None:
        self.settings_panel = QFrame()
        self.settings_panel.setStyleSheet(
            "QFrame { background: #ffffff; border-bottom: 1px solid #e2e8f0; padding: 10px 16px; }"
        )
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        settings_layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel("Application Settings")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #0f172a;")
        title_row.addWidget(title_lbl)
        title_row.addStretch()

        close_btn = QPushButton("✕ Close Settings")
        close_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #64748b; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { color: #0f172a; }"
        )
        close_btn.clicked.connect(lambda: self._on_toggle_settings_bar(False))
        title_row.addWidget(close_btn)
        settings_layout.addLayout(title_row)

        row1 = QHBoxLayout()
        row1.setSpacing(20)
        self.overlay_cb = QCheckBox("Show Floating Recording Overlay")
        self.overlay_cb.setChecked(self.settings.overlay_visible)
        self.overlay_cb.toggled.connect(self._on_overlay_cb_toggled)
        row1.addWidget(self.overlay_cb)

        self.notifications_cb = QCheckBox("Show Windows Notification Popups")
        self.notifications_cb.setChecked(self.settings.show_notifications)
        self.notifications_cb.toggled.connect(self._on_notifications_cb_toggled)
        row1.addWidget(self.notifications_cb)

        self.auto_copy_cb = QCheckBox("Auto-copy to clipboard on capture")
        self.auto_copy_cb.setChecked(self.settings.auto_copy_clipboard)
        self.auto_copy_cb.toggled.connect(self._on_auto_copy_toggled)
        row1.addWidget(self.auto_copy_cb)
        row1.addStretch()
        settings_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(16)

        ver_lbl = QLabel("Default Text Version:")
        ver_lbl.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        row2.addWidget(ver_lbl)
        self.version_combo = QComboBox()
        self.version_combo.addItem("Original Transcript", "original")
        self.version_combo.addItem("Processed Text", "processed")
        if self.settings.default_text_version == "processed":
            self.version_combo.setCurrentIndex(1)
        self.version_combo.currentIndexChanged.connect(self._on_version_combo_changed)
        row2.addWidget(self.version_combo)

        model_lbl = QLabel("Whisper Model:")
        model_lbl.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        row2.addWidget(model_lbl)
        self.model_combo = QComboBox()
        for label, val in [
            ("small (Empfohlen: ~0.8s, beste Balance auf CPU — 460MB)", "small"),
            ("base (Blitzschnell: ~0.3s, geringere Genauigkeit — 74MB)", "base"),
            ("medium (~4-6s auf CPU, sehr hohe Genauigkeit — 1.5GB)", "medium"),
            ("large-v3-turbo (Rechenintensiv: ~15-20s auf CPU — 1.6GB)", "large-v3-turbo"),
        ]:
            self.model_combo.addItem(label, val)
        idx = self.model_combo.findData(self.settings.whisper_model or "small")
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        row2.addWidget(self.model_combo)

        lang_lbl = QLabel("Sprache:")
        lang_lbl.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        row2.addWidget(lang_lbl)
        self.lang_combo = QComboBox()
        for label, val in [
            ("Deutsch (Empfohlen für Denglisch)", "de"),
            ("English", "en"),
            ("Automatisch erkennen (Auto)", "auto"),
        ]:
            self.lang_combo.addItem(label, val)
        l_idx = self.lang_combo.findData(self.settings.whisper_language or "de")
        if l_idx >= 0:
            self.lang_combo.setCurrentIndex(l_idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        row2.addWidget(self.lang_combo)

        row2.addStretch()
        settings_layout.addLayout(row2)

        # Row 3: Refinement Engine & LLM Model
        row3 = QHBoxLayout()
        row3.setSpacing(16)

        engine_lbl = QLabel("Text-Aufbereitung:")
        engine_lbl.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        row3.addWidget(engine_lbl)
        self.engine_combo = QComboBox()
        for label, val in [
            ("Lokale KI (LLM — Grammatik, Kontext & Auto-Tags)", "llm"),
            ("Regelbasiert (Schnell, einfache Bereinigung)", "rules"),
        ]:
            self.engine_combo.addItem(label, val)
        e_idx = self.engine_combo.findData(self.settings.refinement_engine or "llm")
        if e_idx >= 0:
            self.engine_combo.setCurrentIndex(e_idx)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_combo_changed)
        row3.addWidget(self.engine_combo)

        llm_lbl = QLabel("LLM Modell:")
        llm_lbl.setStyleSheet("color: #475569; font-size: 12px; font-weight: 500;")
        row3.addWidget(llm_lbl)
        self.llm_model_combo = QComboBox()
        for label, val in [
            ("Qwen 2.5 0.5B (~2-3s, schnell & leicht)", "qwen2.5-0.5b"),
            ("Qwen 2.5 1.5B (~8-9s, präzise Formulierungen)", "qwen2.5-1.5b"),
        ]:
            self.llm_model_combo.addItem(label, val)
        m_idx = self.llm_model_combo.findData(self.settings.llm_model or "qwen2.5-0.5b")
        if m_idx >= 0:
            self.llm_model_combo.setCurrentIndex(m_idx)
        self.llm_model_combo.currentIndexChanged.connect(self._on_llm_model_combo_changed)
        row3.addWidget(self.llm_model_combo)

        row3.addStretch()
        settings_layout.addLayout(row3)

        self.settings_panel.setVisible(False)

    # Sidebar Filter Handling
    def _on_sidebar_item_clicked(self, key: str) -> None:
        for k, item in self.sidebar_items.items():
            item.set_active(k == key)

        if key == "all":
            self._active_filter_category = None
            self._active_filter_screenshot = None
            self.filter_indicator_frame.setVisible(False)
        elif key == "screenshot":
            self._active_filter_category = None
            self._active_filter_screenshot = True
            self.filter_indicator_label.setText("Showing: Screenshots")
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

        # Update Tab 1 (Transcript)
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

        # Update Tab 2 (Processed Text)
        self.processed_edit.blockSignals(True)
        self.processed_edit.setPlainText(note.text_processed or "")
        self.processed_edit.blockSignals(False)
        self.processed_by_label.setText(f"Method: {note.processed_by or 'None'}")
        self.copy_processed_btn.setEnabled(bool(note.text_processed))

        # Auto-switch tab based on default version preference
        if self.settings.default_text_version == "processed" and note.is_processed:
            self.text_tabs.setCurrentIndex(1)
        else:
            self.text_tabs.setCurrentIndex(0)

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

        self.processed_edit.blockSignals(True)
        self.processed_edit.setPlainText("")
        self.processed_edit.blockSignals(False)

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
            self.status_bar.showMessage(f"Category updated to '{new_cat or 'Uncategorized'}'.", 3000)

    def _on_text_modified(self) -> None:
        if not self.selected_note:
            return
        modified = self.transcript_edit.toPlainText().strip() != self.selected_note.transcript.strip()
        self.save_btn.setEnabled(modified)

    def _on_processed_text_modified(self) -> None:
        if not self.selected_note:
            return
        orig_proc = (self.selected_note.text_processed or "").strip()
        modified = self.processed_edit.toPlainText().strip() != orig_proc
        self.save_btn.setEnabled(modified)

    def _save_changes(self) -> None:
        if not self.selected_note:
            return
        new_text = self.transcript_edit.toPlainText().strip()
        new_proc = self.processed_edit.toPlainText().strip()

        updated = self.repository.update_transcript(self.selected_note.id, new_text)
        if new_proc:
            updated = self.repository.update_processed_text(self.selected_note.id, new_proc, self.selected_note.processed_by or "manual")

        if updated:
            self.selected_note = updated
            self.note_updated.emit(updated.id, new_text)
            self.refresh_notes()
            self.status_bar.showMessage("Changes saved successfully.", 3000)

    def _run_text_refinement(self) -> None:
        """Run text processing and categorization on current note's transcript."""
        if not self.selected_note:
            return
        res = self._text_processor.process(
            self.selected_note.transcript,
            context_app=self.selected_note.application,
            context_window=self.selected_note.window_title,
            language=self.settings.whisper_language,
        )
        if res.success and (res.text or res.category):
            updated = self.repository.update_processed_text(
                self.selected_note.id,
                res.text or self.selected_note.transcript,
                res.processor_id,
                category=res.category,
                tags=res.tags,
            )
            if updated:
                self.selected_note = updated
                self.processed_edit.setPlainText(res.text or self.selected_note.transcript)
                self.processed_by_label.setText(f"Method: {res.processor_id}")
                self.copy_processed_btn.setEnabled(True)

                self.category_combo.blockSignals(True)
                idx = self.category_combo.findData(updated.category or "")
                if idx >= 0:
                    self.category_combo.setCurrentIndex(idx)
                self.category_combo.blockSignals(False)

                self.meta_category_label.setText(f"Category: {updated.category or '(None)'}")
                self.meta_tags_label.setText(f"Tags: {', '.join('#' + t for t in updated.tags)}" if updated.tags else "Tags: None")
                self.refresh_notes()
                self.status_bar.showMessage("Text refined & categorized successfully.", 3000)

    def _copy_original_transcript(self) -> None:
        text = self.transcript_edit.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage("Original transcript copied to clipboard.", 3000)

    def _copy_processed_text(self) -> None:
        text = self.processed_edit.toPlainText().strip()
        if text:
            QApplication.clipboard().setText(text)
            self.status_bar.showMessage("Processed text copied to clipboard.", 3000)

    def _copy_current_active_text(self) -> None:
        if self.text_tabs.currentIndex() == 1 and self.processed_edit.toPlainText().strip():
            self._copy_processed_text()
        else:
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
            "Remove and delete this screenshot?",
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
            "Delete Note",
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
                self.status_bar.showMessage("Note deleted.", 3000)

    def _update_status_bar(self, filtered_count: int | None = None) -> None:
        total = self.repository.count()
        if filtered_count is not None and (self.search_input.text().strip() or self._active_filter_category or self._active_filter_screenshot):
            self.status_bar.showMessage(f"{filtered_count} of {total} thoughts shown")
        else:
            self.status_bar.showMessage(f"{total} thoughts saved")

    # Settings callbacks
    def _on_toggle_settings_bar(self, checked: bool) -> None:
        self.settings_panel.setVisible(checked)
        self.toggle_settings_btn.setChecked(checked)

    def open_settings(self) -> None:
        self.toggle_settings_btn.setChecked(True)
        self.settings_panel.setVisible(True)

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
        self.status_bar.showMessage("Windows notifications enabled." if checked else "Windows notifications disabled.", 2500)

    def update_overlay_checkbox(self, visible: bool) -> None:
        self.overlay_cb.blockSignals(True)
        self.overlay_cb.setChecked(visible)
        self.overlay_cb.blockSignals(False)

    def update_notifications_checkbox(self, enabled: bool) -> None:
        self.notifications_cb.blockSignals(True)
        self.notifications_cb.setChecked(enabled)
        self.notifications_cb.blockSignals(False)

    def _on_version_combo_changed(self, idx: int) -> None:
        val = self.version_combo.currentData()
        self.settings.default_text_version = val
        self.settings.save()
        self.refresh_notes()
        self.status_bar.showMessage(f"Default text version: {self.version_combo.currentText()}.", 2500)

    def _on_model_combo_changed(self, idx: int) -> None:
        model = self.model_combo.currentData()
        self.settings.whisper_model = model
        self.settings.save()
        self.whisper_model_changed.emit(model)
        self.status_bar.showMessage(f"Whisper Model: '{model}'. Preloading...", 3000)

    def _on_lang_combo_changed(self, idx: int) -> None:
        lang = self.lang_combo.currentData()
        self.settings.whisper_language = lang
        self.settings.save()
        self.whisper_language_changed.emit(lang)
        self.status_bar.showMessage(f"Language: '{self.lang_combo.currentText()}'.", 2500)

    def _on_engine_combo_changed(self, idx: int) -> None:
        engine = self.engine_combo.currentData()
        self.settings.refinement_engine = engine
        self.settings.save()
        self.refinement_engine_changed.emit(engine)
        self.status_bar.showMessage(f"Engine: '{self.engine_combo.currentText()}'.", 2500)

    def _on_llm_model_combo_changed(self, idx: int) -> None:
        model = self.llm_model_combo.currentData()
        self.settings.llm_model = model
        self.settings.save()
        self.llm_model_changed.emit(model)
        self.status_bar.showMessage(f"LLM Model: '{model}'.", 2500)
