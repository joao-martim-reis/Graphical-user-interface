# CT Acquisition and Reconstruction GUI

A simplified graphical interface for controlling CT image acquisition and running reconstruction algorithms.

---

## 📋 Quick Start

1. **Install Requirements:**
   - Python 3.8+
   - PySide6: `pip install PySide6`
   - Camera SDK modules (in acquisition folder)

2. **Configure Paths** in `main.py`:
   - `ACQUISITION_MODULE_PATH` - Path to camera SDK
   - `RECONSTRUCTION_ROOT_PATH` - Path to reconstruction scripts
   - `DEFECT_MAP_PATH` - Path to defect map file

3. **Configure Default Dark Map** in `config.py`:
   - `DEFAULT_DARK_MAP_PATH` - Path to your dark map file (auto-loaded)

4. **Run the GUI:**
   ```bash
   python main.py
   ```

---

## 🎯 What This GUI Does

### 1. **Acquisition** (Camera Control)
- Captures CT images from your camera
- Applies defect correction and dark map correction automatically
- Saves images to a folder you choose
- Automatically communicates with motor controller during scan

### 2. **Serial Control** (Motor Controller)
- Connects to STM32 microcontroller
- **Automatically sends:**
  - `OK` when acquisition starts → tells motor to start rotating
  - `STOP` when you click Stop → tells motor to stop immediately
- Shows status and received messages

### 3. **Reconstruction** (Image Processing)
- Runs reconstruction algorithms on acquired images
- Supports: FDK, FBP, and Iterative methods
- Editable parameters (you can change them before running)
- Uses the acquisition folder as input automatically

### 4. **Logging** (Status Display)
- Shows real-time messages from all operations
- Never freezes the GUI (messages are buffered)
- Scrolls automatically to show latest updates

---

## 📦 File Structure & Classes

```
GUI/
├── main.py                 # Entry point - starts the application
├── config.py               # Configuration settings (paths, parameters)
├── main_window.py          # MainWindow class - the GUI you see
├── workers.py              # Worker classes - background processes
├── serial_handler.py       # SerialHandler class - motor communication
└── logging_utils.py        # Logging classes - message handling
```

### **File-by-File Explanation:**

---

### 1. `main.py` - Application Entry Point
**Purpose:** Starts everything up

**What it does:**
1. Creates the Qt application (the window system)
2. Sets up the logging system
3. Creates the main window
4. Runs the event loop (keeps GUI responsive)

**Key code:**
```python
app = QtWidgets.QApplication(sys.argv)  # Create application
window = MainWindow(...)                 # Create main window
window.show()                            # Show the window
sys.exit(app.exec())                     # Run until user closes
```

**No classes here** - just the startup sequence.

---

### 2. `main_window.py` - MainWindow Class
**Purpose:** The actual GUI you interact with

**The MainWindow Class:**
```python
class MainWindow(QtWidgets.QMainWindow):
```

**What this means:**
- `class MainWindow` - We're creating a new class called MainWindow
- `(QtWidgets.QMainWindow)` - It inherits from QMainWindow (gets all window features)
- Inheritance means: "MainWindow is a QMainWindow, plus extra stuff we add"

**Structure:**
```python
class MainWindow:
    def __init__(self, ...):         # Constructor - runs when window is created
        self.save_dir = ""            # Instance variable - stores save folder path
        self.acq_worker = None        # Instance variable - stores acquisition worker
        self._build_ui()              # Method call - builds the interface
    
    def _build_ui(self):              # Method - creates buttons, labels, etc.
        # Creates the UI elements
    
    def _start_acquisition(self):     # Method - handles button click
        # Start the camera acquisition
    
    def _on_acq_progress(self, msg):  # Method - handles progress updates
        # Update status bar and log
```

**Key concepts:**
- `self` - Refers to "this specific window object"
- `self.save_dir` - This window's save directory
- Methods starting with `_` are "private" (internal use only)

**Instance variables (stored data):**
- `self.save_dir` - Where to save images
- `self.dark_map_path` - Path to dark map (auto-loaded)
- `self.acq_worker` - The acquisition worker object
- `self.recon_worker` - The reconstruction worker object
- `self.serial_handler` - The serial communication object

**Methods (actions):**
- `_select_save_folder()` - Opens folder picker
- `_start_acquisition()` - Starts camera capture
- `_stop_acquisition()` - Stops camera capture
- `_run_reconstruction()` - Starts reconstruction
- `_on_acq_progress(message)` - Handles progress updates

---

### 3. `workers.py` - Worker Classes
**Purpose:** Handle heavy work without freezing GUI

#### **AcquisitionWorker Class:**
```python
class AcquisitionWorker(QtCore.QObject):
    # Qt signals - used to send messages back to GUI
    preview_ready = QtCore.Signal(str)
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(str)
    
    def __init__(self, ...):
        self._process = None          # The separate process doing camera work
        self._result_queue = None     # Queue for receiving messages
        
    def start(self, save_dir, dark_map_path, preview_only):
        # Creates a NEW PROCESS (not a thread!)
        self._process = Process(target=_acquisition_process_target, ...)
        self._process.start()         # Start it running
        self._poll_timer.start()      # Start checking for messages
    
    def _poll_results(self):
        # Called every 100ms to check for messages from process
        msg_type, msg_data = self._result_queue.get_nowait()
        if msg_type == "progress":
            self.progress.emit(msg_data)  # Send to GUI
```

**Why separate process?**
- Camera operations can take seconds
- If they ran in the GUI process, GUI would freeze
- Separate process = GUI stays responsive

**How communication works:**
```
┌──────────────────┐                  ┌──────────────────┐
│   GUI Process    │                  │ Acquisition      │
│   (MainWindow)   │                  │ Process          │
│                  │                  │                  │
│  QTimer polls    │◄─── Queue ──────│  Sends messages  │
│  every 100ms     │                  │  ("progress")    │
│                  │                  │  ("finished")    │
│  Emits signals   │                  │  ("error")       │
│  to MainWindow   │                  │                  │
└──────────────────┘                  └──────────────────┘
```

#### **ReconstructionWorker Class:**
Similar structure to AcquisitionWorker:
- Runs reconstruction in separate process
- Uses queue for communication
- Emits signals to GUI
- Can handle input requests (for interactive reconstruction)

---

### 4. `serial_handler.py` - SerialHandler Class
**Purpose:** Communicate with STM32 motor controller

```python
class SerialHandler(QtCore.QObject):
    # Signals for notifying MainWindow
    message_received = QtCore.Signal(str)
    connection_changed = QtCore.Signal(bool)
    
    def __init__(self, parent=None):
        self._port = QtSerialPort.QSerialPort(self)  # Qt serial port object
        self._rx_buffer = ""                         # Buffer for incoming data
        
    def connect(self, port_name, baud_rate):
        # Open the serial port
        self._port.setPortName(port_name)
        self._port.open(...)
        # IMPORTANT: Disable DTR/RTS to prevent STM32 reset!
        self._port.setDataTerminalReady(False)
        self._port.setRequestToSend(False)
    
    def send(self, text):
        # Send command with newline
        self._port.write(f"{text}\n".encode())
    
    def _on_ready_read(self):
        # Called automatically when data arrives
        # Buffers incomplete lines until we get a full message
```

**Key feature:** Event-driven (non-blocking)
- Qt calls `_on_ready_read()` when data arrives
- No need to constantly check for data
- Never freezes the GUI

---

### 5. `logging_utils.py` - Logging Classes
**Purpose:** Handle log messages efficiently

#### **ThreadSafeLogQueue Class:**
```python
class ThreadSafeLogQueue:
    def __init__(self, max_size=1000):
        self._queue = Queue(maxsize=max_size)  # Python's thread-safe queue
        
    def put(self, msg):
        # Add message to queue (drops oldest if full)
        
    def get_batch(self, max_items=10):
        # Get multiple messages at once (efficient!)
        # Returns up to max_items messages
```

**Why needed?**
- Acquisition process sends LOTS of messages
- Updating GUI for each one would be slow
- Queue buffers them, GUI reads in batches

#### **GUILogHandler Class:**
```python
class GUILogHandler(logging.Handler):
    def __init__(self, log_queue):
        self._log_queue = log_queue
        
    def emit(self, record):
        # Called by logging module for each log message
        msg = self.format(record)
        self._log_queue.put(msg)  # Add to queue
```

**How it works:**
```python
# Anywhere in code:
logging.info("Camera opened successfully")

# Behind the scenes:
# 1. logging module calls GUILogHandler.emit()
# 2. Handler puts message in queue
# 3. MainWindow's timer reads from queue every 250ms
# 4. Messages are displayed in log view
```

---

## 🔄 How Everything Connects (Signal/Slot Pattern)

### **What are Signals and Slots?**

**Signal:** An announcement that something happened
**Slot:** A function that responds to the announcement

**Example:**
```python
# In AcquisitionWorker:
self.progress = QtCore.Signal(str)  # Define signal

# Later, when something happens:
self.progress.emit("Captured image 50/200")  # Send the signal

# In MainWindow:
self.acq_worker.progress.connect(self._on_acq_progress)  # Connect signal to slot

# When signal is emitted, this method is called:
def _on_acq_progress(self, message):
    logging.info(message)  # Display the message
```

**Why use signals/slots?**
- Thread-safe communication between classes
- Loose coupling (classes don't need to know about each other)
- Easy to connect/disconnect handlers

---

## 🔍 Step-by-Step: What Happens When You Click "Start Acquisition"

1. **You click "Start acquisition" button**
   ```python
   # MainWindow._start_acquisition() is called
   ```

2. **MainWindow creates an AcquisitionWorker**
   ```python
   self.acq_worker = AcquisitionWorker(...)
   self.acq_worker.progress.connect(self._on_acq_progress)  # Connect signals
   self.acq_worker.start(self.save_dir, self.dark_map_path, False)
   ```

3. **AcquisitionWorker creates a separate Process**
   ```python
   self._process = Process(target=_acquisition_process_target, ...)
   self._process.start()  # NEW PROCESS starts running
   ```

4. **Acquisition process does camera work**
   ```python
   # In separate process:
   camera_device = open_camera()  # Can take seconds - doesn't freeze GUI!
   capture_preview_image(...)
   run_acquisition_loop(...)      # Captures all images
   ```

5. **Process sends messages via queue**
   ```python
   result_queue.put(("progress", "Captured image 10/200"))
   ```

6. **MainWindow's timer polls queue every 100ms**
   ```python
   # AcquisitionWorker._poll_results() runs automatically
   msg_type, msg_data = self._result_queue.get_nowait()
   self.progress.emit(msg_data)  # Emit Qt signal
   ```

7. **MainWindow receives signal and updates GUI**
   ```python
   # MainWindow._on_acq_progress() is called
   def _on_acq_progress(self, message):
       self.statusBar().showMessage(message)  # Update status bar
       logging.info(message)                   # Add to log view
       
       if "MAIN ACQUISITION STARTED" in message:
           self.serial_handler.send("OK")      # Tell motor to start!
   ```

8. **When finished, process sends "finished" message**
   ```python
   result_queue.put(("finished", "Acquisition completed"))
   ```

9. **MainWindow shows completion dialog**
   ```python
   # MainWindow._on_acq_finished() is called
   QtWidgets.QMessageBox.information(self, "Acquisition", "Acquisition completed")
   ```

---

## 📖 Key Programming Concepts Used

### **1. Classes and Objects**
- **Class:** Blueprint/template (defines structure)
- **Object:** Instance created from class (actual thing)
- **Example:** `MainWindow` is a class, `window = MainWindow()` creates an object

### **2. Inheritance**
- **Concept:** One class extends another
- **Example:** `class MainWindow(QtWidgets.QMainWindow):`
- **Means:** MainWindow has all QMainWindow features, plus our additions

### **3. Methods**
- **Concept:** Functions that belong to a class
- **Syntax:** `def method_name(self, parameters):`
- **`self`:** Refers to the current object

### **4. Instance Variables**
- **Concept:** Data that belongs to a specific object
- **Syntax:** `self.variable_name = value`
- **Example:** `self.save_dir` stores this window's save directory

### **5. Signals and Slots**
- **Concept:** Qt's way of connecting events to handlers
- **Signal:** Announcement of an event
- **Slot:** Function that responds to signal
- **Example:** `button.clicked.connect(self.do_something)`

### **6. Multiprocessing**
- **Concept:** Running code in completely separate processes
- **Why:** Prevents GUI freezing during heavy operations
- **Communication:** Via queues (process-safe)

### **7. Event-Driven Programming**
- **Concept:** Code runs in response to events (clicks, timers, etc.)
- **Qt Event Loop:** Constantly checks for events and calls handlers
- **Example:** Button click → Qt calls your method

---

## 🎓 Understanding the Code Flow

### **Starting the Application:**
```
main.py
  ├─> Creates QApplication
  ├─> Creates log queue
  ├─> Creates MainWindow object
  │     └─> MainWindow.__init__() runs
  │           ├─> Stores configuration paths
  │           ├─> Creates SerialHandler object
  │           ├─> Calls _build_ui()
  │           │     └─> Creates all buttons, labels, etc.
  │           └─> Calls _load_defaults()
  └─> Calls app.exec() - starts event loop
```

### **During Acquisition:**
```
User clicks button
  └─> MainWindow._start_acquisition() called
        └─> Creates AcquisitionWorker object
              ├─> Connects signals to MainWindow methods
              └─> Calls worker.start()
                    └─> Creates Process
                          ├─> Process runs camera code
                          └─> Sends messages via queue
                                ↓
        Timer polls queue every 100ms
                                ↓
        Worker emits signals
                                ↓
        MainWindow methods called
                                ↓
        GUI updates (status, logs)
```

---

## 💡 Tips for Understanding the Code

1. **Start with `main.py`** - See how everything starts
2. **Look at `MainWindow.__init__`** - See how window is set up
3. **Find button connections** - See what happens when you click
4. **Follow one action completely** - Pick "Start acquisition" and trace through
5. **Read inline comments** - Explain what each line does
6. **Don't worry about Qt details** - Focus on the logic flow

---

## 🔧 Customization Guide

### **Change Default Paths:**
Edit `main.py`:
```python
ACQUISITION_MODULE_PATH = r"C:\your\path\here"
RECONSTRUCTION_ROOT_PATH = r"C:\your\path\here"
DEFECT_MAP_PATH = r"C:\your\defect_map.tif"
```

Edit `config.py`:
```python
DEFAULT_DARK_MAP_PATH = r"C:\your\dark_map.tif"
```

### **Change Reconstruction Parameters:**
Edit `config.py`:
```python
DEFAULT_RECON_CONFIG = {
    "voxel_size": 26,     # Change this
    "DSD": 457,           # And this
    # ... etc
}
```

### **Change GUI Performance:**
Edit `config.py`:
```python
LOG_FLUSH_INTERVAL_MS = 250  # How often to update log (milliseconds)
LOG_MAX_ITEMS_PER_FLUSH = 10  # Max messages per update
LOG_VIEW_MAX_BLOCKS = 2000    # Max lines in log view
```

---

## ❓ FAQ

**Q: Why does the GUI not freeze during acquisition?**  
A: Acquisition runs in a separate process with its own Python interpreter. The GUI process stays responsive.

**Q: What's the difference between a process and a thread?**  
A: Process = completely separate (own memory, own Python interpreter). Thread = shares memory (can cause issues with Python's GIL).

**Q: Why use classes instead of just functions?**  
A: Classes group related data and functions together, making code more organized and easier to maintain.

**Q: What is `self`?**  
A: `self` refers to the current object. `self.save_dir` means "this object's save_dir variable".

**Q: How do signals/slots work?**  
A: Signal = announcement ("something happened"). Slot = handler ("do this when announcement happens"). Qt manages the connection.

**Q: Can I add more buttons or features?**  
A: Yes! Add UI elements in `_build_ui()`, create handler methods, and connect them with `.clicked.connect()`.

---

## 📞 Troubleshooting

**GUI freezes:**
- Check that acquisition/reconstruction use multiprocessing (not threads)
- Check that heavy operations don't run in MainWindow methods

**Serial port issues:**
- Make sure baud rate matches STM32 (115200)
- Check that DTR/RTS are disabled (prevents reset)
- Close other programs using the port

**Camera errors:**
- Check paths in `main.py` are correct
- Make sure camera SDK modules are accessible
- Check defect map and dark map paths

**Reconstruction fails:**
- Check reconstruction scripts exist
- Check input folder has images
- Check output folder is writable

---

Made with ❤️ for CT scanning

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
