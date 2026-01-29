"""
Serial Communication Handler for STM32 Microcontroller
========================================================

This module handles bidirectional serial communication with the STM32
microcontroller that controls the CT rotation motor.

Communication Protocol:
----------------------
- Baud rate: 115200 (default)
- Line ending: LF (\\n)
- GUI → STM32: Commands like "OK", "STOP"
- STM32 → GUI: Status messages like "[  7/401] Step done - Motor rotated +0.9 deg"

Automatic Commands:
------------------
The main_window.py sends these commands automatically:
- "OK"   → Sent when acquisition starts (to tell motor to start rotating)
- "STOP" → Sent when user clicks Stop (to tell motor to stop)

Why Qt Serial Port:
------------------
We use Qt's QSerialPort instead of pyserial because:
1. It integrates with Qt's event loop (non-blocking)
2. Uses signals/slots for data reception (no polling needed)
3. Works well with the rest of the Qt-based GUI

This NEVER freezes the GUI because all I/O is handled via Qt events.
"""
import logging
from PySide6 import QtCore, QtSerialPort


class SerialHandler(QtCore.QObject):
    """
    Handles serial communication with STM32 microcontroller.
    
    This class provides a clean interface for:
    - Discovering available serial ports
    - Connecting/disconnecting
    - Sending commands
    - Receiving status messages
    
    All communication is non-blocking thanks to Qt's event-driven architecture.
    
    Signals:
        message_received(str): Emitted for each complete line received
        connection_changed(bool): Emitted when connection state changes
    """
    
    # Qt signals for communication with the GUI
    message_received = QtCore.Signal(str)   # Emits received messages
    connection_changed = QtCore.Signal(bool) # Emits True/False for connect/disconnect
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create the Qt serial port object
        self._port = QtSerialPort.QSerialPort(self)
        
        # Buffer for incomplete messages (line-based protocol)
        self._rx_buffer = ""
        
        # Connect Qt signal for incoming data
        # When data arrives, _on_ready_read() is called automatically
        self._port.readyRead.connect(self._on_ready_read)
    
    def get_available_ports(self):
        """
        Return list of available serial port names.
        
        On Windows, these are like "COM1", "COM3", etc.
        On Linux, they're like "/dev/ttyUSB0", "/dev/ttyACM0", etc.
        """
        ports = QtSerialPort.QSerialPortInfo.availablePorts()
        return [port.portName() for port in ports]
    
    def is_connected(self):
        """Check if serial port is currently open."""
        return self._port.isOpen()
    
    def connect(self, port_name, baud_rate=115200):
        """
        Connect to a serial port.
        
        Args:
            port_name: The port to connect to (e.g., "COM3")
            baud_rate: Communication speed (default 115200)
            
        Returns:
            True if connection successful, False otherwise
        """
        # Disconnect first if already connected
        if self._port.isOpen():
            self.disconnect()
        
        # Configure port settings
        self._port.setPortName(port_name)
        self._port.setBaudRate(baud_rate)
        
        # Standard serial settings: 8N1 (8 data bits, no parity, 1 stop bit)
        self._port.setDataBits(QtSerialPort.QSerialPort.DataBits.Data8)
        self._port.setParity(QtSerialPort.QSerialPort.Parity.NoParity)
        self._port.setStopBits(QtSerialPort.QSerialPort.StopBits.OneStop)
        self._port.setFlowControl(QtSerialPort.QSerialPort.FlowControl.NoFlowControl)
        
        # Attempt to open the port
        if self._port.open(QtCore.QIODevice.OpenModeFlag.ReadWrite):
            logging.info(f"Serial connected: {port_name} @ {baud_rate}")
            self.connection_changed.emit(True)
            return True
        else:
            logging.error(f"Failed to open serial port: {port_name}")
            return False
    
    def disconnect(self):
        """Disconnect from serial port."""
        if self._port.isOpen():
            self._port.close()
            logging.info("Serial disconnected")
            self.connection_changed.emit(False)
    
    def send(self, text):
        """
        Send text with LF line ending.
        
        The STM32 expects each command to end with a newline character.
        This method adds the newline automatically.
        
        Args:
            text: The command to send (without newline)
            
        Returns:
            True if sent successfully, False if port not open
        """
        if not self._port.isOpen():
            return False
        
        # Add newline and send
        payload = f"{text}\n"
        self._port.write(payload.encode("utf-8"))
        self._port.flush()  # Ensure data is sent immediately
        logging.info(f"Serial sent: {text}")
        return True
    
    def _on_ready_read(self):
        """
        Handle incoming serial data (called by Qt when data arrives).
        
        This implements line-based buffering:
        - Incoming bytes are accumulated in a buffer
        - When a complete line (ending with \\n) is received, it's emitted
        - Partial lines are kept in the buffer until complete
        
        This ensures we always emit complete messages, not fragments.
        """
        if not self._port.isOpen():
            return
        
        # Read all available data
        data = self._port.readAll()
        if data.isEmpty():
            return
        
        # Decode bytes to string
        try:
            text = bytes(data).decode("utf-8", errors="replace")
        except Exception:
            text = str(bytes(data))
        
        # Add to buffer
        self._rx_buffer += text
        
        # If no complete line yet, wait for more data
        if "\n" not in self._rx_buffer:
            # Prevent buffer from growing too large
            if len(self._rx_buffer) > 4096:
                self._rx_buffer = self._rx_buffer[-4096:]
            return
        
        lines = self._rx_buffer.splitlines()
        if not self._rx_buffer.endswith("\n"):
            self._rx_buffer = lines.pop() if lines else ""
        else:
            self._rx_buffer = ""
        
        for line in lines:
            if line:
                self.message_received.emit(line)
