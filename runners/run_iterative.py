"""
Iterative reconstruction wrapper.

Imports MAIN_TIGRE_iterative as a module (skipping its __main__ block) and
calls main() with a GUI-built config. Per-algorithm overrides (iterations and
params like blocksize / alpha) are applied by mutating iterative_parameters.
ALGORITHM_CONFIGS in memory BEFORE calling main() — the mutation is confined
to this subprocess and does not touch the .py file on disk.
"""
import json
import math
import os
import sys

from _wrapper_common import (
    load_env_overrides,
    merged_config,
    prepend_to_syspath,
    print_banner,
)


_ITER_DEFAULTS = {
    "voxel_size": 26,
    "calibrated_shift_px": 0,
    "total_angle": 2 * math.pi,
    "shift_sign": 1,
    "DSD": 457,
    "DSO": 211,
    "downsample": 1,
    "algorithm": "SIRT",
    "output_folder_NiFT": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\reconstructed_volumes_Nift",
    "filtered_volumes_folder": r"C:\Users\joaomartimreis\Desktop\Joao_CT\Volumes_reconstruction\Filtered_volumes.Nift",
}


def _resolve_algorithm_dir():
    root = os.environ.get("RECON_ALGORITHM_ROOT") or os.environ.get("RECON_ROOT")
    if root and os.path.isdir(root):
        candidate = os.path.join(root, "Iteratives")
        if os.path.isdir(candidate):
            return candidate
    default = r"C:\Users\joaomartimreis\Desktop\Joao_CT\Reconstruction_Algorithms\MAIN_reconstruction_algorithms\Iteratives"
    return default


def _apply_algorithm_overrides(module_iter_params, algorithm, iterations, extra_params):
    """Mutate ALGORITHM_CONFIGS for the selected algorithm (subprocess-scoped)."""
    cfgs = module_iter_params.ALGORITHM_CONFIGS
    if algorithm not in cfgs:
        raise SystemExit(
            f"[WRAPPER] Unknown iterative algorithm '{algorithm}'. "
            f"Known: {list(cfgs.keys())}"
        )
    entry = cfgs[algorithm]
    if iterations is not None:
        entry["iterations"] = int(iterations)
        print(f"[WRAPPER] Override iterations: {algorithm} -> {iterations}")
    if extra_params:
        entry.setdefault("params", {}).update(extra_params)
        print(f"[WRAPPER] Override params for {algorithm}: {extra_params}")


def main():
    overrides, input_dir, output_dir = load_env_overrides()
    cfg = merged_config(_ITER_DEFAULTS, overrides)

    # Algorithm + iterations come through their own env vars (historical GUI wiring)
    algo_env = os.environ.get("RECON_ALGORITHM")
    if algo_env and algo_env != "Select algorithm...":
        cfg["algorithm"] = algo_env

    iterations_env = os.environ.get("RECON_ITERATIONS")
    iterations_override = int(iterations_env) if iterations_env else None

    extra_params = {}
    raw_params = os.environ.get("RECON_ALGO_PARAMS_JSON")
    if raw_params:
        try:
            extra_params = json.loads(raw_params)
        except Exception as e:
            print(f"[WRAPPER] Ignoring invalid RECON_ALGO_PARAMS_JSON: {e}")

    if not input_dir:
        raise SystemExit("[WRAPPER] No input folder provided (RECON_INPUT_DIR not set).")
    if not os.path.isdir(input_dir):
        raise SystemExit(f"[WRAPPER] Input folder does not exist: {input_dir}")

    out = output_dir or cfg.get("output_folder_NiFT")

    print_banner("Iteratives - config received from GUI", cfg)
    print(f"[WRAPPER] Input folder : {input_dir}")
    print(f"[WRAPPER] Output folder: {out}")

    algo_dir = _resolve_algorithm_dir()
    prepend_to_syspath(algo_dir)

    import iterative_parameters  # type: ignore
    _apply_algorithm_overrides(
        iterative_parameters,
        cfg["algorithm"],
        iterations_override,
        extra_params,
    )

    import MAIN_TIGRE_iterative as iter_module  # type: ignore
    iter_module.main(input_dir, cfg, output_folder=out)


if __name__ == "__main__":
    main()
