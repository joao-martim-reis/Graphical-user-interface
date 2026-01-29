"""
Configuration Constants for CT Acquisition and Reconstruction GUI
==================================================================

This file centralizes all configuration settings in one place.
Modify values here to change application behavior without editing code.

IMPORTANT FOR GUI PERFORMANCE:
------------------------------
The LOG_* settings below directly affect GUI responsiveness.
If the GUI becomes slow, try:
- Set LOG_MIRROR_ENABLED = False (don't capture all stdout/stderr)
- Reduce LOG_MAX_ITEMS_PER_FLUSH (fewer log updates per cycle)
- Increase LOG_FLUSH_INTERVAL_MS (less frequent updates)
"""
import math

# ============================================================================
# PATH CONFIGURATION
# ============================================================================
# Path to the camera acquisition module containing camera_config.py, 
# acquisition.py, and image_processing.py
ACQUISITION_MODULE_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\S2I_External_Trigger_detector_image_acquisition\Hot_duration_trig_mode"

# Default defect map for image correction
DEFAULT_DEFECT_MAP_PATH = r"C:\Users\joaomartimreis\Desktop\Joao_CT\DefectMap.tif"

# Root folder containing reconstruction algorithm scripts
DEFAULT_RECON_ROOT = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms"

# ============================================================================
# RECONSTRUCTION CONFIGURATIONS
# ============================================================================

# Default config for FDK (Feldkamp-Davis-Kress) and iterative methods
# These parameters are passed to the reconstruction scripts via environment variables
DEFAULT_RECON_CONFIG = {
    "voxel_size": 26,           # Size of voxels in the reconstructed volume
    "DSD": 457,                 # Distance Source to Detector (mm)
    "DSO": 211,                 # Distance Source to Object/rotation axis (mm)
    "downsample": 1,            # Downsampling factor (1 = no downsampling)
    "total_angle": 2 * math.pi, # Total rotation angle (2π = 360°)
    "calibrated_shift_px": 15.6,# Detector horizontal shift calibration (pixels)
    "shift_sign": 1,            # Direction of shift correction (+1 or -1)
    "filter_type": "ram_lak",   # Filter for FDK reconstruction
    "rotation_angle": 0.0,      # Additional rotation correction
    "output_folder_NiFT": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\reconstructed_volumes_Nift",
    "filtered_volumes_folder": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\Filtered_volumes.Nift"
}

# FBP (Filtered Back Projection) specific configuration
# FBP uses different parameters than FDK/iterative methods
FBP_RECON_CONFIG = {
    "pixel_size": 0.05,         # Physical pixel size (mm)
    "calibrated_shift_px": 5.12,# Detector shift for FBP (different from FDK)
    "shift_sign": -1,           # Shift direction (opposite to FDK)
    "default_filter": "hann",   # Default filter type
    "filters": ["ram_lak", "shepp_logan", "hann"]  # Available filters
    # Alternative filters: ["ram_lak", "shepp_logan", "hann", "hamming", "cosine", "blackman"]
}

# ============================================================================
# GUI PERFORMANCE SETTINGS (CRITICAL FOR PREVENTING FREEZING)
# ============================================================================
# These settings control how log messages are handled.
# The original freezing problem was partly caused by too many log updates.

# If True, ALL stdout/stderr is captured and shown in GUI log
# WARNING: This can slow down the GUI significantly with heavy output!
# Set to False to only show logging.info() messages (recommended)
LOG_MIRROR_ENABLED = False

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

# ============================================================================
# ITERATIVE RECONSTRUCTION ALGORITHMS
# ============================================================================
# List of available iterative algorithms for TIGRE reconstruction
ITERATIVE_ALGORITHMS = [
    "Select algorithm...",  # Placeholder - user must select
    "SIRT",                 # Simultaneous Iterative Reconstruction Technique
    "CGLS",                 # Conjugate Gradient Least Squares
    "LSQR",                 # Least Squares QR
    "LSMR",                 # Least Squares Minimal Residual
    "OSSART",               # Ordered Subset SART
    "SART",                 # Simultaneous Algebraic Reconstruction Technique
    "OSSART_TV",            # OSSART with Total Variation regularization
    "SART_TV",              # SART with Total Variation regularization
    "ASD_POCS",             # Adaptive Steepest Descent POCS
    "AWASD_POCS"            # Adaptive Weighted ASD-POCS
]
