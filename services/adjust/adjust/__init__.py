"""Bounded adjustments: a Meta model reads what the frozen math only counts, and code bounds what it may change.
(Hackathon work, Oct 28.)

Built now: the construction source, from DOB NOW permit descriptions (permits.py). The adjustment object and its
refusals (adjustment.py) are generic, so the later 311-text and venue-hours adjustments reuse them.
"""
import sys
from pathlib import Path

__version__ = "0.1.0"

try:   # the frozen model package; in the monorepo it sits at packages/model
    import noise_score  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "model"))
