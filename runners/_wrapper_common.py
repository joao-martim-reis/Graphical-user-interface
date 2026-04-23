"""
Shared helpers for the reconstruction wrapper scripts.

The GUI launches reconstruction by running one of the run_*.py scripts in this
folder via runpy. Each wrapper reads environment variables set by the GUI,
imports the original reconstruction script as a module (which SKIPS its
`if __name__ == "__main__":` block, keeping the standalone script untouched),
and calls its main() function with a GUI-built config.
"""
import json
import os
import sys


def load_env_overrides():
    """Return (config_overrides, input_dir, output_dir) from GUI env vars."""
    overrides = {}
    raw = os.environ.get("RECON_CONFIG_JSON")
    if raw:
        try:
            overrides = json.loads(raw)
        except Exception as e:
            print(f"[WRAPPER] Ignoring invalid RECON_CONFIG_JSON: {e}")
            overrides = {}

    input_dir = (
        os.environ.get("RECON_INPUT_DIR")
        or os.environ.get("INPUT_FOLDER")
        or os.environ.get("INPUT_DIR")
        or os.environ.get("ACQ_INPUT_DIR")
        or os.environ.get("SAVE_DIR")
    )
    output_dir = os.environ.get("RECON_OUTPUT_DIR") or None
    return overrides, input_dir, output_dir


def prepend_to_syspath(path):
    """Ensure a folder is the first entry on sys.path so its modules import cleanly."""
    if path and path not in sys.path:
        sys.path.insert(0, path)


def merged_config(defaults, overrides):
    """Return a new dict with defaults overlaid by overrides (shallow merge)."""
    merged = dict(defaults)
    for key, value in (overrides or {}).items():
        merged[key] = value
    return merged


def print_banner(title, cfg):
    print("=" * 70)
    print(f"[WRAPPER] {title}".replace("—", "-"))
    print("-" * 70)
    for key in sorted(cfg.keys()):
        val = cfg[key]
        if isinstance(val, str) and len(val) > 60:
            val = val[:57] + "..."
        print(f"    {key}: {val}")
    print("=" * 70)
