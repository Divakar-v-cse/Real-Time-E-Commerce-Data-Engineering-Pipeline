"""Data-quality suite for the lakehouse and warehouse layers.

Exports are resolved lazily so ``python -m pipeline.quality.checks`` does not
import the module twice (once as part of the package, once as ``__main__``).
"""
from typing import Any

__all__ = ["CheckResult", "run_checks", "score_results"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from pipeline.quality import checks

        return getattr(checks, name)
    raise AttributeError(f"module 'pipeline.quality' has no attribute {name!r}")
