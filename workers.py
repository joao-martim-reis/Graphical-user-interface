"""
Background Workers for Acquisition and Reconstruction
======================================================

This module contains the worker classes that run heavy tasks in the background
WITHOUT freezing the GUI.

================================================================================
THE FREEZING PROBLEM AND SOLUTION
================================================================================

PROBLEM: Why did the GUI freeze?
--------------------------------
When you clicked "Start Acquisition", the GUI would freeze because:

1. Python has a GIL (Global Interpreter Lock)
   - Only ONE thread can execute Python code at a time
   - Even with QThread, the camera SDK's blocking calls would hold the GIL
   - The GUI thread couldn't update while waiting for the camera

2. Camera SDK behavior
   - open_camera(), AcquireImage() etc. are blocking calls
   - They wait for hardware responses (can take seconds)
   - While waiting, they might not release the GIL properly

3. Logging overhead
   - Every logging.info() was trying to update the GUI
   - Too many GUI updates = main thread overwhelmed

SOLUTION: Use MULTIPROCESSING instead of threading
--------------------------------------------------
Instead of QThread (which shares the GIL), we use Python's multiprocessing:

    multiprocessing.Process  ←  Acquisition runs here (separate Python interpreter)
           ↓
    multiprocessing.Queue   ←  Messages sent to GUI (process-safe)
           ↓
    QTimer polling          ←  GUI checks queue every 100ms (non-blocking)

Why this works:
- Each Process has its OWN Python interpreter and GIL
- Camera SDK can block forever - GUI doesn't care
- Complete memory isolation - no shared state bugs
- Queue provides safe communication between processes

Communication protocol:
- result_queue: Process → GUI (progress updates, results)
- command_queue: GUI → Process (stop commands)

Message format: (type, data)
- ("log", "message")      - Log message to display
- ("progress", "message") - Progress update
- ("preview", "path")     - Preview image ready
- ("finished", "message") - Acquisition completed successfully
- ("error", "message")    - Acquisition failed

================================================================================
"""
import os
import sys
import json
import logging
import runpy
import multiprocessing
import glob
from multiprocessing import Process, Queue as MPQueue

from PySide6 import QtCore

# Note: ACQUISITION_MODULE_PATH and DEFAULT_DEFECT_MAP_PATH are now passed
# as parameters from main_window.py, which gets them from main.py
# This makes it easier to configure paths in one place (main.py)


# ============================================================================
# ACQUISITION PROCESS
# This code runs in a COMPLETELY SEPARATE process from the GUI!
# ============================================================================

class QueueLogHandler(logging.Handler):
    """
    Custom logging handler that forwards log messages to the GUI via queue.
    
    This is used inside the acquisition process to capture all logging.info()
    calls and send them to the GUI for display.
    
    Why needed:
    - The acquisition process has no direct access to the GUI
    - We need to see what's happening (pulses received, images saved, etc.)
    - The queue provides process-safe communication
    """
    def __init__(self, queue):
        super().__init__()
        self.queue = queue
    
    def emit(self, record):
        """Called by logging module for each log message."""
        try:
            msg = self.format(record)
            # Send as ("log", message) tuple
            self.queue.put(("log", msg))
        except Exception:
            pass  # Never let logging errors crash the process


def _acquisition_process_target(save_dir, dark_map_path, preview_only, result_queue, command_queue, acquisition_module_path, defect_map_path):
    """
    Target function for the acquisition process.
    
    THIS RUNS IN A COMPLETELY SEPARATE PROCESS!
    - Has its own Python interpreter
    - Has its own GIL (Global Interpreter Lock)
    - Can block indefinitely without affecting the GUI
    - Communicates with GUI only through queues
    
    Args:
        save_dir: Directory to save acquired images
        dark_map_path: Path to dark map for correction (or empty string)
        preview_only: If True, only capture preview, don't run full acquisition
        result_queue: Queue to send results/progress TO the GUI
        command_queue: Queue to receive commands FROM the GUI (e.g., "stop")
        acquisition_module_path: Path to camera SDK modules
        defect_map_path: Path to defect map for image correction
    """
    # ========================================================================
    # SETUP LOGGING
    # All logging.info() calls will be forwarded to the GUI via result_queue
    # ========================================================================
    queue_handler = QueueLogHandler(result_queue)
    queue_handler.setFormatter(logging.Formatter('%(message)s'))
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []  # Clear any existing handlers
    root_logger.addHandler(queue_handler)  # Add queue handler for GUI
    
    # Also add terminal output (so we can see logs in the terminal too)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))
    root_logger.addHandler(stream_handler)
    
    # ========================================================================
    # IMPORT CAMERA MODULES
    # These are imported INSIDE the process to avoid serialization issues
    # ========================================================================
    if acquisition_module_path not in sys.path:
        sys.path.insert(0, acquisition_module_path)
    
    try:
        from camera_config import (
            open_camera,
            close_camera,
            setup_camera_mode,
            get_detector_info,
        )
        from image_processing import (
            DefectMapContext,
            DarkMapContext,
            ImageSaver,
            create_image_buffer,
        )
        from acquisition import (
            run_acquisition_loop,
            capture_preview_image,
        )
    except ImportError as e:
        result_queue.put(("error", f"Failed to import camera modules: {e}"))
        return
    
    camera_device = None
    
    def should_stop():
        """
        Callback function to check if GUI requested stop.
        Called periodically by run_acquisition_loop().
        """
        try:
            cmd = command_queue.get_nowait()
            if cmd == "stop":
                return True
        except:
            pass
        return False
    
    # ========================================================================
    # MAIN ACQUISITION LOGIC
    # This is where the actual camera work happens
    # ========================================================================
    try:
        logging.info("Opening camera...")
        camera_device = open_camera()
        
        logging.info("Getting detector info...")
        detector_dimensions = get_detector_info(camera_device)
        if not detector_dimensions:
            result_queue.put(("error", "Failed to get detector info"))
            return
        
        logging.info("Setting up camera mode...")
        setup_camera_mode(camera_device)
        
        logging.info("Loading calibration maps...")
        defect_ctx = DefectMapContext(defect_map_path)
        dark_ctx = DarkMapContext(dark_map_path) if dark_map_path else None
        
        logging.info("Creating image buffer...")
        image_saver = ImageSaver(save_dir, bit_depth=16)
        image_buffer = create_image_buffer(
            detector_dimensions['width'], 
            detector_dimensions['height']
        )
        
        logging.info("Capturing preview...")
        preview_path = capture_preview_image(
            device=camera_device,
            image_buffer=image_buffer,
            defect_ctx=defect_ctx,
            dark_ctx=dark_ctx,
            image_saver=image_saver,
            exposure_ms=2000
        )
        
        if not preview_path:
            result_queue.put(("error", "Preview capture failed"))
            return
        
        # Send preview path to GUI
        result_queue.put(("preview", preview_path))
        
        if preview_only:
            result_queue.put(("finished", "Preview completed"))
            return
        
        # Run the main acquisition loop
        # This is where pulses are received and images are saved
        # The should_stop callback allows the GUI to stop the acquisition
        logging.info("Starting acquisition loop...")
        stats = run_acquisition_loop(
            device=camera_device,
            image_buffer=image_buffer,
            defect_ctx=defect_ctx,
            dark_ctx=dark_ctx,
            image_saver=image_saver,
            stop_callback=should_stop,  # Checked periodically
            pulse_timeout_ms=20000
        )
        
        if stats:
            # ================================================================
            # DELETE PREVIEW AND FIRST IMAGE
            # These are test images that should not be included in reconstruction
            # ================================================================
            logging.info("Cleaning up preview and first test image...")
            
            # Delete the preview image if it exists
            if preview_path and os.path.exists(preview_path):
                try:
                    os.remove(preview_path)
                    logging.info(f"Deleted preview: {os.path.basename(preview_path)}")
                except Exception as e:
                    logging.warning(f"Could not delete preview: {e}")
            
            # Delete the first image (image_00001.tif) - it's a test exposure
            first_image_pattern = os.path.join(save_dir, "image_00001.*")
            first_images = glob.glob(first_image_pattern)
            for img in first_images:
                try:
                    os.remove(img)
                    logging.info(f"Deleted first image: {os.path.basename(img)}")
                except Exception as e:
                    logging.warning(f"Could not delete first image: {e}")
            
            result_queue.put(("finished", "Acquisition completed"))
        else:
            result_queue.put(("error", "Acquisition failed"))
            
    except Exception as e:
        result_queue.put(("error", f"Error: {e}"))
    finally:
        # Always close the camera, even if there was an error
        if camera_device:
            try:
                close_camera(camera_device)
            except:
                pass


# ============================================================================
# ACQUISITION WORKER (GUI-side)
# This class runs in the GUI process and manages the acquisition process
# ============================================================================

class AcquisitionWorker(QtCore.QObject):
    """
    Manages the acquisition process from the GUI side.
    
    This class:
    1. Starts the acquisition in a separate Process
    2. Uses a QTimer to poll the result queue (non-blocking!)
    3. Emits Qt signals when messages arrive from the process
    4. Can send stop commands to the process
    
    Key insight: This class does NOT do any camera work itself.
    It only manages communication with the process that does.
    
    Signals:
        preview_ready(str): Emitted when preview image is saved (path)
        finished(bool, str): Emitted when acquisition ends (success, message)
        progress(str): Emitted for log/progress messages
        started_work(): Emitted when acquisition process starts
    """
    preview_ready = QtCore.Signal(str)
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(str)
    started_work = QtCore.Signal()
    
    def __init__(self, parent=None, acquisition_module_path="", defect_map_path=""):
        super().__init__(parent)
        self._process = None          # The acquisition Process
        self._result_queue = None     # Queue: Process → GUI
        self._command_queue = None    # Queue: GUI → Process
        
        # Path configuration (passed from main.py via main_window.py)
        self._acquisition_module_path = acquisition_module_path
        self._defect_map_path = defect_map_path
        
        # QTimer for polling - this is the key to non-blocking communication!
        # Every 100ms, we check if the process has sent any messages
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(100)  # Poll every 100ms
        self._poll_timer.timeout.connect(self._poll_results)
        
        self._is_running = False
    
    def start(self, save_dir, dark_map_path, preview_only=False):
        """
        Start the acquisition in a separate process.
        
        This method returns immediately - it does NOT wait for acquisition
        to complete. The GUI remains responsive.
        """
        if self._is_running:
            return
        
        # Create the communication queues
        # These are process-safe (can be shared between processes)
        self._result_queue = MPQueue()
        self._command_queue = MPQueue()
        
        # Create and start the acquisition process
        self._process = Process(
            target=_acquisition_process_target,
            args=(save_dir, dark_map_path, preview_only, 
                  self._result_queue, self._command_queue,
                  self._acquisition_module_path, self._defect_map_path)
        )
        self._process.start()  # Starts running in background
        
        self._is_running = True
        self._poll_timer.start()  # Start polling for results
        self.started_work.emit()  # Notify GUI that work has started
    
    def request_stop(self):
        """
        Request the acquisition process to stop.
        
        Sends "stop" command via the command queue.
        The process checks this periodically in should_stop().
        """
        if self._command_queue:
            try:
                self._command_queue.put("stop")
            except:
                pass
    
    def is_running(self):
        return self._is_running
    
    def _poll_results(self):
        """
        Poll the result queue for messages from the acquisition process.
        
        This is called every 100ms by the QTimer.
        It's NON-BLOCKING - if no messages, it returns immediately.
        
        This is the key to keeping the GUI responsive!
        """
        if not self._result_queue:
            return
        
        # Check if process is still alive
        if self._process and not self._process.is_alive():
            self._cleanup()
            return
        
        # Process ALL available messages (non-blocking)
        while True:
            try:
                msg_type, msg_data = self._result_queue.get_nowait()
                
                # Route message to appropriate signal
                if msg_type == "progress":
                    self.progress.emit(msg_data)
                elif msg_type == "log":
                    # Forward log messages from acquisition process to GUI
                    self.progress.emit(msg_data)
                elif msg_type == "preview":
                    self.preview_ready.emit(msg_data)
                elif msg_type == "finished":
                    self.finished.emit(True, msg_data)
                    self._cleanup()
                    return
                elif msg_type == "error":
                    self.finished.emit(False, msg_data)
                    self._cleanup()
                    return
            except:
                # No more messages in queue - exit loop
                break
    
    def _cleanup(self):
        """Clean up process resources after acquisition ends."""
        self._poll_timer.stop()
        self._is_running = False
        
        if self._process:
            # Wait up to 1 second for process to finish
            self._process.join(timeout=1)
            # Force terminate if still running
            if self._process.is_alive():
                self._process.terminate()
            self._process = None
            
        self._result_queue = None
        self._command_queue = None


# ============================================================================
# RECONSTRUCTION PROCESS TARGET
# This runs in a SEPARATE PROCESS to allow matplotlib GUI to work
# ============================================================================

def _reconstruction_process_target(main_path, args, env_vars, result_queue, command_queue):
    """
    Target function for the reconstruction process.
    
    THIS RUNS IN A COMPLETELY SEPARATE PROCESS!
    - Has its own Python interpreter
    - Matplotlib GUI works correctly (it's the "main" thread of this process)
    - Can show interactive windows for ROI selection, etc.
    
    Args:
        main_path: Path to the reconstruction script to run
        args: Command line arguments to pass
        env_vars: Environment variables (config, paths, etc.)
        result_queue: Queue to send progress/results back to GUI
    """
    import runpy
    import sys
    import os
    import builtins
    
    try:
        result_queue.put(("progress", "Setting up environment..."))
        
        # Set environment variables for the reconstruction script
        for key, value in env_vars.items():
            os.environ[key] = value
        
        # Add script directory to Python path
        script_dir = os.path.dirname(main_path)
        if script_dir and script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        
        result_queue.put(("progress", "Running reconstruction script..."))

        # --------------------------------------------------------------------
        # Redirect stdout/stderr to GUI
        # --------------------------------------------------------------------
        original_stdout = sys.stdout
        original_stderr = sys.stderr

        class _QueueStream:
            def __init__(self, queue, stream_name="stdout"):
                self.queue = queue
                self.stream_name = stream_name
                self._buffer = ""

            def write(self, text):
                if not text:
                    return 0
                self._buffer += text
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if line.strip():
                        self.queue.put(("log", line))
                return len(text)

            def flush(self):
                if self._buffer.strip():
                    self.queue.put(("log", self._buffer.strip()))
                self._buffer = ""

        sys.stdout = _QueueStream(result_queue, "stdout")
        sys.stderr = _QueueStream(result_queue, "stderr")

        # --------------------------------------------------------------------
        # Redirect input() to GUI
        # --------------------------------------------------------------------
        original_input = builtins.input

        def _gui_input(prompt=""):
            try:
                result_queue.put(("input_request", prompt))
                response = command_queue.get()  # blocks until GUI responds
                if isinstance(response, tuple) and len(response) >= 2 and response[0] == "input_response":
                    return "" if response[1] is None else str(response[1])
                if response is None:
                    return ""
                return str(response)
            except Exception:
                return ""

        builtins.input = _gui_input
        
        # Run the script using runpy (like python script.py)
        argv_backup = sys.argv[:]
        sys.argv = [main_path] + args
        try:
            runpy.run_path(main_path, run_name="__main__")
        finally:
            sys.argv = argv_backup
            # Restore input and streams
            builtins.input = original_input
            sys.stdout = original_stdout
            sys.stderr = original_stderr
        
        result_queue.put(("finished", "Reconstruction completed"))
    except Exception as e:
        result_queue.put(("error", f"Reconstruction failed: {e}"))


# ============================================================================
# RECONSTRUCTION WORKER (GUI-side)
# Uses multiprocessing to allow matplotlib GUI to work in reconstruction scripts
# ============================================================================

class ReconstructionWorker(QtCore.QObject):
    """
    Manages the reconstruction process from the GUI side.
    
    IMPORTANT: Uses multiprocessing (not QThread) because:
    - Matplotlib GUI must run in the main thread of its process
    - When using QThread, matplotlib windows fail with warnings
    - A separate Process has its own "main thread" where matplotlib works
    
    This is the same pattern as AcquisitionWorker:
    1. Start reconstruction in a separate Process
    2. Use QTimer to poll result queue (non-blocking)
    3. Emit Qt signals when messages arrive
    
    Signals:
        finished(bool, str): Emitted when reconstruction ends
        progress(str): Emitted for status updates
    """
    finished = QtCore.Signal(bool, str)
    progress = QtCore.Signal(str)
    input_requested = QtCore.Signal(str)

    def __init__(self, main_path, args, env_vars, parent=None):
        """
        Args:
            main_path: Path to the reconstruction script to run
            args: Command line arguments to pass
            env_vars: Environment variables to set (config, paths, etc.)
        """
        super().__init__(parent)
        self.main_path = main_path
        self.args = args
        self.env_vars = env_vars
        
        self._process = None
        self._result_queue = None
        self._command_queue = None
        
        # QTimer for polling - same pattern as AcquisitionWorker
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(100)  # Poll every 100ms
        self._poll_timer.timeout.connect(self._poll_results)
        
        self._is_running = False

    def start(self):
        """Start the reconstruction in a separate process."""
        if self._is_running:
            return
        
        # Create communication queue
        self._result_queue = MPQueue()
        self._command_queue = MPQueue()
        
        # Create and start the reconstruction process
        self._process = Process(
            target=_reconstruction_process_target,
            args=(self.main_path, self.args, self.env_vars, self._result_queue, self._command_queue)
        )
        self._process.start()
        
        self._is_running = True
        self._poll_timer.start()
    
    def is_running(self):
        return self._is_running
    
    def _poll_results(self):
        """Poll the result queue for messages from the reconstruction process."""
        if not self._result_queue:
            return
        
        # Check if process is still alive
        if self._process and not self._process.is_alive():
            self._cleanup()
            return
        
        # Process all available messages
        while True:
            try:
                msg_type, msg_data = self._result_queue.get_nowait()
                
                if msg_type == "progress":
                    self.progress.emit(msg_data)
                elif msg_type == "log":
                    self.progress.emit(msg_data)
                elif msg_type == "input_request":
                    self.input_requested.emit(msg_data)
                elif msg_type == "finished":
                    self.finished.emit(True, msg_data)
                    self._cleanup()
                    return
                elif msg_type == "error":
                    self.finished.emit(False, msg_data)
                    self._cleanup()
                    return
            except:
                break
    
    def _cleanup(self):
        """Clean up process resources."""
        self._poll_timer.stop()
        self._is_running = False
        
        if self._process:
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.terminate()
            self._process = None
        
        self._result_queue = None
        self._command_queue = None

    def send_input_response(self, response):
        """Send input response back to reconstruction process."""
        if self._command_queue:
            try:
                self._command_queue.put(("input_response", response))
            except Exception:
                pass
