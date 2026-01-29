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
    LOG_FLUSH_INTERVAL_MS,
    LOG_MAX_ITEMS_PER_FLUSH,
    LOG_VIEW_MAX_BLOCKS,
)
from logging_utils import ThreadSafeLogQueue
from workers import AcquisitionWorker, ReconstructionWorker
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
    
    def __init__(self, log_queue, acquisition_module_path="", reconstruction_root_path="", defect_map_path=""):
        super().__init__()
        self.setWindowTitle("CT Acquisition and Reconstruction")
        self.resize(1100, 720)
        self.setMinimumSize(1000, 760)
        
        # ====================================================================
        # PATH CONFIGURATION (passed from main.py)
        # ====================================================================
        self._acquisition_module_path = acquisition_module_path
        self._reconstruction_root_path = reconstruction_root_path
        self._defect_map_path = defect_map_path
        
        # ====================================================================
        # APPLICATION STATE
        # ====================================================================
        self.save_dir = ""          # Directory for acquired images
        self.dark_map_path = ""     # Path to dark map for correction
        self.recon_root = ""        # Root folder for reconstruction scripts
        self.recon_map = {}         # Maps method names to script paths
        self.last_preview_path = "" # Path to last preview image
        
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
        self.dark_map_label = QtWidgets.QLabel("Dark map not selected")
        
        # Buttons
        select_save_btn = QtWidgets.QPushButton("Select save folder")
        select_dark_btn = QtWidgets.QPushButton("Select dark map")
        preview_btn = QtWidgets.QPushButton("Preview only")
        start_btn = QtWidgets.QPushButton("Start acquisition")
        stop_btn = QtWidgets.QPushButton("Stop")
        
        # Connect signals
        select_save_btn.clicked.connect(self._select_save_folder)
        select_dark_btn.clicked.connect(self._select_dark_map)
        preview_btn.clicked.connect(self._run_preview)
        start_btn.clicked.connect(self._start_acquisition)
        stop_btn.clicked.connect(self._stop_acquisition)
        
        # Layout
        layout.addWidget(select_save_btn, 0, 0)
        layout.addWidget(self.save_dir_label, 0, 1)
        layout.addWidget(select_dark_btn, 1, 0)
        layout.addWidget(self.dark_map_label, 1, 1)
        layout.addWidget(preview_btn, 2, 0)
        layout.addWidget(start_btn, 2, 1)
        layout.addWidget(stop_btn, 2, 2)
        
        return group
    
    def _create_serial_group(self):
        """Create the serial control group."""
        group = QtWidgets.QGroupBox("Serial Control (STM32)")
        layout = QtWidgets.QGridLayout(group)
        
        # Widgets
        self.serial_port_combo = QtWidgets.QComboBox()
        self.serial_refresh_btn = QtWidgets.QPushButton("Refresh")
        self.serial_baud_combo = QtWidgets.QComboBox()
        self.serial_baud_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.serial_baud_combo.setCurrentText("115200")
        self.serial_connect_btn = QtWidgets.QPushButton("Connect")
        self.serial_input = QtWidgets.QLineEdit()
        self.serial_input.setPlaceholderText("Type command and press Enter")
        self.serial_send_btn = QtWidgets.QPushButton("Send")
        
        # Connect signals
        self.serial_refresh_btn.clicked.connect(self._refresh_serial_ports)
        self.serial_connect_btn.clicked.connect(self._toggle_serial_connection)
        self.serial_send_btn.clicked.connect(self._send_serial_text)
        self.serial_input.returnPressed.connect(self._send_serial_text)
        
        # Layout
        layout.addWidget(QtWidgets.QLabel("Port"), 0, 0)
        layout.addWidget(self.serial_port_combo, 0, 1)
        layout.addWidget(self.serial_refresh_btn, 0, 2)
        layout.addWidget(QtWidgets.QLabel("Baud"), 1, 0)
        layout.addWidget(self.serial_baud_combo, 1, 1)
        layout.addWidget(self.serial_connect_btn, 1, 2)
        layout.addWidget(QtWidgets.QLabel("Send"), 2, 0)
        layout.addWidget(self.serial_input, 2, 1)
        layout.addWidget(self.serial_send_btn, 2, 2)
        
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
        
        # Input folder label (shows the acquisition save folder)
        self.recon_input_label = QtWidgets.QLabel("Input: (uses acquisition save folder)")
        self.recon_input_label.setStyleSheet("color: gray; font-style: italic;")
        
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
        self.recon_algorithm_label.setVisible(False)
        self.recon_algorithm_combo.setVisible(False)
        
        # Run button
        run_recon_btn = QtWidgets.QPushButton("Run reconstruction")
        run_recon_btn.clicked.connect(self._run_reconstruction)
        
        # Layout
        layout.addWidget(select_recon_root_btn, 0, 0)
        layout.addWidget(self.recon_root_label, 0, 1)
        layout.addWidget(self.recon_list, 1, 0, 1, 2)
        layout.addWidget(self.recon_args, 2, 0, 1, 2)
        layout.addWidget(self.recon_input_label, 3, 0, 1, 2)
        layout.addWidget(select_output_btn, 4, 0)
        layout.addWidget(self.recon_output_label, 4, 1)
        layout.addWidget(self.recon_algorithm_label, 5, 0)
        layout.addWidget(self.recon_algorithm_combo, 5, 1)
        layout.addWidget(run_recon_btn, 6, 0, 1, 2)
        layout.setRowMinimumHeight(1, 120)
        layout.setColumnStretch(1, 1)
        
        return panel
    
    def _create_recon_config_panel(self):
        """Create the reconstruction config editor panel."""
        group = QtWidgets.QGroupBox("Reconstruction parameters")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.recon_config_editor = QtWidgets.QTextEdit()
        self.recon_config_editor.setPlaceholderText("Reconstruction config (JSON)")
        self.recon_config_editor.setMinimumHeight(120)
        self._reset_recon_config_editor()
        
        self.reset_config_btn = QtWidgets.QPushButton("Use default config")
        self.reset_config_btn.clicked.connect(self._reset_recon_config_editor)
        
        layout.addWidget(self.recon_config_editor)
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
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select save folder")
        if path:
            self.save_dir = os.path.normpath(path)
            self.save_dir_label.setText(self.save_dir)
            # Update reconstruction input label
            self.recon_input_label.setText(f"Input: {self.save_dir}")
            self.recon_input_label.setStyleSheet("")  # Remove gray italic style
    
    def _select_dark_map(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select dark map", "",
            "TIFF files (*.tif *.tiff);;All files (*.*)"
        )
        if path:
            self.dark_map_path = os.path.normpath(path)
            self.dark_map_label.setText(self.dark_map_path)
    
    def _run_preview(self):
        if not self.save_dir:
            QtWidgets.QMessageBox.warning(self, "Missing data", "Select a save folder first")
            return
        if self.acq_worker and self.acq_worker.is_running():
            return
        
        self._start_acq_worker(preview_only=True)
    
    def _start_acquisition(self):
        if not self.save_dir:
            QtWidgets.QMessageBox.warning(self, "Missing data", "Select a save folder first")
            return
        if self.acq_worker and self.acq_worker.is_running():
            return
        
        self._start_acq_worker(preview_only=False)
    
    def _start_acq_worker(self, preview_only):
        """Create and start the acquisition worker."""
        self.acq_worker = AcquisitionWorker(
            self,
            acquisition_module_path=self._acquisition_module_path,
            defect_map_path=self._defect_map_path
        )
        self.acq_worker.preview_ready.connect(self._show_preview)
        self.acq_worker.finished.connect(self._on_acq_finished)
        self.acq_worker.progress.connect(self._on_acq_progress)
        self.acq_worker.started_work.connect(self._on_acq_started)
        self.acq_worker.start(self.save_dir, self.dark_map_path, preview_only)
    
    def _stop_acquisition(self):
        if self.acq_worker and self.acq_worker.is_running():
            self.acq_worker.request_stop()
            # Send STOP command via serial to stop the motor
            if self.serial_handler.is_connected():
                self.serial_handler.send("STOP")
                logging.info("Sent STOP command to motor")
    
    def _on_acq_started(self):
        self.setCursor(QtCore.Qt.BusyCursor)
        self.statusBar().showMessage("Acquisition in progress...")
    
    def _on_acq_progress(self, message):
        # Show truncated message in status bar (max 80 chars)
        status_msg = message[:80] + "..." if len(message) > 80 else message
        self.statusBar().showMessage(status_msg)
        # Log full message to log view
        logging.info(message)
        
        # Send OK via serial when acquisition loop starts (to start the motor)
        if "MAIN ACQUISITION STARTED" in message:
            if self.serial_handler.is_connected():
                self.serial_handler.send("OK")
                logging.info("Sent OK command to start motor")
    
    def _on_acq_finished(self, ok, message):
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.statusBar().clearMessage()
        if ok:
            QtWidgets.QMessageBox.information(self, "Acquisition", message)
        else:
            QtWidgets.QMessageBox.critical(self, "Acquisition", message)
    
    def _show_preview(self, preview_path):
        """Show preview image (if preview label exists)."""
        if not preview_path or not os.path.exists(preview_path):
            return
        self.last_preview_path = preview_path
        logging.info(f"Preview saved: {preview_path}")
    
    # ========================================================================
    # SERIAL HANDLERS
    # ========================================================================
    
    def _refresh_serial_ports(self):
        self.serial_port_combo.clear()
        ports = self.serial_handler.get_available_ports()
        if ports:
            self.serial_port_combo.addItems(ports)
        else:
            self.serial_port_combo.addItem("No ports found")
    
    def _toggle_serial_connection(self):
        if self.serial_handler.is_connected():
            self.serial_handler.disconnect()
        else:
            port_name = self.serial_port_combo.currentText()
            if not port_name or port_name == "No ports found":
                QtWidgets.QMessageBox.warning(self, "Serial", "No serial port selected")
                return
            baud_rate = int(self.serial_baud_combo.currentText())
            if not self.serial_handler.connect(port_name, baud_rate):
                QtWidgets.QMessageBox.warning(self, "Serial", f"Failed to open {port_name}")
    
    def _on_serial_connection_changed(self, connected):
        self.serial_connect_btn.setText("Disconnect" if connected else "Connect")
    
    def _send_serial_text(self):
        if not self.serial_handler.is_connected():
            QtWidgets.QMessageBox.warning(self, "Serial", "Serial port not connected")
            return
        text = self.serial_input.text().strip()
        if text:
            self.serial_handler.send(text)
            self.serial_input.clear()
    
    def _on_serial_message(self, message):
        logging.info(f"[SERIAL] {message}")
    
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
            "FDK_iteratives": root / "FDK_iteratives" / "MAIN_TIGRE_iterative.py",
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
    
    def _is_iterative_method(self, method_name):
        return method_name.lower().endswith("iteratives") or "iterative" in method_name.lower()
    
    def _is_fbp_method(self, method_name):
        return method_name.upper() == "FBP"
    
    def _on_recon_method_changed(self):
        selected_items = self.recon_list.selectedItems()
        if not selected_items:
            self.recon_algorithm_label.setVisible(False)
            self.recon_algorithm_combo.setVisible(False)
            self.recon_config_group.setVisible(True)
            return
        
        method_name = selected_items[0].text()
        is_iterative = self._is_iterative_method(method_name)
        self.recon_algorithm_label.setVisible(is_iterative)
        self.recon_algorithm_combo.setVisible(is_iterative)
        self.recon_config_group.setVisible(True)
        
        # Update config editor based on selected method
        self._reset_recon_config_editor()
    
    def _get_current_default_config(self):
        selected_items = self.recon_list.selectedItems()
        if selected_items:
            method_name = selected_items[0].text()
            if self._is_fbp_method(method_name):
                return FBP_RECON_CONFIG
        return DEFAULT_RECON_CONFIG
    
    def _reset_recon_config_editor(self):
        config = self._get_current_default_config()
        self.recon_config_editor.setPlainText(json.dumps(config, indent=2))
    
    def _get_recon_config(self):
        text = self.recon_config_editor.toPlainText().strip()
        if not text:
            return self._get_current_default_config()
        try:
            config = json.loads(text)
            if not isinstance(config, dict):
                raise ValueError("Config must be a JSON object")
            return config
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", f"Invalid config JSON: {exc}")
            return None
    
    def _run_reconstruction(self):
        if self.recon_worker and self.recon_worker.is_running():
            return
        
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
        
        args = self.recon_args.text().strip().split() if self.recon_args.text().strip() else []
        
        # Always use save_dir (acquisition folder) as input for reconstruction
        if self.save_dir:
            args.extend(["--input", self.save_dir])
        else:
            QtWidgets.QMessageBox.warning(self, "Reconstruction", "No acquisition folder selected. Please select a save folder first.")
            return
            
        if self.recon_output_dir:
            args.extend(["--output", self.recon_output_dir])
        
        recon_config = self._get_recon_config()
        if recon_config is None:
            return
        
        env_vars = {}
        if self.save_dir:
            env_vars["ACQ_INPUT_DIR"] = self.save_dir
        if self.recon_output_dir:
            env_vars["RECON_OUTPUT_DIR"] = self.recon_output_dir
        env_vars["RECON_CONFIG_JSON"] = json.dumps(recon_config)
        env_vars["RECON_ALGORITHM"] = self.recon_algorithm_combo.currentText()
        
        self.recon_worker = ReconstructionWorker(main_path, args, env_vars)
        self.recon_worker.finished.connect(self._on_recon_finished)
        self.recon_worker.progress.connect(self._on_recon_progress)
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
