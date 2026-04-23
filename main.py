"""
CT Acquisition and Reconstruction GUI
======================================

Main entry point for the application.
Run this file to start the GUI: python main.py

================================================================================
HOW THE GUI FREEZING PROBLEM WAS SOLVED
================================================================================

PROBLEM:
--------
When running acquisition, the GUI would freeze and show "Not Responding".
This happened because:
1. The camera SDK performs blocking operations (waiting for hardware)
2. Even using QThread, Python's GIL (Global Interpreter Lock) can cause issues
3. Heavy I/O and CPU operations in threads can still block the main thread

SOLUTION: MULTIPROCESSING
-------------------------
Instead of using threads (QThread), the acquisition runs in a COMPLETELY 
SEPARATE PROCESS using Python's multiprocessing module.

Why multiprocessing works:
- Each process has its own Python interpreter and GIL
- The camera SDK can block indefinitely without affecting the GUI
- Complete memory isolation - no shared state issues
- The GUI process remains 100% responsive

Architecture:
                    
    ┌─────────────────────────────────────────────────────────┐
    │                   MAIN PROCESS (GUI)                    │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
    │  │  Qt Event   │  │   Log View  │  │   Serial    │     │
    │  │    Loop     │  │   Update    │  │   Handler   │     │
    │  └─────────────┘  └─────────────┘  └─────────────┘     │
    │         │                                               │
    │         │ QTimer polls every 100ms                      │
    │         ▼                                               │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │     multiprocessing.Queue (result_queue)        │   │
    │  │  - Receives: progress, log, preview, finished   │   │
    │  └─────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘
                              ▲
                              │ Messages via Queue
                              │ (thread-safe, process-safe)
                              │
    ┌─────────────────────────────────────────────────────────┐
    │              ACQUISITION PROCESS (Separate)             │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
    │  │   Camera    │  │   Image     │  │    File     │     │
    │  │    SDK      │  │ Processing  │  │   Saving    │     │
    │  └─────────────┘  └─────────────┘  └─────────────┘     │
    │         │                                               │
    │         │ All logging.info() calls                      │
    │         ▼                                               │
    │  ┌─────────────────────────────────────────────────┐   │
    │  │   QueueLogHandler → Sends to result_queue       │   │
    │  └─────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘

Communication Flow:
1. GUI creates multiprocessing.Queue for results
2. GUI starts acquisition Process with queue reference
3. Acquisition process sends messages: ("log", "message"), ("progress", "..."), etc.
4. GUI polls queue every 100ms with QTimer (non-blocking)
5. Messages are displayed in log view and status bar

================================================================================
FILE STRUCTURE
================================================================================

- main.py           - Entry point (this file)
- config.py         - Configuration constants and paths
- logging_utils.py  - Thread-safe logging utilities  
- workers.py        - Background workers (multiprocessing for acquisition)
- serial_handler.py - STM32 serial communication
- main_window.py    - Main GUI window and UI logic

================================================================================
"""
import os
import sys
import multiprocessing

from PySide6 import QtWidgets

from config import LOG_MAX_QUEUE_SIZE, DEFAULT_DARK_MAP_PATH, DEFAULT_GAIN_MAP_PATH
from logging_utils import ThreadSafeLogQueue, setup_logging
from main_window import MainWindow

# ============================================================================
# PATH CONFIGURATION - EDIT THESE PATHS AS NEEDED
# ============================================================================
# Path to camera acquisition modules (camera_config.py, acquisition.py, etc.)
ACQUISITION_MODULE_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\S2I_External_Trigger_detector_image_acquisition\Hot_duration_trig_mode"

# Path to reconstruction algorithm scripts root folder
RECONSTRUCTION_ROOT_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms"

# Default defect map for image correction
DEFECT_MAP_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\DefectMap.tif"


def main():
    # Required for multiprocessing on Windows
    # This must be called before creating any Process objects
    # It allows the frozen executable to work correctly
    multiprocessing.freeze_support()
    
    # Create the Qt application instance
    app = QtWidgets.QApplication(sys.argv)

    # Apply the light-polish stylesheet (purely cosmetic, no behavior changes)
    qss_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.qss")
    if os.path.exists(qss_path):
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception:
            pass  # Never let styling prevent startup

    # Setup thread-safe logging system
    # The log_queue allows background processes to send log messages
    # to the GUI without causing threading issues
    log_queue = ThreadSafeLogQueue(max_size=LOG_MAX_QUEUE_SIZE)
    setup_logging(log_queue)
    
    # Create and show the main window
    # Pass the log_queue so the window can display messages from workers
    # Pass the paths for acquisition and reconstruction configuration
    window = MainWindow(
        log_queue,
        acquisition_module_path=ACQUISITION_MODULE_PATH,
        reconstruction_root_path=RECONSTRUCTION_ROOT_PATH,
        defect_map_path=DEFECT_MAP_PATH,
        default_dark_map_path=DEFAULT_DARK_MAP_PATH,
        default_gain_map_path=DEFAULT_GAIN_MAP_PATH,
    )
    window.show()
    
    # Start the Qt event loop
    # This blocks until the application is closed
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
