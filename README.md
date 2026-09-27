# tucknote
Capture a thought. Keep its context.

**Thought Capture** (`tucknote`) is a lightweight, local Windows desktop application that captures spontaneous thoughts via voice without having to leave your active application.

---

## Features & Workflow

1. **Global Hotkey (`Ctrl+Alt+Space`):**
   - Press once to start voice recording.
   - The app **immediately captures the active window context** (application name, process ID, and window title like `Visual Studio Code` or `msedge.exe`) before any focus changes occur.
   - Press again to stop recording.
2. **Local Transcription & Speech Optimization:**
   - Audio is transcribed locally on CPU (`int8`) using `faster-whisper` (default model `small`).
   - Dynamic prompt priming injects tech vocabulary (`Antigravity`, `Recording`, `Clipboard`, `VS Code`, `GitHub`, `API`, `Git`, etc.) and active window context to eliminate misspellings.
   - Headroom peak audio normalization prevents phoneme hallucinations on quiet speech starts.
   - Language selection (`Deutsch (Empfohlen für Denglisch)`, `English`, `Auto-detect`) configurable directly in Settings.
3. **Local AI Post-Processing & Smart Categorization (100% Offline):**
   - Embedded local LLM engine powered by a portable `llama.cpp` runtime and Qwen 2.5 (`0.5B` or `1.5B`).
   - Corrects grammar, punctuation, and misheard technical words using active window context.
   - Automatically categorizes thoughts (`🔨 Task`, `🐛 Bug`, `💡 Idea`, `📝 Note`) and generates relevant `#tags`.
   - Fast deterministic rule-based fallback mode available for instant processing without LLMs.
4. **Floating Recording Overlay:**
   - Compact, semi-transparent pill widget floating unobtrusively above active windows.
   - Click to start/stop or cancel recordings, toggle screenshots, copy text, or access the Library.
   - Draggable across the desktop with automatic position saving between sessions.
   - Toggle visibility anytime via the system tray menu.
   - **Context-Safe:** Tucknote continuously monitors the active external application. Interacting with the overlay will *never* misattribute the note's context to Tucknote itself.
5. **Conscious Screenshot Capture:**
   - Optional one-click screenshot capture via the overlay before or during recording.
   - Automatically minimizes the overlay during capture to keep your notes clean.
   - Thumbnails are previewed immediately with an option to remove before saving.
   - Stored locally in `%LOCALAPPDATA%\tucknote\screenshots\` and automatically purged whenever a note is deleted.
6. **Dual Text Versions (Original & Refined):**
   - Transcripts preserve the raw audio verbatim (`transcript_original` is never altered).
   - Seamlessly switch between Original and Refined tabs in the Library view.
   - Both versions can be copied separately.
7. **Clipboard Integration:**
   - One-click copy buttons in both the floating overlay and the Library detail inspector.
   - Optional setting to automatically copy the final text to your clipboard upon successful transcription.
8. **SQLite Persistence & Migration (Schema v3):**
   - Auto-migrating SQLite storage with automatic migration from v1 and v2 to Schema v3.
   - Stores notes with UTC timestamps, application context, processed text, category, tags, and screenshot references.
   - Temporary audio files are safely cleaned up once transcribed.
9. **Searchable Library & Settings:**
   - Accessible via the tray menu (`Settings...`), floating overlay, or `--show-library`.
   - Chronological list with real-time search across original text, refined text, category, tags, app names, and window titles.
   - Configure Whisper Model (`small`, `base`, `medium`, `large-v3-turbo`), Language, Text Refinement Engine (`Local AI` or `Rule-based`), and LLM Model (`Qwen 0.5B` or `1.5B`) directly in the collapsible Settings panel.

---

## Requirements & Installation

- **Operating System:** Windows 10 / Windows 11 (64-bit)
- **Python:** Python 3.12+
- **Package Manager:** [`uv`](https://github.com/astral-sh/uv) (recommended)

### 1. Clone Repository & Navigate to Directory

```powershell
git clone https://github.com/yannik45/tucknote.git
cd tucknote
```

### 2. Install Dependencies with `uv`

```powershell
uv sync
```

*Note on Windows binaries:* The project uses `ctranslate2==4.4.0` and `PySide6`, pre-configured in `pyproject.toml` to run on Windows without requiring separate Visual C++ build tools.

---

## Running the Application

### Option A: Using the Runner Script (Recommended)

```powershell
.\run.ps1
```

Or open directly with the Library window:

```powershell
.\run.ps1 -ShowLibrary
```

*(You can also double-click [`run.bat`](run.bat) in Windows Explorer).*

### Option B: Using `uv run`

```powershell
uv run tucknote
```

To open directly with the Library window:

```powershell
uv run tucknote --show-library
```

### CLI Arguments

| Argument | Description | Default |
| --- | --- | --- |
| `--model MODEL` | Whisper model size (`tiny`, `base`, `small`, etc.) | `base` |
| `--hotkey HOTKEY` | Custom global hotkey combination | `Ctrl+Alt+Space` |
| `--show-library` | Open the Library window immediately on startup | `False` |

---

## System Tray Status Indicators

The tray icon indicates the current application state:

| State | Color / Icon | Description |
| --- | --- | --- |
| **Ready** | Blue circle | Idle and waiting for hotkey (`Ctrl+Alt+Space`) |
| **Recording** | Red pulsing dot | Recording in progress; press hotkey again to finish |
| **Processing** | Amber gear/ring | Transcribing audio locally and saving note |
| **Error** | Red warning badge | Error occurred; audio is preserved for retry or dismissal |

The tray context menu (right-click) also allows manual start/stop if the hotkey conflicts with another application.

---

## Storage & Privacy

- **SQLite Database:**  
  `%LOCALAPPDATA%\tucknote\notes.db`
- **Application Settings:**  
  `%LOCALAPPDATA%\tucknote\settings.json`
- **Screenshots:**  
  `%LOCALAPPDATA%\tucknote\screenshots\` (tied to notes; deleted automatically when a note is deleted).
- **Temporary Audio Recordings:**  
  `%LOCALAPPDATA%\tucknote\temp_audio\` (deleted automatically upon successful transcription; kept temporarily only if an inference error occurs to allow retrying).
- **Log Files:**  
  `%LOCALAPPDATA%\tucknote\logs\tucknote.log`
- **Privacy Guarantee:**  
  No audio data or transcribed thoughts are ever transmitted externally. In accordance with privacy specifications, logs never contain audio data or transcribed text.

---

## Running Tests

The test suite covers SQLite persistence, Win32 window context detection, audio recording, Whisper transcription, hotkey registration, and PySide6 UI:

```powershell
uv run pytest -v
```

---

## Known Considerations (MVP)

- **Elevated Windows:** Protected Windows running with higher privileges (e.g. Task Manager run as Administrator) restrict query permissions for standard user processes. In such cases, the window title is captured, while the executable name defaults to `None`.
- **File Names in Window Titles:** Many window titles include active filenames (e.g., `models.py - tucknote`). The MVP records the title as reported by Windows without speculative filesystem deductions.
- **Initial Download:** On first execution, `faster-whisper` downloads the selected model (~140 MB for `base`). Subsequent executions operate fully offline.
