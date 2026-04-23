"""
FBP (2D single-line parallel-beam) reconstruction wrapper.

TIGRE_fbp1.run_reconstruction expects (tiff_folder, line_shift, lines_filters,
configurations). We split the GUI-supplied config into the CONFIG dict the
function reads AND the two integer arguments it needs (line_shift and the
list of sinogram rows to reconstruct).
"""
import os
import sys

from _wrapper_common import (
    load_env_overrides,
    merged_config,
    prepend_to_syspath,
    print_banner,
)


_FBP_DEFAULTS = {
    "pixel_size": 0.05,
    "calibrated_shift_px": 5.12,
    "shift_sign": -1,
    "default_filter": "hann",
    "filters": ["ram_lak", "shepp_logan", "hann"],
    # GUI-exposed arguments that FBP's run_reconstruction takes separately:
    "line_shift": 100,
    "lines_filters": [50, 400, 800],
}


def _resolve_algorithm_dir():
    root = os.environ.get("RECON_ALGORITHM_ROOT") or os.environ.get("RECON_ROOT")
    if root and os.path.isdir(root):
        candidate = os.path.join(root, "FBP")
        if os.path.isdir(candidate):
            return candidate
    default = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms\FBP"
    return default


def _coerce_int_list(value):
    if isinstance(value, list):
        return [int(v) for v in value]
    if isinstance(value, str):
        return [int(v.strip()) for v in value.split(",") if v.strip()]
    return [int(value)]


def main():
    overrides, input_dir, _output_dir = load_env_overrides()
    cfg = merged_config(_FBP_DEFAULTS, overrides)

    if not input_dir:
        raise SystemExit("[WRAPPER] No input folder provided (RECON_INPUT_DIR not set).")
    if not os.path.isdir(input_dir):
        raise SystemExit(f"[WRAPPER] Input folder does not exist: {input_dir}")

    line_shift = int(cfg.pop("line_shift", 100))
    lines_filters = _coerce_int_list(cfg.pop("lines_filters", [50, 400, 800]))

    # Only the keys TIGRE_fbp1 actually reads should live in the config passed through
    fbp_cfg_keys = ("pixel_size", "calibrated_shift_px", "shift_sign", "default_filter", "filters")
    fbp_cfg = {k: cfg[k] for k in fbp_cfg_keys if k in cfg}

    print_banner("FBP - config received from GUI", {**fbp_cfg, "line_shift": line_shift, "lines_filters": lines_filters})
    print(f"[WRAPPER] Input folder : {input_dir}")

    algo_dir = _resolve_algorithm_dir()
    prepend_to_syspath(algo_dir)

    import TIGRE_fbp1 as fbp_module  # type: ignore
    fbp_module.run_reconstruction(input_dir, line_shift, lines_filters, fbp_cfg)


if __name__ == "__main__":
    main()
