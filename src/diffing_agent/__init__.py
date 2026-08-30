"""v0 black-box model-diffing agent (B13 benchmark).

Interviews two anonymous target endpoints and decides whether they differ.
See README_HARNESS.md for how to run it.
"""

from .agent import run
from .config import BrainConfig, RunConfig, TargetConfig

__all__ = ["run", "RunConfig", "TargetConfig", "BrainConfig"]
__version__ = "0.1.0"
