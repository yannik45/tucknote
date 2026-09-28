"""Vector Icon Provider for Thought Capture (tucknote).

Renders crisp, lightweight, modern Lucide/Feather-style SVG vector icons into
QPixmap and QIcon instances at arbitrary sizes and colors with PySide6.QtSvg.
"""

from __future__ import annotations

from typing import Final
import PySide6.QtSvg as QtSvg
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap

# Lucide-style SVG path definitions (viewBox 0 0 24 24, stroke-width 2)
SVG_PATHS: Final[dict[str, str]] = {
    # Navigation & Categories
    "inbox": (
        '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
    ),
    "layers": (
        '<polygon points="12 2 2 7 12 12 22 7 12 2"/>'
        '<polyline points="2 17 12 22 22 17"/>'
        '<polyline points="2 12 12 17 22 12"/>'
    ),
    "check-square": (
        '<path d="m9 11 3 3L22 4"/>'
        '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'
    ),
    "bug": (
        '<path d="m8 2 1.88 1.88"/>'
        '<path d="M14.12 3.88 16 2"/>'
        '<path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/>'
        '<path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/>'
        '<path d="M12 20v-9"/>'
        '<path d="M6.53 9C4.6 8.8 3 7.1 3 5"/>'
        '<path d="M6 13H2"/>'
        '<path d="M3 21c0-2.1 1.7-3.9 3.8-4"/>'
        '<path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/>'
        '<path d="M22 13h-4"/>'
        '<path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/>'
    ),
    "lightbulb": (
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>'
        '<path d="M9 18h6"/>'
        '<path d="M10 22h4"/>'
    ),
    "file-text": (
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M10 9H8"/>'
        '<path d="M16 13H8"/>'
        '<path d="M16 17H8"/>'
    ),
    "image": (
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>'
        '<circle cx="9" cy="9" r="2"/>'
        '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>'
    ),
    "camera": (
        '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>'
        '<circle cx="12" cy="13" r="3"/>'
    ),
    # Actions & Utilities
    "search": (
        '<circle cx="11" cy="11" r="8"/>'
        '<path d="m21 21-4.3-4.3"/>'
    ),
    "sparkles": (
        '<path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/>'
        '<path d="M20 3v4"/>'
        '<path d="M22 5h-4"/>'
    ),
    "copy": (
        '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
        '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>'
    ),
    "check": (
        '<polyline points="20 6 9 17 4 12"/>'
    ),
    "trash-2": (
        '<path d="M3 6h18"/>'
        '<path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>'
        '<path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>'
        '<line x1="10" x2="10" y1="11" y2="17"/>'
        '<line x1="14" x2="14" y1="11" y2="17"/>'
    ),
    "settings": (
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "external-link": (
        '<path d="M15 3h6v6"/>'
        '<path d="M10 14 21 3"/>'
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
    ),
    "x": (
        '<path d="M18 6 6 18"/>'
        '<path d="m6 6 12 12"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="12 6 12 12 16 14"/>'
    ),
    "app-window": (
        '<rect x="2" y="4" width="20" height="16" rx="2"/>'
        '<path d="M10 4v4"/>'
        '<path d="M2 8h20"/>'
        '<path d="M6 4v4"/>'
    ),
    "tag": (
        '<path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/>'
        '<path d="M7 7h.01"/>'
    ),
    "save": (
        '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/>'
        '<path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/>'
        '<path d="M7 3v4a1 1 0 0 0 1 1h7"/>'
    ),
    "mic": (
        '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>'
        '<path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'
        '<line x1="12" x2="12" y1="19" y2="22"/>'
    ),
    "chevron-right": (
        '<polyline points="9 18 15 12 9 6"/>'
    ),
    "chevron-down": (
        '<polyline points="6 9 12 15 18 9"/>'
    ),
    "filter": (
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'
    ),
}

_PIXMAP_CACHE: dict[tuple[str, str, int, float], QPixmap] = {}


def get_chevron_icon_path() -> str:
    """Ensure a clean chevron-down PNG icon is saved on disk for QSS use and return its file URI."""
    from tucknote.config import get_data_dir
    assets_dir = get_data_dir() / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    icon_path = assets_dir / "chevron-down.png"
    if not icon_path.exists():
        pix = get_vector_pixmap("chevron-down", color="#71717a", size=16, stroke_width=2.2)
        pix.save(str(icon_path), "PNG")
    return icon_path.as_posix()



def get_vector_pixmap(name: str, color: str = "#64748b", size: int = 16, stroke_width: float = 2.0) -> QPixmap:
    """Render a vector icon into a high-DPI crisp QPixmap."""
    cache_key = (name, color, size, stroke_width)
    if cache_key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[cache_key]

    inner = SVG_PATHS.get(name, SVG_PATHS["file-text"])
    svg_str = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" stroke-linejoin="round">'
        f'{inner}'
        f'</svg>'
    )

    renderer = QtSvg.QSvgRenderer(QByteArray(svg_str.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    _PIXMAP_CACHE[cache_key] = pix
    return pix


def get_vector_icon(name: str, color: str = "#52525b", size: int = 16, stroke_width: float = 1.6) -> QIcon:
    """Return a QIcon wrapping the rendered vector pixmap."""
    pix = get_vector_pixmap(name, color=color, size=size, stroke_width=stroke_width)
    return QIcon(pix)


# Category color and icon helpers — Minimalist Apple / ChatGPT monochromatic palette
CATEGORY_THEMES: Final[dict[str, dict[str, str]]] = {
    "Task": {
        "label": "Task",
        "icon": "check-square",
        "color": "#18181b",
        "bg": "#f4f4f5",
        "border": "#e4e4e7",
    },
    "Bug": {
        "label": "Bug",
        "icon": "bug",
        "color": "#3f3f46",
        "bg": "#f4f4f5",
        "border": "#e4e4e7",
    },
    "Idea": {
        "label": "Idea",
        "icon": "lightbulb",
        "color": "#52525b",
        "bg": "#f4f4f5",
        "border": "#e4e4e7",
    },
    "Note": {
        "label": "Note",
        "icon": "file-text",
        "color": "#71717a",
        "bg": "#f4f4f5",
        "border": "#e4e4e7",
    },
}
