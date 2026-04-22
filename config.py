"""
Configuration Constants for CT Acquisition and Reconstruction GUI
==================================================================

This file centralizes all configuration settings in one place.
Modify values here to change application behavior without editing code.


The LOG_* settings below directly affect GUI responsiveness.
"""
import math

# 
# Path to the camera acquisition module containing camera_config.py, 
# acquisition.py, and image_processing.py
ACQUISITION_MODULE_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\S2I_External_Trigger_detector_image_acquisition\Hot_duration_trig_mode"

# Default defect map for image correction
DEFAULT_DEFECT_MAP_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\DefectMap.tif"

# Default dark map for image correction (always the same one)
DEFAULT_DARK_MAP_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Dark_map\DARK_MAP_5_12.tif"

# Default gain/flat field map path (set to "" to disable gain correction)
DEFAULT_GAIN_MAP_PATH = r""

# Root folder containing reconstruction algorithm scripts
DEFAULT_RECON_ROOT = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms"

# Path to calibration script (runs before reconstruction to calculate shift)
CALIBRATION_SCRIPT_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms\Calibration\calibration_main.py"


# ============================================================================
# MOTOR CONFIGURATION SETTINGS (for CONFIG command to STM32)
# ============================================================================
# These are the default values shown in the motor configuration dialog
# User can change them before sending CONFIG command to the firmware

MOTOR_CONFIG_DEFAULTS = {
    "projections": 800,      # Number of projections for full rotation
    "high_time_ms": 400,     # Trigger HIGH duration in milliseconds
    "low_time_ms": 100       # Trigger LOW duration in milliseconds
}

# Valid ranges for motor configuration parameters
# These enforce the firmware's acceptable ranges
MOTOR_CONFIG_RANGES = {
    "projections": (10, 3600),      # Min: 10, Max: 3600
    "high_time_ms": (10, 5000),     # Min: 10 ms, Max: 5000 ms
    "low_time_ms": (10, 5000)       # Min: 10 ms, Max: 5000 ms
}


# Default config for FDK (Feldkamp-Davis-Kress) and iterative methods
# These parameters are passed to the reconstruction scripts via environment variables
DEFAULT_RECON_CONFIG = {
    "voxel_size": 26,
    "DSD": 457,
    "DSO": 211,
    "downsample": 1,
    "total_angle": 2 * math.pi,
    "calibrated_shift_px": 15.6,
    "shift_sign": 1,
    "filter_type": "ram_lak",
    "rotation_angle": 0.0,
    "output_folder_NiFT": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\reconstructed_volumes_Nift",
    "filtered_volumes_folder": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\Filtered_volumes.Nift"
}

# FBP (Filtered Back Projection) specific configuration
# FBP uses different parameters than FDK/iterative methods
FBP_RECON_CONFIG = {
    "pixel_size": 0.05,
    "calibrated_shift_px": 5.12,
    "shift_sign": -1,
    "default_filter": "hann",
    "filters": ["ram_lak", "shepp_logan", "hann"]
}


# GUI PERFORMANCE SETTINGS (CRITICAL FOR PREVENTING FREEZING)

# These settings control how log messages are handled.
# Maximum number of log messages to buffer before dropping old ones
# Prevents memory issues with very long running acquisitions
LOG_MAX_QUEUE_SIZE = 1000

# How often (milliseconds) to update the log view
# Higher values = less CPU usage but less responsive log
# Lower values = more responsive but more CPU usage
LOG_FLUSH_INTERVAL_MS = 250

# Maximum log messages to add to GUI per flush cycle
# Limits GUI updates to prevent freezing during high log volume
LOG_MAX_ITEMS_PER_FLUSH = 10

# Maximum lines to keep in the log view widget
# Older lines are automatically removed to prevent memory issues
LOG_VIEW_MAX_BLOCKS = 2000


# List of available iterative algorithms for TIGRE reconstruction
ITERATIVE_ALGORITHMS = [
    "Select algorithm...",
    "SIRT",
    "CGLS",
    "LSQR",
    "LSMR",
    "OSSART",
    "SART",
    "OSSART_TV",
    "SART_TV",
    "ASD_POCS",
    "AWASD_POCS"
]

# Default iterations for each iterative algorithm
# Keep it simple - just control the number of iterations
# More complex parameters can be added to DEFAULT_RECON_CONFIG if needed
ITERATIVE_ALGORITHM_ITERATIONS = {
    "SIRT": 50,
    "CGLS": 20,
    "LSQR": 20,
    "LSMR": 20,
    "OSSART": 40,
    "SART": 30,
    "OSSART_TV": 50,
    "SART_TV": 50,
    "ASD_POCS": 50,
    "AWASD_POCS": 50
}
