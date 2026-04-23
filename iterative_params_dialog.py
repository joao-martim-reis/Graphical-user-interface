"""
Dialog that lets the user edit the iterations and per-algorithm parameters
(blocksize, alpha, ...) defined in iterative_parameters.py.

The dialog dynamically reads ALGORITHM_CONFIGS from the reconstruction repo
at runtime using importlib, so adding a new algorithm to iterative_parameters.py
(or changing its params) is picked up without editing the GUI.
"""
import importlib.util
import os
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


def load_algorithm_configs(reconstruction_root):
    """
    Import iterative_parameters.py from the reconstruction root and return its
    ALGORITHM_CONFIGS dict. Returns None if the file can't be loaded.
    """
    if not reconstruction_root:
        return None
    candidate = Path(reconstruction_root) / "Iteratives" / "iterative_parameters.py"
    if not candidate.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "iterative_parameters_gui_view", str(candidate)
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "ALGORITHM_CONFIGS", None)
    except Exception:
        return None


class IterativeParametersDialog(QtWidgets.QDialog):
    """
    Edit iterations + per-algorithm params for one iterative algorithm.

    Parameters
    ----------
    algorithm_name : str
    algorithm_config : dict
        One entry from ALGORITHM_CONFIGS, with keys 'category', 'iterations',
        'description', 'params', ...
    current_overrides : dict, optional
        Previously-entered overrides for this algorithm (re-populated on reopen).
    """

    def __init__(self, algorithm_name, algorithm_config, current_overrides=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure parameters — {algorithm_name}")
        self.setModal(True)
        self.setMinimumWidth(440)

        self._algorithm_name = algorithm_name
        self._algorithm_config = algorithm_config or {}
        self._current_overrides = dict(current_overrides or {})
        self._param_widgets = {}  # key -> (widget, kind)

        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(self._build_header())

        form_group = QtWidgets.QGroupBox("Parameters")
        form = QtWidgets.QFormLayout(form_group)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        # Iterations (always shown)
        default_niter = int(self._algorithm_config.get("iterations", 50))
        niter_value = int(self._current_overrides.get("_iterations", default_niter))
        self._niter_spin = QtWidgets.QSpinBox()
        self._niter_spin.setRange(1, 5000)
        self._niter_spin.setValue(niter_value)
        self._niter_spin.setToolTip(
            f"Number of iterations (default for {algorithm_name}: {default_niter})."
        )
        form.addRow("Iterations", self._niter_spin)

        # Algorithm-specific params
        params = self._algorithm_config.get("params") or {}
        if not params:
            hint = QtWidgets.QLabel(
                "This algorithm has no tunable parameters beyond the iteration count."
            )
            hint.setStyleSheet("color: gray; font-style: italic;")
            hint.setWordWrap(True)
            form.addRow(hint)
        else:
            for key, default_value in params.items():
                current_value = self._current_overrides.get(key, default_value)
                widget = self._widget_for_value(key, default_value, current_value)
                form.addRow(key, widget)

        layout.addWidget(form_group)

        # Small hint about the underlying file
        src_hint = QtWidgets.QLabel(
            "Values come from iterative_parameters.py. Changes here apply only to "
            "this run — the file on disk is not modified."
        )
        src_hint.setStyleSheet("color: gray; font-size: 9pt; font-style: italic;")
        src_hint.setWordWrap(True)
        layout.addWidget(src_hint)

        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
            | QtWidgets.QDialogButtonBox.Cancel
            | QtWidgets.QDialogButtonBox.RestoreDefaults
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QtWidgets.QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        layout.addWidget(button_box)

    def _build_header(self):
        wrap = QtWidgets.QFrame()
        wrap.setFrameShape(QtWidgets.QFrame.StyledPanel)
        inner = QtWidgets.QVBoxLayout(wrap)
        inner.setContentsMargins(10, 8, 10, 8)

        title = QtWidgets.QLabel(self._algorithm_name)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title.setFont(title_font)

        category = self._algorithm_config.get("category", "")
        fn_name = self._algorithm_config.get("function_name", "")
        badge_text = f"category: {category}"
        if fn_name:
            badge_text += f"    |    tigre.algorithms.{fn_name}"
        badge = QtWidgets.QLabel(badge_text)
        badge.setStyleSheet("color: #555; font-size: 9pt;")

        desc = QtWidgets.QLabel(self._algorithm_config.get("description", ""))
        desc.setWordWrap(True)

        inner.addWidget(title)
        inner.addWidget(badge)
        inner.addWidget(desc)
        return wrap

    def _widget_for_value(self, key, default_value, current_value):
        if isinstance(default_value, bool):
            widget = QtWidgets.QCheckBox()
            widget.setChecked(bool(current_value))
            self._param_widgets[key] = (widget, "bool", default_value)
            return widget
        if isinstance(default_value, int):
            widget = QtWidgets.QSpinBox()
            widget.setRange(1, 10000)
            widget.setValue(int(current_value))
            widget.setToolTip(f"Default: {default_value}")
            self._param_widgets[key] = (widget, "int", default_value)
            return widget
        if isinstance(default_value, float):
            widget = QtWidgets.QDoubleSpinBox()
            widget.setDecimals(6)
            widget.setRange(0.0, 1000.0)
            widget.setSingleStep(0.001)
            widget.setValue(float(current_value))
            widget.setToolTip(f"Default: {default_value}")
            self._param_widgets[key] = (widget, "float", default_value)
            return widget
        # Fallback — string/other
        widget = QtWidgets.QLineEdit(str(current_value))
        widget.setToolTip(f"Default: {default_value}")
        self._param_widgets[key] = (widget, "str", default_value)
        return widget

    def _restore_defaults(self):
        self._niter_spin.setValue(int(self._algorithm_config.get("iterations", 50)))
        for key, (widget, kind, default_value) in self._param_widgets.items():
            if kind == "bool":
                widget.setChecked(bool(default_value))
            elif kind == "int":
                widget.setValue(int(default_value))
            elif kind == "float":
                widget.setValue(float(default_value))
            else:
                widget.setText(str(default_value))

    def result_overrides(self):
        """
        Return the overrides dict to pass through RECON_ALGO_PARAMS_JSON + the
        iterations value. Only values that DIFFER from the algorithm defaults
        are included, so running with untouched defaults sends nothing extra.
        """
        overrides = {}
        default_niter = int(self._algorithm_config.get("iterations", 50))
        new_niter = int(self._niter_spin.value())
        if new_niter != default_niter:
            overrides["_iterations"] = new_niter

        for key, (widget, kind, default_value) in self._param_widgets.items():
            if kind == "bool":
                value = bool(widget.isChecked())
            elif kind == "int":
                value = int(widget.value())
            elif kind == "float":
                value = float(widget.value())
            else:
                text = widget.text().strip()
                try:
                    value = float(text) if "." in text or "e" in text.lower() else int(text)
                except ValueError:
                    value = text
            if value != default_value:
                overrides[key] = value

        return overrides
