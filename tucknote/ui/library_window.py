"""Library Window for Thought Capture (tucknote).

Displays notes chronologically, provides instant search, detail view,
editing, and deletion.
"""

from __future__ import annotations

import logging
from datetime import datetime
from PySide6.QtCore import Qt, Signal
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
)

from tucknote.storage.models import Note
from tucknote.storage.repository import NoteRepository

logger = logging.getLogger("tucknote")


class NoteListItemWidget(QWidget):
    """Custom compact card widget for each note in the list."""

    def __init__(self, note: Note, parent=None):
        super().__init__(parent)
        self.note = note

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        # Header: Timestamp + App badge
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Format local time
        local_dt = note.captured_at_local
        time_str = local_dt.strftime("%d %b %Y %H:%M")
        self.time_label = QLabel(time_str)
        self.time_label.setStyleSheet("color: #64748b; font-size: 11px; font-weight: bold;")
        header_layout.addWidget(self.time_label)

        header_layout.addStretch()

        if note.application:
            app_badge = QLabel(note.application)
            app_badge.setStyleSheet(
                "background-color: #e0e7ff; color: #3730a3; "
                "border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: bold;"
            )
            header_layout.addWidget(app_badge)

        layout.addLayout(header_layout)

        # Window title if present
        if note.window_title:
            title_text = note.window_title
            if len(title_text) > 45:
                title_text = title_text[:42] + "..."
            self.title_label = QLabel(f"🪟 {title_text}")
            self.title_label.setStyleSheet("color: #334155; font-size: 11px; font-weight: 500;")
            layout.addWidget(self.title_label)

        # Transcript preview (first 75 chars)
        preview_text = note.transcript.replace("\n", " ").strip()
        if len(preview_text) > 75:
            preview_text = preview_text[:72] + "..."
        if not preview_text:
            preview_text = "(No text)"
        self.preview_label = QLabel(preview_text)
        self.preview_label.setStyleSheet("color: #1e293b; font-size: 12px;")
        layout.addWidget(self.preview_label)


class LibraryWindow(QMainWindow):
    """Thought Capture Library desktop window."""

    note_deleted = Signal(str)
    note_updated = Signal(str, str)

    def __init__(self, repository: NoteRepository, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.selected_note: Note | None = None

        self.setWindowTitle("Thought Capture — Library")
        self.resize(850, 550)
        self.setMinimumSize(640, 400)

        self._init_ui()
        self.refresh_notes()

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 1. Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search thoughts, applications, or window titles...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setStyleSheet(
            "QLineEdit { padding: 8px 12px; font-size: 13px; border: 1px solid #cbd5e1; border-radius: 6px; }"
            "QLineEdit:focus { border: 1px solid #3b82f6; }"
        )
        search_layout.addWidget(self.search_input)
        main_layout.addLayout(search_layout)

        # 2. Main Content Splitter (Left: Note List, Right: Details)
        splitter = QSplitter(Qt.Horizontal)

        # Left pane: List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.note_list = QListWidget()
        self.note_list.setStyleSheet(
            "QListWidget { border: 1px solid #cbd5e1; border-radius: 6px; background: #ffffff; }"
            "QListWidget::item:selected { background: #eff6ff; border-radius: 4px; }"
            "QListWidget::item:hover:!selected { background: #f8fafc; border-radius: 4px; }"
        )
        self.note_list.currentRowChanged.connect(self._on_note_selected)
        left_layout.addWidget(self.note_list)
        splitter.addWidget(left_widget)

        # Right pane: Details
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(8)

        # Metadata Header Frame
        meta_frame = QFrame()
        meta_frame.setStyleSheet(
            "QFrame { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 8px; }"
        )
        meta_layout = QVBoxLayout(meta_frame)
        meta_layout.setContentsMargins(8, 8, 8, 8)
        meta_layout.setSpacing(4)

        self.meta_time_label = QLabel("Captured: -")
        self.meta_time_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #1e293b;")
        meta_layout.addWidget(self.meta_time_label)

        self.meta_app_label = QLabel("Application: -")
        self.meta_app_label.setStyleSheet("font-size: 12px; color: #475569;")
        meta_layout.addWidget(self.meta_app_label)

        self.meta_window_label = QLabel("Window Title: -")
        self.meta_window_label.setWordWrap(True)
        self.meta_window_label.setStyleSheet("font-size: 12px; color: #475569;")
        meta_layout.addWidget(self.meta_window_label)

        right_layout.addWidget(meta_frame)

        # Editable Transcript Field
        transcript_header = QHBoxLayout()
        transcript_title = QLabel("Transcript (editable):")
        transcript_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #334155;")
        transcript_header.addWidget(transcript_title)

        self.edited_badge = QLabel("Edited (Original preserved)")
        self.edited_badge.setStyleSheet(
            "background: #fef3c7; color: #92400e; border-radius: 3px; padding: 1px 4px; font-size: 10px;"
        )
        self.edited_badge.setVisible(False)
        transcript_header.addWidget(self.edited_badge)
        transcript_header.addStretch()
        right_layout.addLayout(transcript_header)

        self.transcript_edit = QPlainTextEdit()
        self.transcript_edit.setStyleSheet(
            "QPlainTextEdit { border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; font-size: 13px; line-height: 1.4; background: #ffffff; }"
            "QPlainTextEdit:focus { border: 1px solid #3b82f6; }"
        )
        self.transcript_edit.textChanged.connect(self._on_text_modified)
        right_layout.addWidget(self.transcript_edit)

        # Original Transcript reference box (shown when edited)
        self.original_box = QLabel()
        self.original_box.setWordWrap(True)
        self.original_box.setStyleSheet(
            "background: #f1f5f9; color: #64748b; border: 1px dashed #cbd5e1; border-radius: 4px; padding: 6px; font-size: 11px;"
        )
        self.original_box.setVisible(False)
        right_layout.addWidget(self.original_box)

        # Action Buttons
        btn_layout = QHBoxLayout()

        self.save_btn = QPushButton("💾 Save Changes")
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            "QPushButton { background: #2563eb; color: white; border: none; border-radius: 5px; padding: 6px 12px; font-weight: 500; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #94a3b8; }"
        )
        self.save_btn.clicked.connect(self._save_changes)
        btn_layout.addWidget(self.save_btn)

        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setStyleSheet(
            "QPushButton { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; border-radius: 5px; padding: 6px 12px; }"
            "QPushButton:hover { background: #e2e8f0; }"
        )
        self.copy_btn.clicked.connect(self._copy_to_clipboard)
        btn_layout.addWidget(self.copy_btn)

        btn_layout.addStretch()

        self.delete_btn = QPushButton("🗑️ Delete")
        self.delete_btn.setStyleSheet(
            "QPushButton { background: #fee2e2; color: #dc2626; border: 1px solid #fca5a5; border-radius: 5px; padding: 6px 12px; }"
            "QPushButton:hover { background: #fecaca; }"
        )
        self.delete_btn.clicked.connect(self._delete_current_note)
        btn_layout.addWidget(self.delete_btn)

        right_layout.addLayout(btn_layout)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        main_layout.addWidget(splitter)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status_bar()

    def refresh_notes(self) -> None:
        """Reload notes from repository using current search filter."""
        query = self.search_input.text()
        notes = self.repository.search(query)

        current_id = self.selected_note.id if self.selected_note else None

        self.note_list.clear()
        found_idx = -1

        for idx, note in enumerate(notes):
            item = QListWidgetItem(self.note_list)
            card = NoteListItemWidget(note)
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
        self.meta_time_label.setText(f"Captured: {local_dt.strftime('%d %b %Y %H:%M:%S')} (local)")
        self.meta_app_label.setText(f"Application: {note.application or '(not detected)'}")
        self.meta_window_label.setText(f"Window Title: {note.window_title or '(no title)'}")

        # Update transcript
        self.transcript_edit.blockSignals(True)
        self.transcript_edit.setPlainText(note.transcript)
        self.transcript_edit.blockSignals(False)

        # Original transcript
        if note.is_edited:
            self.edited_badge.setVisible(True)
            self.original_box.setVisible(True)
            self.original_box.setText(f"Original Transcript:\n{note.original_transcript}")
        else:
            self.edited_badge.setVisible(False)
            self.original_box.setVisible(False)

        self.save_btn.setEnabled(False)
        self.copy_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)

    def _clear_detail_view(self) -> None:
        self.selected_note = None
        self.meta_time_label.setText("Captured: -")
        self.meta_app_label.setText("Application: -")
        self.meta_window_label.setText("Window Title: -")
        self.transcript_edit.blockSignals(True)
        self.transcript_edit.setPlainText("")
        self.transcript_edit.blockSignals(False)
        self.edited_badge.setVisible(False)
        self.original_box.setVisible(False)
        self.save_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)

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
            self.status_bar.showMessage("Note updated successfully.", 3000)

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

    def _copy_to_clipboard(self) -> None:
        text = self.transcript_edit.toPlainText().strip()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.status_bar.showMessage("Transcript copied to clipboard.", 3000)

    def _update_status_bar(self, filtered_count: int | None = None) -> None:
        total = self.repository.count()
        if filtered_count is not None and self.search_input.text().strip():
            self.status_bar.showMessage(f"{filtered_count} of {total} thoughts found")
        else:
            self.status_bar.showMessage(f"{total} thoughts saved")
