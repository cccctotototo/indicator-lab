"""Copy to adapters/<same_name_as_pine>.py and implement the rules.

Adapters are trusted local Python code. Only run files you created or reviewed.
"""

from __future__ import annotations

import pandas as pd


PARAMETERS = {}


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    # Replace these two Series with your Pine long/short conditions.
    long_signal = pd.Series(False, index=df.index)
    short_signal = pd.Series(False, index=df.index)
    return pd.DataFrame({"long_signal": long_signal, "short_signal": short_signal})
