# tucknote
Capture a thought. Keep its context.

**Thought Capture** (`tucknote`) is a lightweight, local Windows desktop application that captures spontaneous thoughts via voice without having to leave your active application.

---

## Features & Workflow

1. **Global Hotkey (`Ctrl+Alt+Space`):**
   - Press once to start voice recording.
   - The app **immediately captures the active window context** (application name, process ID, and window title like `Visual Studio Code` or `msedge.exe`) before any focus changes occur.
   - Press again to stop recording.
2. **Local Transcription:**
   - Audio is transcribed locally on CPU (`int8`) using `faster-whisper`.
   - 100% offline — no cloud APIs, no external telemetry, and no network required after initial setup.
   - Multilingual support (out-of-the-box support for English, German, and others).
3. **SQLite Persistence:**
   - Transcripts are stored atomically in a local SQLite database along with UTC timestamp, app name, and window title.
   - Once saved, temporary audio files are immediately deleted.
4. **Searchable Library:**
   - Accessible via the system tray or launch with `--show-library`.
   - Chronological list (newest notes first).
   - Real-time search across transcript text, application name, and window title.
   - Edit notes (the original transcript is always preserved for reference) or delete them.
   - One-click copy to clipboard.

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
