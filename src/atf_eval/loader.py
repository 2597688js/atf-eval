from __future__ import annotations

import importlib

from atf_eval.adapter import TrajectoryAgent


def load_adapter(spec: str) -> TrajectoryAgent:
    """Instantiate an adapter from "module.path:ClassName", no constructor args."""
    if ":" not in spec:
        raise ValueError(
            f"invalid adapter spec {spec!r}, expected 'module.path:ClassName'"
        )
    module_path, class_name = spec.split(":", 1)

    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise ImportError(f"could not import adapter module {module_path!r}: {e}") from e

    try:
        adapter_cls = getattr(module, class_name)
    except AttributeError as e:
        raise AttributeError(
            f"module {module_path!r} has no class {class_name!r}"
        ) from e

    return adapter_cls()
