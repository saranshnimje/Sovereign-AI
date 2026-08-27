"""
Generate a realistic bearing-run CSV for the SIH demonstration.

The produced dataset simulates ~24 h of 1-minute sampling on a motor
driving a loaded bearing:
  - temperature drifts up slowly as friction grows (60 -> 92 C)
  - vibration RMS rises with occasional spikes once wear accelerates
  - rpm sags slightly as load increases
  - small measurement noise everywhere

Nothing in the app knows about this file — the analysis must derive any
conclusions from these numbers alone.

Usage:  python scripts/generate_bearing_sample.py [out_path] [rows]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def generate(rows: int = 1440, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.arange(rows)

    # Wear accelerates over the last third of the run
    wear = np.clip((t - rows * 0.66) / (rows * 0.34), 0, 1) ** 1.6

    temp = 60 + 30 * wear + rng.normal(0, 0.25, rows)
    vib_base = 2.8 + 2.4 * wear
    vib = vib_base + np.abs(rng.normal(0, 0.18, rows))
    spike_idx = rng.choice(np.where(wear > 0.35)[0], size=max(3, int(12 * wear.max())), replace=False)
    vib[spike_idx] += rng.uniform(2.5, 5.5, len(spike_idx))
    rpm = 1492 - 14 * wear + rng.normal(0, 2.0, rows)
    ts = pd.date_range("2026-01-15 06:00", periods=rows, freq="min")

    return pd.DataFrame({
        "timestamp": ts,
        "bearing_temp_C": np.round(temp, 2),
        "vibration_mm_s": np.round(vib, 3),
        "motor_rpm": np.round(rpm, 1),
    })


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "sample_data" / "bearing_run.csv"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1440
    out.parent.mkdir(parents=True, exist_ok=True)
    df = generate(n)
    df.to_csv(out, index=False)
    print(f"Wrote {len(df)} rows -> {out}")
    print(df.tail(3).to_string(index=False))
