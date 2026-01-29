# CT Acquisition and Reconstruction GUI

A graphical interface for controlling CT image acquisition and running reconstruction algorithms.

## Quick Start

```powershell
cd c:\Users\joaomartimreis\Desktop\Joao_CT\GUI
python main.py
```

## Requirements

- Python 3.8+
- PySide6
- Camera SDK modules (in `S2I_External_Trigger_detector_image_acquisition`)

Install dependencies:
```powershell
pip install PySide6
```

---

## How the GUI Freezing Problem Was Solved

### The Problem
When clicking "Start Acquisition", the GUI would freeze and show "Not Responding".
This happened because:

1. **Python's GIL (Global Interpreter Lock)**: Even with threading (QThread), only one thread can execute Python code at a time. When the camera SDK blocks waiting for hardware, it holds the GIL and the GUI thread can't update.

2. **Camera SDK Blocking**: Functions like `open_camera()`, `AcquireImage()` wait for hardware responses and can block for seconds.

3. **Logging Overhead**: Every `logging.info()` was trying to update the GUI, overwhelming the main thread.

### The Solution: Multiprocessing

Instead of using threads, the acquisition runs in a **completely separate process**:

```
┌─────────────────────────────────────────────────────────────┐
│                   MAIN PROCESS (GUI)                        │
│  • Qt Event Loop (handles UI)                               │
│  • Serial Handler (async)                                   │
│  • Log View (updated via timer)                             │
│                         │                                   │
│     QTimer polls every 100ms (non-blocking)                 │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         multiprocessing.Queue (results)             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ Messages
                          │
┌─────────────────────────────────────────────────────────────┐
│              ACQUISITION PROCESS (Separate!)                │
│  • Own Python interpreter                                   │
│  • Own GIL (no conflict with GUI)                          │
│  • Camera SDK (can block freely)                           │
│  • Image processing and saving                             │
└─────────────────────────────────────────────────────────────┘
```

**Why this works:**
- Each process has its **own GIL** → no blocking conflicts
- Camera can wait forever → GUI doesn't care
- Communication via `multiprocessing.Queue` → process-safe
- GUI polls queue with `QTimer` → non-blocking

**Key files for this solution:**
- `workers.py` - Contains `AcquisitionWorker` using multiprocessing
- `logging_utils.py` - Thread-safe log queue
- `config.py` - Performance settings (flush intervals, buffer sizes)

---

## File Structure

```
GUI/
├── main.py            # Entry point - RUN THIS FILE
├── config.py          # Configuration constants and paths
├── logging_utils.py   # Thread-safe logging utilities
├── workers.py         # Background workers (acquisition, reconstruction)
├── serial_handler.py  # STM32 serial communication
├── main_window.py     # Main GUI window and UI logic
└── README.md          # This file
```

---

## Module Descriptions

### `main.py`
**Entry point** for the application. Initializes the Qt application, logging system, and main window.

### `config.py`
**All configuration constants** in one place:
- File paths (acquisition modules, defect maps, reconstruction root)
- Reconstruction configs (DEFAULT_RECON_CONFIG, FBP_RECON_CONFIG)
- GUI settings (log buffer sizes, flush intervals)
- Iterative algorithm list

**To change settings**, edit this file:
```python
# Example: Enable log mirroring (may slow down GUI)
LOG_MIRROR_ENABLED = True

# Example: Change FBP config
FBP_RECON_CONFIG = {
    "pixel_size": 0.05,
    "calibrated_shift_px": 5.12,
    ...
}
```

### `logging_utils.py`
**Thread-safe logging** that won't freeze the GUI:
- `ThreadSafeLogQueue` - Queue for log messages with overflow protection
- `MinimalStreamTee` - Optional stdout/stderr capture (disabled by default)
- `GUILogHandler` - Sends logging module messages to GUI

### `workers.py`
**Background workers** for heavy tasks:
- `AcquisitionWorker` - Runs camera acquisition in a **separate process** (multiprocessing)
- `ReconstructionWorker` - Runs reconstruction scripts in a thread

**Why multiprocessing for acquisition?**
- Camera SDK may block at driver level
- Python threads share GIL (Global Interpreter Lock)
- Separate process = complete isolation from GUI

### `serial_handler.py`
**STM32 serial communication**:
- Port discovery and connection
- Send/receive with line buffering
- Signal-based message handling
- Auto commands: "OK" on start, "STOP" on stop

### `main_window.py`
**Main GUI window**:
- Acquisition controls (save folder, dark map, start/stop)
- Serial port controls (connect, send commands)
- Reconstruction controls (method selection, config editor)
- Log viewer

---

## Automatic Serial Commands

The GUI automatically sends commands to the STM32:

| Event | Command | Purpose |
|-------|---------|---------|
| "MAIN ACQUISITION STARTED" appears | `OK` | Tell motor to start rotating |
| User clicks "Stop" button | `STOP` | Tell motor to stop |

---

## Troubleshooting

### GUI Freezes During Acquisition

This should no longer happen! But if it does:

2. **Enable verbose logging** in `config.py`:
   ```python
   LOG_MIRROR_ENABLED = True
   ```

3. **Add debug prints** in `workers.py` inside `_acquisition_process_target()`:
   ```python
   print("DEBUG: Opening camera...")  # Appears in terminal
   ```

### Log View Not Updating

The log view only shows `logging.info()` messages by default. To see all prints:
```python
# In config.py
LOG_MIRROR_ENABLED = True
```
⚠️ Warning: This may slow down the GUI if there's heavy output.

### Camera Not Found

Check that the acquisition module path is correct in `config.py`:
```python
ACQUISITION_MODULE_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\S2I_External_Trigger_detector_image_acquisition\Hot_duration_trig_mode"
```

### Serial Port Issues

1. Click "Refresh" to rescan ports
2. Check baud rate matches STM32 configuration (default: 115200)
3. Ensure no other application is using the port

---

## Configuration Reference

### Reconstruction Configs

**FDK / Iterative Methods** use `DEFAULT_RECON_CONFIG`:
```python
{
    "voxel_size": 26,
    "DSD": 457,
    "DSO": 211,
    "downsample": 1,
    "total_angle": 2 * math.pi,
    "calibrated_shift_px": 15.6,
    "shift_sign": 1,
    "filter_type": "ram_lak",
    "rotation_angle": 0.0,
    "output_folder_NiFT": "...",
    "filtered_volumes_folder": "..."
}
```

**FBP** uses `FBP_RECON_CONFIG`:
```python
{
    "pixel_size": 0.05,
    "calibrated_shift_px": 5.12,
    "shift_sign": -1,
    "default_filter": "hann",
    "filters": ["ram_lak", "shepp_logan", "hann"]
}
```

The GUI automatically switches between configs when you select a method.

### GUI Performance Settings

In `config.py`:
```python
LOG_MIRROR_ENABLED = False      # Mirror ALL stdout to GUI (slow if True)
LOG_MAX_QUEUE_SIZE = 1000       # Max pending log messages
LOG_FLUSH_INTERVAL_MS = 250     # How often to update log view
LOG_MAX_ITEMS_PER_FLUSH = 10    # Max lines added per update
LOG_VIEW_MAX_BLOCKS = 2000      # Max lines in log view
```

---

## Architecture Notes

### Why Separate Process for Acquisition?

```
┌─────────────────────────────────────────────────────────────┐
│                      MAIN PROCESS                           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Qt GUI    │    │   Logging   │    │   Serial    │     │
│  │   Thread    │    │   Handler   │    │   Handler   │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
│         │                                                   │
│         │ Poll results (100ms timer)                        │
│         ▼                                                   │
│  ┌─────────────┐                                           │
│  │   Result    │◄─────── multiprocessing.Queue ◄───────────┤
│  │   Queue     │                                           │
│  └─────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ Completely isolated
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   ACQUISITION PROCESS                        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   Camera    │    │   Image     │    │   File      │     │
│  │   SDK       │    │  Processing │    │   Saving    │     │
│  └─────────────┘    └─────────────┘    └─────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

This architecture ensures the GUI **never freezes** even if:
- Camera SDK blocks waiting for hardware
- Heavy image processing is running
- File I/O is slow

---

## Adding New Features

### Adding a New Reconstruction Method

1. Add the method mapping in `main_window.py` → `_scan_reconstruction_methods()`:
   ```python
   mapping = {
       "FDK_reduce_memory": root / "FDK_reduce_memory" / "MAIN_TIGRE_FDK_Voxel_size.py",
       "FBP": root / "FBP" / "TIGRE_fbp1.py",
       "NEW_METHOD": root / "new_folder" / "new_script.py",  # Add here
   }
   ```

2. If it needs a special config, add it in `config.py` and update `_get_current_default_config()`.

### Adding New GUI Controls

1. Create the widget in the appropriate `_create_*_group()` method in `main_window.py`
2. Connect signals to handler methods
3. Implement the handler method

---

## Contact

For issues with the camera modules, check the acquisition module documentation in:
```
C:\Users\joaomartimreis\Desktop\Joao_CT\S2I_External_Trigger_detector_image_acquisition\
```
