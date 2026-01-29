"""
Logging Utilities for CT GUI
=============================

This module provides thread-safe logging that won't freeze the GUI.

WHY THIS IS NEEDED (Part of the freezing solution):
---------------------------------------------------
The original GUI would freeze partly because of logging overhead:
1. Every print() or logging.info() call would try to update the GUI
2. The GUI update happens on the main thread
3. Too many updates = main thread overwhelmed = GUI freezes

SOLUTION:
---------
1. Use a thread-safe queue to buffer log messages
2. The GUI polls the queue periodically (not on every message)
3. Limit how many messages are processed per cycle
4. Drop old messages if the queue gets too full

This decouples the logging from the GUI updates, preventing freezing.

CLASSES:
--------
- ThreadSafeLogQueue: Buffer for log messages with overflow protection
- MinimalStreamTee: Optional stdout/stderr capture (disabled by default)
- GUILogHandler: Sends logging.info() calls to the queue
"""
import sys
import logging
from queue import Queue, Empty

from PySide6 import QtCore


class ThreadSafeLogQueue:
    """
    Thread-safe queue for log messages to prevent GUI crashes.
    
    This queue acts as a buffer between log producers (acquisition process,
    serial handler, etc.) and the GUI consumer (log view widget).
    
    Key features:
    - Non-blocking put() - never blocks the producer
    - Overflow protection - drops old messages when full
    - Batch retrieval - get multiple messages at once for efficiency
    """
    
    def __init__(self, max_size=1000):
        """
        Args:
            max_size: Maximum messages to buffer. When exceeded, oldest are dropped.
        """
        self._queue = Queue(maxsize=max_size)
        self._dropped_count = 0  # Track how many messages were dropped
        self._enabled = True
    
    def set_enabled(self, enabled):
        """Enable or disable logging to queue."""
        self._enabled = enabled
    
    def put(self, msg):
        """
        Add a message to the queue (non-blocking).
        If queue is full, drops the oldest message to make room.
        """
        if not self._enabled:
            return
        try:
            self._queue.put_nowait(msg)
        except:
            # Queue full - drop oldest message and add new one
            # This ensures producers never block waiting for space
            self._dropped_count += 1
            try:
                self._queue.get_nowait()  # Remove oldest
                self._queue.put_nowait(msg)  # Add new
            except:
                pass
    
    def get_batch(self, max_items=10, max_backlog=500):
        """
        Get a batch of messages (non-blocking).
        
        If the backlog grows too large, drop oldest messages to keep 
        the GUI responsive. This prevents the GUI from getting behind
        when there's a flood of log messages.
        
        Args:
            max_items: Maximum messages to return per call
            max_backlog: If queue has more than this, drop excess
            
        Returns:
            List of log message strings
        """
        try:
            backlog = self._queue.qsize()
        except NotImplementedError:
            backlog = None
        
        # If backlog is too large, drop old messages
        # This keeps the GUI showing recent messages, not old ones
        if backlog and backlog > max_backlog:
            drop_count = backlog - max_backlog
            for _ in range(drop_count):
                try:
                    self._queue.get_nowait()
                    self._dropped_count += 1
                except Empty:
                    break

        # Get a batch of messages
        msgs = []
        for _ in range(max_items):
            try:
                msgs.append(self._queue.get_nowait())
            except Empty:
                break
        return msgs
    
    def get_dropped_count(self):
        """Return total number of dropped messages."""
        return self._dropped_count
    
    def clear(self):
        """Clear all pending messages."""
        while True:
            try:
                self._queue.get_nowait()
            except Empty:
                break


class MinimalStreamTee:
    """
    Optionally captures stdout/stderr and sends to log queue.
    
    WARNING: Enabling this (capture_all=True) can slow down the GUI
    significantly if there's heavy output. This is disabled by default.
    
    How it works:
    1. Replaces sys.stdout/sys.stderr
    2. All writes go to both the original stream AND the log queue
    3. Line-buffered to send complete lines to the queue
    """
    def __init__(self, original_stream, log_queue, capture_all=False):
        self._original_stream = original_stream
        self._log_queue = log_queue
        self._capture_all = capture_all  # If False, only sends to terminal
        self._buffer = ""  # Buffer for incomplete lines

    def write(self, text):
        if not text:
            return
        # ALWAYS write to original stream first (terminal)
        # This ensures terminal output is never lost
        try:
            self._original_stream.write(text)
            self._original_stream.flush()
        except Exception:
            pass
        
        # Only capture to GUI if explicitly enabled
        # Disabled by default because it can cause slowdown
        if not self._capture_all:
            return
        
        # Line-buffer: only send complete lines to avoid partial messages
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._log_queue.put(line)

    def flush(self):
        try:
            self._original_stream.flush()
        except Exception:
            pass
        # Flush any remaining buffer content
        if self._capture_all and self._buffer:
            self._log_queue.put(self._buffer)
            self._buffer = ""

    def isatty(self):
        return False


class GUILogHandler(logging.Handler):
    """
    Custom logging handler that sends messages to the GUI queue.
    
    This only captures logging.info(), logging.warning(), etc. calls -
    NOT all print() statements. This is much more efficient than
    capturing all stdout/stderr.
    
    Usage:
        The setup_logging() function installs this automatically.
        In code, use logging.info("message") to send to GUI.
    """
    def __init__(self, log_queue):
        super().__init__()
        self._log_queue = log_queue
        self._enabled = True

    def set_enabled(self, enabled):
        self._enabled = enabled

    def emit(self, record):
        """Called by logging module for each log message."""
        if not self._enabled:
            return
        try:
            msg = self.format(record)
            self._log_queue.put(msg)
        except Exception:
            pass  # Never let logging errors crash the app


def setup_logging(log_queue, mirror_to_gui=False):
    """
    Setup the logging system for the GUI application.
    
    Args:
        log_queue: ThreadSafeLogQueue instance for buffering messages
        mirror_to_gui: If True, capture ALL stdout/stderr (slow!)
                       If False, only capture logging.* calls (recommended)
    
    This configures:
    1. Terminal handler - all logs go to terminal (always)
    2. GUI handler - logging.* calls go to GUI via queue
    3. Optional stream tee - stdout/stderr capture (if mirror_to_gui=True)
    """
    # Store original streams
    stdout_original = sys.stdout
    stderr_original = sys.stderr
    
    # Only tee streams if explicitly requested
    # WARNING: This can slow down the GUI significantly!
    if mirror_to_gui:
        sys.stdout = MinimalStreamTee(stdout_original, log_queue, capture_all=True)
        sys.stderr = MinimalStreamTee(stderr_original, log_queue, capture_all=True)
    
    # Setup logging to terminal (always enabled)
    terminal_handler = logging.StreamHandler(stdout_original)
    terminal_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    )
    
    # Setup logging to GUI (only logging module, not all prints)
    gui_handler = GUILogHandler(log_queue)
    gui_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []
    root_logger.addHandler(terminal_handler)
    root_logger.addHandler(gui_handler)
    
    return stdout_original, stderr_original
