"""
Logging Utilities for CT GUI
=============================

This module provides thread-safe logging that won't freeze the GUI.

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
    This queue acts as a buffer between log producers (acquisition process, serial handler, etc.) and the GUI consumer (log view widget).
    """
    
    def __init__(self, max_size=1000):
        """
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


def setup_logging(log_queue):
    """
    Setup the logging system for the GUI application.
    
    Args:
        log_queue: ThreadSafeLogQueue instance for buffering messages
    
    This configures:
    1. Terminal handler - all logs go to terminal (always)
    2. GUI handler - logging.* calls go to GUI via queue
    """
    # Setup logging to terminal (always enabled)
    terminal_handler = logging.StreamHandler(sys.stdout)
    terminal_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    )
    
    # Setup logging to GUI (only logging module, not all prints)
    gui_handler = GUILogHandler(log_queue)
    gui_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S')
    )
    
    # Configure the root logger with both handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers = []
    root_logger.addHandler(terminal_handler)
    root_logger.addHandler(gui_handler)
