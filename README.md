# CT Acquisition and Reconstruction GUI

A desktop app for driving a cone-beam micro-CT pipeline end-to-end: image
acquisition from the camera, motor control over a serial link to the STM32,
and volume reconstruction using FDK, FBP, or iterative algorithms through
TIGRE. Built with PySide6.

> If you have the same scanner (camera + STM32 + GPU with TIGRE), the goal is
> simple: install the pieces listed below, run `python main.py`, click Start.

---

## What you get

- Acquire projections directly from the detector, with automatic dark-map
  and (optional) gain-map correction.
- Drive the STM32 motor controller from the same window - connect, configure
  projections / high / low trigger times, send `OK` / `STOP`.
- Run reconstructions without editing Python: FDK (reduce-memory), any of 11
  iterative algorithms (SIRT, CGLS, LSQR, LSMR, OSSART, SART, MLEM, OSSART_TV,
  SART_TV, ASD_POCS, AWASD_POCS), or single-line FBP with filter comparison.
- Live parameter editor on the right side - voxel size, DSD / DSO, filter,
  shift, rotation. Values actually apply at runtime via lightweight wrappers
  in `runners/`.
- `Advanced...` dialog for iterative algorithms that reads
  `iterative_parameters.py` at runtime and lets you tweak per-algorithm
  parameters (`blocksize`, `alpha`, iterations).
- Optional calibration step that computes the detector shift before
  reconstruction and auto-fills the parameter.
- Save / load named **parameter presets** (per phantom, per experiment).
- Automatic **reconstruction history** (`runs.jsonl`) with a table viewer
  under `View → Reconstruction history`.
- Thread-safe logging panel that never freezes, even during long acquisitions.

---

## Prerequisites

### Hardware

- Your detector + camera, connected and powered.
- STM32 motor controller flashed with the matching firmware, reachable on a
  serial port (default 115200 baud).
- An NVIDIA GPU with up-to-date CUDA drivers (TIGRE runs on CUDA).

### Software

| Component | What to install | Notes |
|---|---|---|
| Python | 3.8 or newer (64-bit, Windows) | Tested on 3.10 / 3.11 |
| Python packages | `pip install -r requirements.txt` | Covers the GUI + reconstruction Python deps |
| **TIGRE** | Follow the official instructions at https://github.com/CERN/TIGRE | Needs a matching CUDA toolkit; not a normal pip install |
| **Reconstruction algorithms** | Clone the companion repo (see below) | Contains the FDK / iterative / FBP scripts the GUI launches |
| **Camera SDK** | Install from the detector vendor (Spectral Instruments / SLDevice) | Ships a Python wrapper the acquisition module imports |

### Companion repositories / folders

The GUI assumes two sibling components exist on disk, referenced by absolute
paths:

```
Reconstruction_Algorithms/
└── MAIN_reconstruction_algorithms/
    ├── FDK_reduce_memory/
    ├── Iteratives/
    ├── FBP/
    └── Calibration/

<acquisition-sdk-root>/
└── <trigger-mode-folder>/       # e.g. Hot_duration_trig_mode
    ├── camera_config.py
    ├── acquisition.py
    └── image_processing.py
```

The reconstruction algorithms live in a separate repo you will clone
(URL goes here once you push them). The acquisition SDK comes from your
camera vendor and is not redistributable; install it from their package.

---

## Install

```bash
# 1. Clone this GUI repo
git clone https://github.com/joao-martim-reis/GUI.git
cd GUI

# 2. (Optional but recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install TIGRE
#    Follow https://github.com/CERN/TIGRE - this compiles against your CUDA.
#    Confirm with: python -c "import tigre; print(tigre.__version__)"

# 5. Clone the reconstruction algorithms repo next to the GUI
git clone <URL_OF_RECONSTRUCTION_ALGORITHMS_REPO>

# 6. Install the camera SDK from your vendor
#    (produces the folder with camera_config.py, acquisition.py, etc.)
```

---

## Configure paths (once)

Open `main.py` and edit the three paths at the top:

```python
ACQUISITION_MODULE_PATH  = r"C:\path\to\your\camera_sdk\Hot_duration_trig_mode"
RECONSTRUCTION_ROOT_PATH = r"C:\path\to\Reconstruction_Algorithms\MAIN_reconstruction_algorithms"
DEFECT_MAP_PATH          = r"C:\path\to\DefectMap.tif"
```

And in `config.py`:

```python
DEFAULT_DARK_MAP_PATH = r"C:\path\to\Dark_map\DARK_MAP_xxx.tif"
DEFAULT_GAIN_MAP_PATH = r""   # leave empty to disable gain correction
CALIBRATION_SCRIPT_PATH = r"C:\path\to\Reconstruction_Algorithms\MAIN_reconstruction_algorithms\Calibration\calibration_main.py"
```

These are the only paths you need to touch. Everything else (output folders,
filtered-volumes folders) can be chosen from the GUI at runtime.

---

## Run

```bash
python main.py
```

You can also create a desktop shortcut pointing at
`pythonw.exe main.py` (no terminal window) or package with PyInstaller later
for a single `.exe`.

---

## Typical workflow

1. **Connect the STM32** - pick the port, click `Connect`. The status label
   turns green.
2. **Configure the motor** - click `Configure Motor`, set number of
   projections + HIGH / LOW trigger times, click OK. The firmware receives
   the new values.
3. **Pick a save folder** under *Acquisition* - where TIFFs will be written.
4. **Start acquisition**. Projections stream into the save folder. Click
   `Send OK` to start motor rotation; click `Stop` + `Send STOP` to end early.
5. **Select a reconstruction method** (`FDK_reduce_memory`, `Iteratives`,
   or `FBP`). The parameter panel on the right repopulates with the
   method's defaults.
6. *(Optional for iterative)* - pick an algorithm from the `Iterative
   algorithm` dropdown, set the iterations, or click `Advanced...` to tweak
   `blocksize` / `alpha`.
7. *(Optional)* tick `Run calibration first` - the detector shift is
   computed and `calibrated_shift_px` is auto-filled.
8. **Run reconstruction**. The blue button kicks off the wrapper in
   `runners/`, which applies your right-panel values to the underlying
   algorithm script. Logs stream into the log panel.
9. **Save a preset** (`Save as...`) to reuse this exact configuration
   later, and check `View → Reconstruction history` to see every run's
   timestamp, algorithm, duration, and status.

---

## How parameters actually reach the reconstruction scripts

The GUI does **not** edit the algorithm scripts. It runs one of three tiny
launchers in `runners/` (`run_fdk.py`, `run_iterative.py`, `run_fbp.py`).
Each launcher reads environment variables set by the GUI
(`RECON_CONFIG_JSON`, `RECON_ALGORITHM`, `RECON_ITERATIONS`,
`RECON_ALGO_PARAMS_JSON`, `RECON_INPUT_DIR`, `RECON_OUTPUT_DIR`), imports the
corresponding algorithm module (which skips its hardcoded `__main__` block),
and calls its `main()` directly with a freshly built CONFIG dict. Running the
original scripts directly from the command line still works with their
hardcoded defaults - nothing in `Reconstruction_Algorithms/` was modified.

---

## Files in this repo

```
GUI/
├── main.py                      # Entry point
├── main_window.py               # MainWindow class, menu, preset bar, history
├── config.py                    # Default paths, parameter labels and tooltips
├── workers.py                   # Background processes for acquisition / recon
├── serial_handler.py            # STM32 serial communication
├── logging_utils.py             # Thread-safe log queue + GUI log handler
├── iterative_params_dialog.py   # Dialog that reads iterative_parameters.py
├── style.qss                    # Grayscale UI stylesheet
├── runners/                     # Launchers that bridge GUI config -> algo main()
│   ├── run_fdk.py
│   ├── run_iterative.py
│   ├── run_fbp.py
│   └── _wrapper_common.py
├── presets.json                 # Auto-created on first preset save
├── runs.jsonl                   # Auto-created on first reconstruction
└── requirements.txt
```

---

## Troubleshooting

**GUI won't start** - usually a missing path. Check `main.py` and `config.py`
have the four paths filled in. The acquisition module path in particular
must point at the folder that contains `camera_config.py`.

**`ModuleNotFoundError: No module named 'tigre'`** - TIGRE isn't installed in
your Python environment. Follow the CERN TIGRE install guide. A working
install answers `python -c "import tigre"` silently.

**Serial port says "Not connected"** - ensure no other program (Arduino IDE,
PuTTY, another Python process) holds the port. Baud must match the STM32
firmware (default 115200).

**Reconstruction starts but fails instantly** - the wrapper echoes every
parameter it received at the top of the log. Verify the paths and values
are what you expect. The three most common causes are: wrong input folder,
TIGRE not on the Python path of the subprocess, or an invalid voxel size /
downsample combo.

**Parameters on the right panel "don't do anything"** - they do. Look for
the `[WRAPPER]` banner in the logs right after you click Run reconstruction
- the values you set are printed there and are what the algorithm uses.

**Napari window never appears** - Napari needs a Qt backend. If you
installed PySide6 already you're covered. If you see an error about
`qtpy`, run `pip install qtpy`.

---

## Features added recently

- `runners/` wrappers so right-panel parameters actually apply to the
  algorithm call (previously the scripts used their own hardcoded CONFIG).
- Iteratives `Advanced...` dialog that reads `iterative_parameters.py`
  dynamically.
- Preset save / load, reconstruction history viewer.
- Light-polish grayscale stylesheet, resizable splitter, indeterminate
  progress bar while a run is in flight, per-field tooltips and red-border
  validation.

---

<details>
<summary><b>Developer notes (architecture deep-dive)</b></summary>

### Process model

```
MAIN PROCESS (GUI)
  - Qt event loop, log view, serial handler
  - QTimer polls a multiprocessing.Queue every 100 ms

                         |  messages ("progress", "log", "finished")
                         v

ACQUISITION PROCESS (separate interpreter)
  - Camera SDK (can block on hardware without freezing GUI)
  - Image correction + file saving
  - Log handler pushes to result queue
```

Reconstruction uses the same pattern: a separate process driven by
`multiprocessing`, with stdout / stderr / `input()` redirected through
queues so interactive matplotlib / napari windows work inside the
subprocess without blocking the GUI.

### Signals / slots

All communication between workers and the main window is Qt signals, so it
is thread- and process-safe. `main_window._on_acq_progress`,
`_on_recon_progress`, `_on_recon_finished`, etc. are the slots.

### Paths of interest

- Entry point: `main.py` → creates `QApplication`, loads `style.qss`,
  instantiates `MainWindow`, runs `app.exec()`.
- Reconstruction launch: `main_window._do_reconstruction()` sets env vars
  and starts a `ReconstructionWorker`. The worker runs
  `_reconstruction_process_target` (in `workers.py`) which `runpy.run_path`s
  one of `runners/run_*.py`.
- Iterative parameter dialog: `iterative_params_dialog.load_algorithm_configs`
  reads `iterative_parameters.py` via `importlib.util.spec_from_file_location`.

### Extending

- **Add a reconstruction method**: create a new wrapper in `runners/` that
  imports your algorithm script's `main` function, then add an entry in
  `main_window._scan_reconstruction_methods` pointing to it. Nothing else
  has to change.
- **Expose a new parameter**: add it to `DEFAULT_RECON_CONFIG` (or
  `FBP_RECON_CONFIG`) in `config.py`, add display label and tooltip in
  `RECON_PARAM_DISPLAY` / `RECON_PARAM_TOOLTIPS`. Wrappers pick it up
  automatically from `RECON_CONFIG_JSON`.
- **New iterative algorithm**: add it to `ALGORITHM_CONFIGS` in
  `Reconstruction_Algorithms/.../Iteratives/iterative_parameters.py` and
  to `ITERATIVE_ALGORITHMS` / `ITERATIVE_ALGORITHM_ITERATIONS` in
  `config.py`. The `Advanced...` dialog picks up the new params
  automatically.

### GUI performance tuning (`config.py`)

```
LOG_MAX_QUEUE_SIZE      = 1000   # max pending log messages
LOG_FLUSH_INTERVAL_MS   = 250    # how often to update the log view
LOG_MAX_ITEMS_PER_FLUSH = 10     # max lines added per update
LOG_VIEW_MAX_BLOCKS     = 2000   # max lines kept in the log view
```

</details>
