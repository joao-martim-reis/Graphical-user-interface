"""
Main Window for CT Acquisition and Reconstruction GUI
======================================================

This is the main GUI window containing all UI elements and logic.

GUI Architecture (part of the freezing solution):
-------------------------------------------------
The GUI uses Qt's event-driven architecture:

1. Main Event Loop (Qt)
   - Handles all UI events (clicks, keypresses, painting)
   - MUST remain responsive for UI to work
   - If blocked for >5 seconds, Windows shows "Not Responding"

2. Background Workers
   - AcquisitionWorker: Runs in SEPARATE PROCESS (multiprocessing)
   - ReconstructionWorker: Runs in separate THREAD (QThread)
   - Neither blocks the main event loop

3. Periodic Timers
   - Log flush timer: Updates log view every 250ms
   - Worker poll timer: Checks for results every 100ms

4. Serial Communication
   - Uses Qt's async serial port (event-driven)
   - Never blocks the main thread

Signal Flow for Acquisition:
---------------------------
1. User clicks "Start Acquisition"
2. AcquisitionWorker.start() creates Process and returns immediately
3. GUI remains responsive (can click Stop, scroll logs, etc.)
4. Process sends messages via queue
5. QTimer polls queue every 100ms, emits Qt signals
6. Main window receives signals, updates UI

Auto Serial Commands:
--------------------
- When "MAIN ACQUISITION STARTED" appears → Send "OK" to motor
- When user clicks Stop → Send "STOP" to motor
"""
import os
import json
import logging
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from config import (
    DEFAULT_RECON_CONFIG,
    FBP_RECON_CONFIG,
    ITERATIVE_ALGORITHMS,
    ITERATIVE_ALGORITHM_ITERATIONS,
    LOG_FLUSH_INTERVAL_MS,
    LOG_MAX_ITEMS_PER_FLUSH,
    LOG_VIEW_MAX_BLOCKS,
    MOTOR_CONFIG_DEFAULTS,
    MOTOR_CONFIG_RANGES,
    CALIBRATION_SCRIPT_PATH,
)
from logging_utils import ThreadSafeLogQueue
from workers import AcquisitionWorker, ReconstructionWorker, CalibrationWorker
from serial_handler import SerialHandler


class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window.
    
    This class contains:
    - All UI widgets (buttons, labels, log view, etc.)
    - Event handlers for user actions
    - Worker management (starting/stopping acquisition)
    - Serial communication management
    - Log display management
    
    Key design principles:
    1. NEVER block the main thread (use workers for heavy tasks)
    2. Use Qt signals/slots for communication (thread-safe)
    3. Batch UI updates to avoid overwhelming the event loop
    """
    
    def __init__(self, log_queue, acquisition_module_path="", reconstruction_root_path="", defect_map_path="", default_dark_map_path="", default_gain_map_path=""):
        super().__init__()
        self.setWindowTitle("CT Acquisition and Reconstruction")
        self.resize(1100, 720)
        self.setMinimumSize(1000, 760)
        
        # ====================================================================
        # PATH CONFIGURATION (passed from main.py)
        # ====================================================================
        self._acquisition_module_path = acquisition_module_path  # Path to camera SDK
        self._reconstruction_root_path = reconstruction_root_path  # Path to reconstruction scripts
        self._defect_map_path = defect_map_path  # Path to defect map (always loaded)
        self._default_dark_map_path = default_dark_map_path  # Path to dark map (always loaded)
        self._default_gain_map_path = default_gain_map_path  # Path to gain/flat field map (optional)
        
        # ====================================================================
        # APPLICATION STATE
        # ====================================================================
        self.save_dir = ""          # Directory for acquired images (user selects this)
        self.dark_map_path = self._default_dark_map_path  # Dark map path (auto-loaded)
        self.gain_map_path = self._default_gain_map_path  # Gain map path (auto-loaded, optional)
        self.recon_root = ""        # Root folder for reconstruction scripts
        self.recon_map = {}         # Maps method names to script paths
        self.last_preview_path = "" # Path to last preview image
        self.recon_input_override = ""  # NEW: Optional input folder for reconstruction-only mode
        
        # ====================================================================
        # LOG QUEUE (for displaying messages from workers)
        # ====================================================================
        # This queue is shared with workers - they put messages, we display
        self._log_queue = log_queue
        self._setup_log_timer()
        
        # ====================================================================
        # SERIAL HANDLER (for STM32 communication)
        # ====================================================================
        self.serial_handler = SerialHandler(self)
        # Connect signals to handlers
        self.serial_handler.message_received.connect(self._on_serial_message)
        self.serial_handler.connection_changed.connect(self._on_serial_connection_changed)
        
        # ====================================================================
        # WORKERS (for background tasks)
        # ====================================================================
        self.acq_worker = None    # Will be created when acquisition starts
        self.recon_worker = None  # Will be created when reconstruction starts
        self.calibration_worker = None  # NEW: Will be created when calibration runs
        self.calculated_shift = None  # NEW: Stores shift value from calibration
        
        # Build the UI and load defaults
        self._build_ui()
        self._load_defaults()
    
    def _setup_log_timer(self):
        """
        Setup timer to flush log messages to GUI.
        
        This is part of the freezing solution:
        - Instead of updating GUI on every log message (which would be slow)
        - We batch updates and flush them periodically
        - This keeps the GUI responsive even with heavy logging
        """
        self._log_flush_timer = QtCore.QTimer(self)
        self._log_flush_timer.setInterval(LOG_FLUSH_INTERVAL_MS)  # e.g., 250ms
        self._log_flush_timer.timeout.connect(self._flush_logs)
        self._log_flush_timer.start()
        self._is_flushing = False
        self._last_dropped_count = 0
    
    def _flush_logs(self):
        """Flush log messages from queue to GUI."""
        if self._is_flushing:
            return
        
        self._is_flushing = True
        try:
            msgs = self._log_queue.get_batch(max_items=LOG_MAX_ITEMS_PER_FLUSH)
            if not msgs:
                return
            
            # Check for dropped messages
            dropped = self._log_queue.get_dropped_count()
            if dropped > self._last_dropped_count:
                delta = dropped - self._last_dropped_count
                self._last_dropped_count = dropped
                msgs.insert(0, f"[LOG] Dropped {delta} messages to keep UI responsive")
            
            scrollbar = self.log_view.verticalScrollBar()
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 2
            
            self.log_view.appendPlainText("\n".join(msgs))
            
            if at_bottom:
                scrollbar.setValue(scrollbar.maximum())
        finally:
            self._is_flushing = False
    
    def _build_ui(self):
        """Build the main UI."""
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        
        # Create UI sections
        layout.addWidget(self._create_acquisition_group())
        layout.addWidget(self._create_serial_group())
        layout.addWidget(self._create_reconstruction_group())
        layout.addWidget(self._create_log_group())
        
        # Set stretch factors
        layout.setStretch(0, 0)
        layout.setStretch(1, 0)
        layout.setStretch(2, 0)
        layout.setStretch(3, 1)
        
        self.setCentralWidget(central)
    
    def _create_acquisition_group(self):
        """Create the acquisition controls group."""
        group = QtWidgets.QGroupBox("Acquisition")
        layout = QtWidgets.QGridLayout(group)
        
        # Labels
        self.save_dir_label = QtWidgets.QLabel("Save folder not selected")
        
        # Info label showing that dark map is auto-loaded
        self.dark_map_info = QtWidgets.QLabel("Dark map: Auto-loaded from config")
        self.dark_map_info.setStyleSheet("color: gray; font-style: italic;")

        # Info label showing gain map state
        if self.gain_map_path:
            gain_text = "Gain map: Auto-loaded from config"
        else:
            gain_text = "Gain map: Not configured (correction disabled)"
        self.gain_map_info = QtWidgets.QLabel(gain_text)
        self.gain_map_info.setStyleSheet("color: gray; font-style: italic;")

        # Buttons
        select_save_btn = QtWidgets.QPushButton("Select save folder")
        start_btn = QtWidgets.QPushButton("Start acquisition")
        stop_btn = QtWidgets.QPushButton("Stop")

        # Connect signals
        select_save_btn.clicked.connect(self._select_save_folder)
        start_btn.clicked.connect(self._start_acquisition)
        stop_btn.clicked.connect(self._stop_acquisition)

        # Layout
        layout.addWidget(select_save_btn,    0, 0)
        layout.addWidget(self.save_dir_label, 0, 1)
        layout.addWidget(self.dark_map_info,  1, 0, 1, 2)
        layout.addWidget(self.gain_map_info,  2, 0, 1, 2)
        layout.addWidget(start_btn,           3, 0)
        layout.addWidget(stop_btn,            3, 1)
        
        return group
    
    def _create_serial_group(self):
        """Create the serial control group."""
        group = QtWidgets.QGroupBox("Serial Control (STM32)")
        layout = QtWidgets.QGridLayout(group)
        
        # Port selection widgets
        self.serial_port_combo = QtWidgets.QComboBox()
        self.serial_refresh_btn = QtWidgets.QPushButton("Refresh")
        self.serial_connect_btn = QtWidgets.QPushButton("Connect")
        
        # Status label to show connection state
        self.serial_status_label = QtWidgets.QLabel("Not connected")
        self.serial_status_label.setStyleSheet("color: gray; font-style: italic;")
        
        # Manual command buttons - YOU control when to send OK and STOP
        self.serial_ok_btn = QtWidgets.QPushButton("Send OK")
        self.serial_ok_btn.setEnabled(False)  # Disabled until connected
        self.serial_stop_btn = QtWidgets.QPushButton("Send STOP")
        self.serial_stop_btn.setEnabled(False)  # Disabled until connected
        
        # NEW: Configure Motor button (sends CONFIG command with parameters)
        self.serial_config_btn = QtWidgets.QPushButton("Configure Motor")
        self.serial_config_btn.setEnabled(False)  # Disabled until connected
        self.serial_config_btn.setToolTip("Send CONFIG command to set projections and trigger times")
        
        # Connect signals
        self.serial_refresh_btn.clicked.connect(self._refresh_serial_ports)
        self.serial_connect_btn.clicked.connect(self._toggle_serial_connection)
        self.serial_ok_btn.clicked.connect(self._send_ok_command)
        self.serial_stop_btn.clicked.connect(self._send_stop_command)
        self.serial_config_btn.clicked.connect(self._configure_motor)
        
        # Layout
        layout.addWidget(QtWidgets.QLabel("Port"), 0, 0)
        layout.addWidget(self.serial_port_combo, 0, 1)
        layout.addWidget(self.serial_refresh_btn, 0, 2)
        layout.addWidget(self.serial_connect_btn, 0, 3)
        layout.addWidget(QtWidgets.QLabel("Status"), 1, 0)
        layout.addWidget(self.serial_status_label, 1, 1, 1, 3)
        layout.addWidget(QtWidgets.QLabel("Commands"), 2, 0)
        layout.addWidget(self.serial_ok_btn, 2, 1)
        layout.addWidget(self.serial_stop_btn, 2, 2)
        layout.addWidget(self.serial_config_btn, 3, 1, 1, 2)  # Spans 2 columns
        
        return group
    
    def _create_reconstruction_group(self):
        """Create the reconstruction controls group."""
        group = QtWidgets.QGroupBox("Reconstruction")
        layout = QtWidgets.QHBoxLayout(group)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(12)
        
        # Left panel - controls
        left_panel = self._create_recon_controls_panel()
        
        # Right panel - config editor
        self.recon_config_group = self._create_recon_config_panel()
        
        layout.addWidget(left_panel, 1)
        layout.addWidget(self.recon_config_group, 1)
        layout.setStretch(0, 3)
        layout.setStretch(1, 2)
        
        return group
    
    def _create_recon_controls_panel(self):
        """Create the reconstruction controls panel."""
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout(panel)
        layout.setVerticalSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Root folder selection
        self.recon_root_label = QtWidgets.QLabel("Reconstruction root folder")
        select_recon_root_btn = QtWidgets.QPushButton("Select reconstruction root")
        select_recon_root_btn.clicked.connect(self._select_recon_root)
        
        # Method list
        self.recon_list = QtWidgets.QListWidget()
        self.recon_list.setMinimumHeight(120)
        self.recon_list.itemSelectionChanged.connect(self._on_recon_method_changed)
        
        # Arguments
        self.recon_args = QtWidgets.QLineEdit()
        self.recon_args.setPlaceholderText("Additional arguments")
        
        # NEW: Input folder selection (for reconstruction-only mode)
        # Allows running reconstruction without doing acquisition first
        select_input_btn = QtWidgets.QPushButton("Select input folder")
        select_input_btn.clicked.connect(self._select_recon_input)
        select_input_btn.setToolTip("Select folder with images for reconstruction (optional - uses acquisition folder if not set)")
        
        self.recon_input_label = QtWidgets.QLabel("Input: (uses acquisition save folder)")
        self.recon_input_label.setStyleSheet("color: gray; font-style: italic;")
        
        # NEW: Calibration checkbox - run calibration before reconstruction
        self.run_calibration_checkbox = QtWidgets.QCheckBox("Run calibration first")
        self.run_calibration_checkbox.setToolTip("Run calibration script before reconstruction to calculate shift value automatically")
        self.calibration_status_label = QtWidgets.QLabel("Calibration: Not run")
        self.calibration_status_label.setStyleSheet("color: gray; font-size: 9pt; font-style: italic;")
        
        # Output folder
        self.recon_output_dir = ""
        select_output_btn = QtWidgets.QPushButton("Select output folder")
        select_output_btn.clicked.connect(self._select_recon_output)
        self.recon_output_label = QtWidgets.QLabel("Output folder not selected")
        
        # Iterative algorithm selector
        self.recon_algorithm_label = QtWidgets.QLabel("Iterative algorithm")
        self.recon_algorithm_combo = QtWidgets.QComboBox()
        self.recon_algorithm_combo.addItems(ITERATIVE_ALGORITHMS)
        self.recon_algorithm_combo.setCurrentIndex(0)
        self.recon_algorithm_combo.currentTextChanged.connect(self._on_recon_method_changed)
        self.recon_algorithm_combo.currentTextChanged.connect(self._on_algorithm_changed)  # NEW
        self.recon_algorithm_label.setVisible(False)
        self.recon_algorithm_combo.setVisible(False)
        
        # NEW: Iterations input (for iterative algorithms only)
        self.recon_iterations_label = QtWidgets.QLabel("Iterations")
        self.recon_iterations_spin = QtWidgets.QSpinBox()
        self.recon_iterations_spin.setRange(1, 500)  # Min 1, max 500 iterations
        self.recon_iterations_spin.setValue(50)  # Default
        self.recon_iterations_spin.setToolTip("Number of iterations for the iterative algorithm")
        self.recon_iterations_label.setVisible(False)
        self.recon_iterations_spin.setVisible(False)
        
        # Run button
        run_recon_btn = QtWidgets.QPushButton("Run reconstruction")
        run_recon_btn.clicked.connect(self._run_reconstruction)
        
        # Layout
        layout.addWidget(select_recon_root_btn, 0, 0)
        layout.addWidget(self.recon_root_label, 0, 1)
        layout.addWidget(self.recon_list, 1, 0, 1, 2)
        layout.addWidget(self.recon_args, 2, 0, 1, 2)
        layout.addWidget(select_input_btn, 3, 0)  # NEW: Input folder button
        layout.addWidget(self.recon_input_label, 3, 1)
        layout.addWidget(self.run_calibration_checkbox, 4, 0)  # NEW: Calibration checkbox
        layout.addWidget(self.calibration_status_label, 4, 1)  # NEW: Calibration status
        layout.addWidget(select_output_btn, 5, 0)
        layout.addWidget(self.recon_output_label, 5, 1)
        layout.addWidget(self.recon_algorithm_label, 6, 0)
        layout.addWidget(self.recon_algorithm_combo, 6, 1)
        layout.addWidget(self.recon_iterations_label, 7, 0)  # NEW: Iterations
        layout.addWidget(self.recon_iterations_spin, 7, 1)  # NEW: Iterations
        layout.addWidget(run_recon_btn, 8, 0, 1, 2)
        layout.setRowMinimumHeight(1, 120)
        layout.setColumnStretch(1, 1)
        
        return panel
    
    def _create_recon_config_panel(self):
        """Create the reconstruction config editor panel."""
        group = QtWidgets.QGroupBox("Reconstruction parameters")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.recon_config_scroll = QtWidgets.QScrollArea()
        self.recon_config_scroll.setWidgetResizable(True)
        self.recon_config_container = QtWidgets.QWidget()
        self.recon_form_layout = QtWidgets.QFormLayout(self.recon_config_container)
        self.recon_form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        self.recon_config_scroll.setWidget(self.recon_config_container)

        self._recon_config_widgets = {}
        self._recon_config_meta = {}
        self._reset_recon_config_editor()
        
        self.reset_config_btn = QtWidgets.QPushButton("Use default config")
        self.reset_config_btn.clicked.connect(self._reset_recon_config_editor)
        
        layout.addWidget(self.recon_config_scroll)
        layout.addWidget(self.reset_config_btn)
        
        return group
    
    def _create_log_group(self):
        """Create the log view group."""
        group = QtWidgets.QGroupBox("Logs")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(220)
        self.log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.log_view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.log_view.setMaximumBlockCount(LOG_VIEW_MAX_BLOCKS)
        self.log_view.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.log_view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.log_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        
        group.setMinimumHeight(220)
        group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.MinimumExpanding)
        layout.addWidget(self.log_view)
        
        return group
    
    def _load_defaults(self):
        """Load default settings."""
        self._load_default_reconstruction_root()
        self._refresh_serial_ports()
    
    # ========================================================================
    # ACQUISITION HANDLERS
    # ========================================================================
    
    def _select_save_folder(self):
        # Open a folder selection dialog
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select save folder")
        if path:  # If user selected a folder (didn't cancel)
            self.save_dir = os.path.normpath(path)  # Normalize the path
            self.save_dir_label.setText(self.save_dir)  # Update label to show path
            # Update reconstruction input label to show this is where images will be
            self.recon_input_label.setText(f"Input: {self.save_dir}")
            self.recon_input_label.setStyleSheet("")  # Remove gray italic style
    
    def _start_acquisition(self):
        # Check if user selected a save folder first
        if not self.save_dir:
            QtWidgets.QMessageBox.warning(self, "Missing data", "Select a save folder first")
            return
        # Check if acquisition is already running
        if self.acq_worker and self.acq_worker.is_running():
            return
        
        # Start the acquisition worker (full acquisition, not preview)
        self._start_acq_worker(preview_only=False)
    
    def _start_acq_worker(self, preview_only):
        """Create and start the acquisition worker."""
        # Create a new AcquisitionWorker object
        # This class manages the acquisition process (camera operations)
        self.acq_worker = AcquisitionWorker(
            self,  # Parent widget
            acquisition_module_path=self._acquisition_module_path,  # Path to camera SDK
            defect_map_path=self._defect_map_path  # Path to defect map for image correction
        )
        # Connect Qt signals to our handler methods
        # When the worker emits a signal, our method gets called
        self.acq_worker.preview_ready.connect(self._show_preview)  # When preview image is ready
        self.acq_worker.finished.connect(self._on_acq_finished)  # When acquisition completes/fails
        self.acq_worker.progress.connect(self._on_acq_progress)  # When progress updates arrive
        self.acq_worker.started_work.connect(self._on_acq_started)  # When acquisition starts
        # Start the worker with our parameters
        self.acq_worker.start(self.save_dir, self.dark_map_path, self.gain_map_path, preview_only)
    
    def _stop_acquisition(self):
        if self.acq_worker and self.acq_worker.is_running():
            self.acq_worker.request_stop()
            # Note: If you want to stop the motor, click the "Send STOP" button manually
    
    def _on_acq_started(self):
        self.setCursor(QtCore.Qt.BusyCursor)
        self.statusBar().showMessage("Acquisition in progress...")
    
    def _on_acq_progress(self, message):
        # Truncate long messages for status bar (max 80 characters)
        status_msg = message[:80] + "..." if len(message) > 80 else message
        self.statusBar().showMessage(status_msg)  # Update bottom status bar
        # Log full message to log view (not truncated)
        logging.info(message)
        
        # Note: Manual control - YOU decide when to send OK via the button
        # No automatic sending of commands
    
    def _on_acq_finished(self, ok, message):
        # Restore normal cursor (no longer busy)
        self.setCursor(QtCore.Qt.ArrowCursor)
        # Clear the status bar message
        self.statusBar().clearMessage()
        # Show popup dialog with result
        if ok:  # If acquisition succeeded
            QtWidgets.QMessageBox.information(self, "Acquisition", message)
        else:  # If acquisition failed
            QtWidgets.QMessageBox.critical(self, "Acquisition", message)
    
    def _show_preview(self, preview_path):
        """Show preview image (if preview label exists)."""
        # Check if preview file actually exists
        if not preview_path or not os.path.exists(preview_path):
            return
        # Store the path (could be used to display image later)
        self.last_preview_path = preview_path
        # Log that preview was saved
        logging.info(f"Preview saved: {preview_path}")
    
    # ========================================================================
    # SERIAL HANDLERS
    # ========================================================================
    
    def _refresh_serial_ports(self):
        # Clear the dropdown menu
        self.serial_port_combo.clear()
        # Get list of available serial ports from the system
        ports = self.serial_handler.get_available_ports()
        if ports:  # If any ports found
            self.serial_port_combo.addItems(ports)  # Add them to dropdown
        else:  # No ports found
            self.serial_port_combo.addItem("No ports found")
    
    def _toggle_serial_connection(self):
        # If already connected, disconnect
        if self.serial_handler.is_connected():
            self.serial_handler.disconnect()
        else:
            # Get the selected port name from the dropdown
            port_name = self.serial_port_combo.currentText()
            if not port_name or port_name == "No ports found":
                QtWidgets.QMessageBox.warning(self, "Serial", "No serial port selected")
                return
            # Use fixed baud rate of 115200 (standard for STM32)
            if not self.serial_handler.connect(port_name, 115200):
                QtWidgets.QMessageBox.warning(self, "Serial", f"Failed to open {port_name}")
    
    def _on_serial_connection_changed(self, connected):
        # Update button text based on connection state
        self.serial_connect_btn.setText("Disconnect" if connected else "Connect")
        # Enable/disable command buttons based on connection
        self.serial_ok_btn.setEnabled(connected)
        self.serial_stop_btn.setEnabled(connected)
        self.serial_config_btn.setEnabled(connected)  # NEW: Enable/disable config button
        # Update status label
        if connected:
            port_name = self.serial_port_combo.currentText()
            self.serial_status_label.setText(f"Connected to {port_name} - Ready for manual commands")
            self.serial_status_label.setStyleSheet("color: green;")
        else:
            self.serial_status_label.setText("Not connected")
            self.serial_status_label.setStyleSheet("color: gray; font-style: italic;")
    
    def _on_serial_message(self, message):
        # Log all messages received from STM32
        logging.info(f"[SERIAL] {message}")
    
    def _send_ok_command(self):
        """Send OK command to STM32 (manually triggered by user)"""
        if self.serial_handler.is_connected():
            self.serial_handler.send("OK")
            logging.info("[MANUAL] Sent OK command to motor")
        else:
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
    
    def _send_stop_command(self):
        """Send STOP command to STM32 (manually triggered by user)"""
        if self.serial_handler.is_connected():
            self.serial_handler.send("STOP")
            logging.info("[MANUAL] Sent STOP command to motor")
        else:
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
    
    def _send_ok_command(self):
        """Send OK command to STM32 (manually triggered by user)"""
        if self.serial_handler.is_connected():
            self.serial_handler.send("OK")
            logging.info("[MANUAL] Sent OK command to motor")
        else:
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
    
    def _send_stop_command(self):
        """Send STOP command to STM32 (manually triggered by user)"""
        if self.serial_handler.is_connected():
            self.serial_handler.send("STOP")
            logging.info("[MANUAL] Sent STOP command to motor")
        else:
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
    
    def _configure_motor(self):
        """
        Open dialog to configure motor parameters.
        Sends CONFIG command followed by projections, HIGH time, and LOW time.
        """
        # Check if connected first
        if not self.serial_handler.is_connected():
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
            return
        
        # Open the configuration dialog
        dialog = MotorConfigDialog(self)
        
        # If user clicks OK in the dialog
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            # Get the values from the dialog
            projections, high_time, low_time = dialog.get_values()
            
            # Send CONFIG command
            logging.info(f"[CONFIG] Sending motor configuration: projections={projections}, HIGH={high_time}ms, LOW={low_time}ms")
            self.serial_handler.send("CONFIG")
            
            # Small delay to let firmware process the command
            QtCore.QThread.msleep(100)
            
            # Send the three parameters (firmware expects them line by line)
            self.serial_handler.send(str(projections))
            QtCore.QThread.msleep(50)
            
            self.serial_handler.send(str(high_time))
            QtCore.QThread.msleep(50)
            
            self.serial_handler.send(str(low_time))
            
            logging.info("[CONFIG] Motor configuration commands sent successfully")
    
    # ========================================================================
    # RECONSTRUCTION HANDLERS
    # ========================================================================
    
    def _select_recon_root(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select reconstruction root")
        if path:
            self.recon_root = os.path.normpath(path)
            self.recon_root_label.setText(self.recon_root)
            self._scan_reconstruction_methods()
    
    def _load_default_reconstruction_root(self):
        if self._reconstruction_root_path:
            self.recon_root = self._reconstruction_root_path
            self.recon_root_label.setText(self.recon_root)
            self._scan_reconstruction_methods()
    
    def _scan_reconstruction_methods(self):
        self.recon_list.clear()
        self.recon_map = {}
        if not self.recon_root:
            return
        
        root = Path(self.recon_root)
        mapping = {
            "FDK_reduce_memory": root / "FDK_reduce_memory" / "MAIN_TIGRE_FDK_Voxel_size.py",
            "Iteratives": root / "Iteratives" / "MAIN_TIGRE_iterative.py",
            "FBP": root / "FBP" / "TIGRE_fbp1.py"
        }
        
        for name, path in mapping.items():
            if path.exists():
                self.recon_map[name] = str(path)
                self.recon_list.addItem(name)
    
    def _select_recon_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.recon_output_dir = os.path.normpath(path)
            self.recon_output_label.setText(self.recon_output_dir)
    
    def _select_recon_input(self):
        """
        NEW: Select input folder for reconstruction (reconstruction-only mode).
        This allows you to run reconstruction without doing acquisition first.
        """
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select input folder for reconstruction"
        )
        if path:
            # Store the override folder
            self.recon_input_override = os.path.normpath(path)
            # Update the label to show selected folder
            self.recon_input_label.setText(f"Input: {self.recon_input_override}")
            self.recon_input_label.setStyleSheet("")  # Remove gray italic style
            logging.info(f"[RECON] Input folder set to: {self.recon_input_override}")
    
    def _is_iterative_method(self, method_name):
        return method_name.lower().endswith("iteratives") or "iterative" in method_name.lower()
    
    def _is_fbp_method(self, method_name):
        return method_name.upper() == "FBP"
    
    def _on_recon_method_changed(self):
        selected_items = self.recon_list.selectedItems()
        if not selected_items:
            self.recon_algorithm_label.setVisible(False)
            self.recon_algorithm_combo.setVisible(False)
            self.recon_iterations_label.setVisible(False)  # NEW
            self.recon_iterations_spin.setVisible(False)  # NEW
            self.recon_config_group.setVisible(True)
            return
        
        method_name = selected_items[0].text()
        is_iterative = self._is_iterative_method(method_name)
        self.recon_algorithm_label.setVisible(is_iterative)
        self.recon_algorithm_combo.setVisible(is_iterative)
        self.recon_iterations_label.setVisible(is_iterative)  # NEW
        self.recon_iterations_spin.setVisible(is_iterative)  # NEW
        self.recon_config_group.setVisible(True)
        
        # Update config editor based on selected method
        self._reset_recon_config_editor()
    
    def _on_algorithm_changed(self, algorithm_name):
        """
        NEW: Called when iterative algorithm selection changes.
        Updates the iterations spinbox with the default for that algorithm.
        """
        # Skip if "Select algorithm..." is selected
        if algorithm_name == "Select algorithm...":
            return
        
        # Get default iterations for this algorithm
        default_iterations = ITERATIVE_ALGORITHM_ITERATIONS.get(algorithm_name, 50)
        self.recon_iterations_spin.setValue(default_iterations)
        logging.info(f"[RECON] Algorithm changed to {algorithm_name}, iterations set to {default_iterations}")
    def _get_current_default_config(self):
        selected_items = self.recon_list.selectedItems()
        if selected_items:
            method_name = selected_items[0].text()
            if self._is_fbp_method(method_name):
                return FBP_RECON_CONFIG
        return DEFAULT_RECON_CONFIG
    
    def _reset_recon_config_editor(self):
        config = self._get_current_default_config()
        self._build_recon_config_form(config)
    
    def _get_recon_config(self):
        if not self._recon_config_widgets:
            return self._get_current_default_config()

        config = {}
        for key, widget in self._recon_config_widgets.items():
            meta = self._recon_config_meta.get(key, {})
            value_type = meta.get("type", str)
            is_list = meta.get("is_list", False)

            if isinstance(widget, QtWidgets.QCheckBox):
                config[key] = widget.isChecked()
                continue

            text = ""
            if isinstance(widget, QtWidgets.QComboBox):
                text = widget.currentText().strip()
            elif isinstance(widget, QtWidgets.QLineEdit):
                text = widget.text().strip()

            if is_list:
                if not text:
                    config[key] = []
                else:
                    parts = [part.strip() for part in text.split(",") if part.strip()]
                    config[key] = parts
                continue

            if value_type in (int, float):
                try:
                    num = float(text) if text else 0.0
                    config[key] = int(num) if value_type is int else float(num)
                except Exception:
                    QtWidgets.QMessageBox.warning(self, "Reconstruction", f"Invalid numeric value for {key}")
                    return None
                continue

            config[key] = text

        return config

    def _build_recon_config_form(self, config):
        # Clear existing rows
        while self.recon_form_layout.rowCount() > 0:
            self.recon_form_layout.removeRow(0)

        self._recon_config_widgets = {}
        self._recon_config_meta = {}

        for key, value in config.items():
            label = QtWidgets.QLabel(key)

            if isinstance(value, bool):
                widget = QtWidgets.QCheckBox()
                widget.setChecked(value)
                self._recon_config_meta[key] = {"type": bool, "is_list": False}
            elif isinstance(value, (int, float)):
                widget = QtWidgets.QLineEdit(str(value))
                if isinstance(value, int):
                    validator = QtGui.QIntValidator(widget)
                else:
                    validator = QtGui.QDoubleValidator(widget)
                    validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
                widget.setValidator(validator)
                self._recon_config_meta[key] = {"type": type(value), "is_list": False}
            elif isinstance(value, list):
                widget = QtWidgets.QLineEdit(", ".join(str(item) for item in value))
                self._recon_config_meta[key] = {"type": list, "is_list": True}
            else:
                widget = QtWidgets.QLineEdit(str(value))
                self._recon_config_meta[key] = {"type": str, "is_list": False}

            self._recon_config_widgets[key] = widget
            self.recon_form_layout.addRow(label, widget)
    
    def _run_reconstruction(self):
        """
        Run reconstruction (optionally with calibration first).
        
        NEW: If "Run calibration first" is checked:
        1. Run calibration script to calculate shift value
        2. Update calibrated_shift_px parameter automatically
        3. Then run reconstruction with the new shift value
        """
        # Check if reconstruction is already running
        if self.recon_worker and self.recon_worker.is_running():
            return
        
        # Check if calibration is running
        if self.calibration_worker and self.calibration_worker.is_running():
            return
        
        # Validate reconstruction method selection
        selected_items = self.recon_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "Select a reconstruction method")
            return
        
        method_name = selected_items[0].text()
        main_path = self.recon_map.get(method_name)
        if not main_path:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "Invalid reconstruction method")
            return
        
        if self._is_iterative_method(method_name) and self.recon_algorithm_combo.currentIndex() == 0:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "Select an iterative algorithm")
            return
        
        # NEW: Check if we need to run calibration first
        if self.run_calibration_checkbox.isChecked():
            # Run calibration before reconstruction
            self._run_calibration_then_reconstruction()
            return
        
        # Otherwise, proceed directly with reconstruction
        self._do_reconstruction()
    
    def _run_calibration_then_reconstruction(self):
        """
        Run calibration first, then automatically run reconstruction.
        This is called when user checks "Run calibration first" checkbox.
        """
        # Get input folder for calibration
        input_folder = self.recon_input_override or self.save_dir
        
        if not input_folder:
            QtWidgets.QMessageBox.warning(
                self, "Calibration",
                "No input folder selected.\n\nSelect input folder first."
            )
            return
        
        # Check if calibration script exists
        if not os.path.exists(CALIBRATION_SCRIPT_PATH):
            QtWidgets.QMessageBox.warning(
                self, "Calibration",
                f"Calibration script not found:\n{CALIBRATION_SCRIPT_PATH}"
            )
            return
        
        logging.info("[CALIBRATION] Starting calibration before reconstruction...")
        self.calibration_status_label.setText("Calibration: Running...")
        self.calibration_status_label.setStyleSheet("color: orange; font-size: 9pt;")
        
        # Create and start calibration worker
        self.calibration_worker = CalibrationWorker(CALIBRATION_SCRIPT_PATH, input_folder)
        self.calibration_worker.finished.connect(self._on_calibration_finished)
        self.calibration_worker.progress.connect(self._on_calibration_progress)
        self.calibration_worker.shift_found.connect(self._on_shift_found)
        self.calibration_worker.start()
        
        self.setCursor(QtCore.Qt.BusyCursor)
        self.statusBar().showMessage("Running calibration...")
    
    def _on_shift_found(self, shift_value):
        """Called when calibration finds the shift value."""
        self.calculated_shift = shift_value
        logging.info(f"[CALIBRATION] Shift value found: {shift_value}")
        
        # Update the calibrated_shift_px parameter in the config widgets
        if "calibrated_shift_px" in self._recon_config_widgets:
            widget = self._recon_config_widgets["calibrated_shift_px"]
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.setText(str(shift_value))
                logging.info(f"[CALIBRATION] Updated calibrated_shift_px parameter to {shift_value}")
    
    def _on_calibration_progress(self, message):
        """Called for calibration progress updates."""
        self.statusBar().showMessage(message)
        logging.info(f"[CALIBRATION] {message}")
    
    def _on_calibration_finished(self, ok, message):
        """Called when calibration finishes."""
        self.setCursor(QtCore.Qt.ArrowCursor)
        
        if ok:
            # Calibration succeeded
            if self.calculated_shift is not None:
                self.calibration_status_label.setText(f"Calibration: Done (shift = {self.calculated_shift:.2f})")
                self.calibration_status_label.setStyleSheet("color: green; font-size: 9pt;")
                logging.info(f"[CALIBRATION] Calibration completed successfully")
                
                # Automatically proceed with reconstruction
                self.statusBar().showMessage("Calibration done. Starting reconstruction...")
                QtCore.QTimer.singleShot(500, self._do_reconstruction)  # Small delay
            else:
                # Calibration finished but no shift found
                self.calibration_status_label.setText("Calibration: No shift value found")
                self.calibration_status_label.setStyleSheet("color: orange; font-size: 9pt;")
                
                reply = QtWidgets.QMessageBox.question(
                    self, "Calibration",
                    "Calibration completed but shift value was not found in output.\n\nProceed with reconstruction anyway?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                )
                if reply == QtWidgets.QMessageBox.Yes:
                    QtCore.QTimer.singleShot(500, self._do_reconstruction)
        else:
            # Calibration failed
            self.calibration_status_label.setText("Calibration: Failed")
            self.calibration_status_label.setStyleSheet("color: red; font-size: 9pt;")
            QtWidgets.QMessageBox.critical(self, "Calibration", message)
            self.statusBar().clearMessage()
    
    def _do_reconstruction(self):
        """
        Actually run the reconstruction.
        This is called either directly or after calibration completes.
        """
        # Get reconstruction method selection
        selected_items = self.recon_list.selectedItems()
        if not selected_items:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "Select a reconstruction method")
            return
        
        method_name = selected_items[0].text()
        main_path = self.recon_map.get(method_name)
        if not main_path:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "Invalid reconstruction method")
            return
        
        # Parse arguments
        args = self.recon_args.text().strip().split() if self.recon_args.text().strip() else []
        
        # Get input folder
        input_folder = self.recon_input_override or self.save_dir
        
        if input_folder:
            args.extend(["--input", input_folder])
        else:
            # No input folder selected at all
            QtWidgets.QMessageBox.warning(
                self, "Reconstruction", 
                "No input folder selected.\n\nEither:\n- Do an acquisition first, OR\n- Click 'Select input folder' to choose existing images"
            )
            return
            
        if self.recon_output_dir:
            args.extend(["--output", self.recon_output_dir])
        
        recon_config = self._get_recon_config()
        if recon_config is None:
            return
        
        # Set environment variables for reconstruction script
        env_vars = {}
        
        # Use input_folder (can be override or save_dir) for all input-related env vars
        if input_folder:
            env_vars["ACQ_INPUT_DIR"] = input_folder
            env_vars["RECON_INPUT_DIR"] = input_folder
            env_vars["INPUT_DIR"] = input_folder
            env_vars["INPUT_FOLDER"] = input_folder
            env_vars["SAVE_DIR"] = input_folder
        
        if self.recon_output_dir:
            env_vars["RECON_OUTPUT_DIR"] = self.recon_output_dir
        
        # Send reconstruction config as JSON (check if your scripts read this!)
        env_vars["RECON_CONFIG_JSON"] = json.dumps(recon_config)
        env_vars["RECON_ALGORITHM"] = self.recon_algorithm_combo.currentText()
        
        # NEW: Send iterations value for iterative algorithms
        # Your reconstruction scripts should read this: os.environ.get("RECON_ITERATIONS")
        env_vars["RECON_ITERATIONS"] = str(self.recon_iterations_spin.value())
        
        self.recon_worker = ReconstructionWorker(main_path, args, env_vars)
        self.recon_worker.finished.connect(self._on_recon_finished)
        self.recon_worker.progress.connect(self._on_recon_progress)
        self.recon_worker.input_requested.connect(self._on_recon_input_requested)
        self.recon_worker.start()
        
        self.setCursor(QtCore.Qt.BusyCursor)
        self.statusBar().showMessage("Reconstruction in progress...")
    
    def _on_recon_progress(self, message):
        self.statusBar().showMessage(message)
        logging.info(f"[RECON] {message}")
    
    def _on_recon_finished(self, ok, message):
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.statusBar().clearMessage()
        if ok:
            QtWidgets.QMessageBox.information(self, "Reconstruction", message)
        else:
            QtWidgets.QMessageBox.critical(self, "Reconstruction", message)

    def _on_recon_input_requested(self, prompt):
        title = "Reconstruction Input"
        display_prompt = prompt.strip() if prompt else "Enter value"
        text, ok = QtWidgets.QInputDialog.getText(self, title, display_prompt)
        if not ok:
            text = ""
        if self.recon_worker:
            self.recon_worker.send_input_response(text)
    
    def closeEvent(self, event):
        """
        Called when the window is closing.
        
        Ensures the serial port is disconnected so other applications
        (Arduino IDE, PuTTY, etc.) can access the STM32.
        """
        if self.serial_handler.is_connected():
            logging.info("Closing GUI: Disconnecting serial port...")
            self.serial_handler.disconnect()
            # Give time for port to be fully released
            QtCore.QThread.msleep(200)
        event.accept()


# ============================================================================
# MOTOR CONFIGURATION DIALOG
# ============================================================================

class MotorConfigDialog(QtWidgets.QDialog):
    """
    Simple dialog for configuring motor parameters.
    
    This dialog allows the user to set:
    - Number of projections (10-3600)
    - Trigger HIGH time in milliseconds (10-5000)
    - Trigger LOW time in milliseconds (10-5000)
    
    When OK is clicked, these values are sent to the STM32 via CONFIG command.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Motor Configuration")
        self.setModal(True)  # Block interaction with main window
        self.setMinimumWidth(400)
        
        # Create the layout
        layout = QtWidgets.QVBoxLayout(self)
        
        # Form layout for input fields
        form = QtWidgets.QFormLayout()
        
        # ====================================================================
        # PROJECTIONS INPUT
        # ====================================================================
        self.projections_spin = QtWidgets.QSpinBox()
        self.projections_spin.setRange(*MOTOR_CONFIG_RANGES["projections"])  # 10 to 3600
        self.projections_spin.setValue(MOTOR_CONFIG_DEFAULTS["projections"])  # Default: 800
        self.projections_spin.setSingleStep(10)  # Increment by 10
        
        # Label with range info
        proj_label = QtWidgets.QLabel("Number of projections:")
        proj_help = QtWidgets.QLabel(f"(Range: {MOTOR_CONFIG_RANGES['projections'][0]} - {MOTOR_CONFIG_RANGES['projections'][1]})")
        proj_help.setStyleSheet("color: gray; font-size: 9pt;")
        
        form.addRow(proj_label, self.projections_spin)
        form.addRow("", proj_help)
        
        # ====================================================================
        # HIGH TIME INPUT
        # ====================================================================
        self.high_time_spin = QtWidgets.QSpinBox()
        self.high_time_spin.setRange(*MOTOR_CONFIG_RANGES["high_time_ms"])  # 10 to 5000
        self.high_time_spin.setValue(MOTOR_CONFIG_DEFAULTS["high_time_ms"])  # Default: 400
        self.high_time_spin.setSingleStep(10)  # Increment by 10
        self.high_time_spin.setSuffix(" ms")  # Show "ms" after number
        
        high_label = QtWidgets.QLabel("Trigger HIGH time:")
        high_help = QtWidgets.QLabel(f"(Range: {MOTOR_CONFIG_RANGES['high_time_ms'][0]} - {MOTOR_CONFIG_RANGES['high_time_ms'][1]} ms)")
        high_help.setStyleSheet("color: gray; font-size: 9pt;")
        
        form.addRow(high_label, self.high_time_spin)
        form.addRow("", high_help)
        
        # ====================================================================
        # LOW TIME INPUT
        # ====================================================================
        self.low_time_spin = QtWidgets.QSpinBox()
        self.low_time_spin.setRange(*MOTOR_CONFIG_RANGES["low_time_ms"])  # 10 to 5000
        self.low_time_spin.setValue(MOTOR_CONFIG_DEFAULTS["low_time_ms"])  # Default: 100
        self.low_time_spin.setSingleStep(10)  # Increment by 10
        self.low_time_spin.setSuffix(" ms")  # Show "ms" after number
        
        low_label = QtWidgets.QLabel("Trigger LOW time:")
        low_help = QtWidgets.QLabel(f"(Range: {MOTOR_CONFIG_RANGES['low_time_ms'][0]} - {MOTOR_CONFIG_RANGES['low_time_ms'][1]} ms)")
        low_help.setStyleSheet("color: gray; font-size: 9pt;")
        
        form.addRow(low_label, self.low_time_spin)
        form.addRow("", low_help)
        
        # ====================================================================
        # CALCULATED STEP ANGLE (READ-ONLY, UPDATES AUTOMATICALLY)
        # ====================================================================
        self.step_angle_label = QtWidgets.QLabel()
        self.step_angle_label.setStyleSheet("font-weight: bold;")
        self._update_step_angle()  # Calculate initial value
        
        # Update step angle whenever projections value changes
        self.projections_spin.valueChanged.connect(self._update_step_angle)
        
        form.addRow("Step angle (calculated):", self.step_angle_label)
        
        # Add form to main layout
        layout.addLayout(form)
        
        # ====================================================================
        # OK AND CANCEL BUTTONS
        # ====================================================================
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)  # OK clicked
        button_box.rejected.connect(self.reject)  # Cancel clicked
        
        layout.addWidget(button_box)
    
    def _update_step_angle(self):
        """Calculate and display step angle based on projections."""
        projections = self.projections_spin.value()
        step_angle = 360.0 / projections  # 360 degrees divided by number of steps
        self.step_angle_label.setText(f"{step_angle:.3f}°")
    
    def get_values(self):
        """
        Return the configured values as a tuple.
        
        Returns:
            tuple: (projections, high_time_ms, low_time_ms)
        """
        return (
            self.projections_spin.value(),
            self.high_time_spin.value(),
            self.low_time_spin.value()
        )
