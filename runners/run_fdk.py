"""
FDK (reduce memory) reconstruction wrapper.

Run by the GUI via runpy. Imports MAIN_TIGRE_FDK_Voxel_size as a module so its
`if __name__ == "__main__":` block is skipped, then calls its main() with a
config built from GUI env vars.

Safe: does not modify the original script. Running the script directly from the
command line keeps using its hardcoded CONFIG block.
"""
import math
import os
import sys

from _wrapper_common import (
    load_env_overrides,
    merged_config,
    prepend_to_syspath,
    print_banner,
)


# Mirror the hardcoded defaults from MAIN_TIGRE_FDK_Voxel_size.py's __main__
_FDK_DEFAULTS = {
    "voxel_size": 26,
    "calibrated_shift_px": 0,
    "shift_sign": 1,
    "total_angle": 2 * math.pi,
    "DSD": 457,
    "DSO": 211,
    "downsample": 1,
    "filter_type": "ram_lak",
    "detector_tilt": 0,
    "output_folder_NiFT": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\reconstructed_volumes_Nift",
    "filtered_volumes_folder": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\Filtered_volumes.Nift",
}


def _resolve_algorithm_dir():
    """Locate the FDK algorithm folder relative to RECON_ROOT or fall back to defaults."""
    root = os.environ.get("RECON_ALGORITHM_ROOT") or os.environ.get("RECON_ROOT")
    if root and os.path.isdir(root):
        candidate = os.path.join(root, "FDK_reduce_memory")
        if os.path.isdir(candidate):
            return candidate
    # Fallback: known install path
    default = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms\FDK_reduce_memory"
    return default


def main():
    overrides, input_dir, output_dir = load_env_overrides()
    cfg = merged_config(_FDK_DEFAULTS, overrides)

    if not input_dir:
        raise SystemExit("[WRAPPER] No input folder provided (RECON_INPUT_DIR not set).")
    if not os.path.isdir(input_dir):
        raise SystemExit(f"[WRAPPER] Input folder does not exist: {input_dir}")

    out = output_dir or cfg.get("output_folder_NiFT")

    print_banner("FDK_reduce_memory - config received from GUI", cfg)
    print(f"[WRAPPER] Input folder : {input_dir}")
    print(f"[WRAPPER] Output folder: {out}")

    algo_dir = _resolve_algorithm_dir()
    prepend_to_syspath(algo_dir)

    # Import the original script. Because we use import (not runpy), the
    # script's `if __name__ == "__main__":` block (with its hardcoded CONFIG)
    # is skipped — only the top-level main() function is defined.
    import MAIN_TIGRE_FDK_Voxel_size as fdk_module  # type: ignore

    fdk_module.main(input_dir, cfg, output_folder=out)


if __name__ == "__main__":
    main()
