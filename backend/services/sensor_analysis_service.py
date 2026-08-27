"""
Deterministic sensor/CSV analysis engine.

DESIGN CONTRACT
---------------
- ALL numerical results are computed here with pandas/numpy.
  The LLM is NEVER asked to calculate anything and can only annotate the
  persisted numbers (see routers/sensor_analysis.py).
- Every method is transparent: anomalies record WHICH method produced them,
  the baseline used, and a score. No black-box models.
- Invalid/malformed input raises SensorAnalysisError with an honest message;
  nothing is silently dropped or fabricated.

Pipeline:
  decode → parse CSV → shape guards → schema detection → numeric coercion
  → per-column stats + trend → anomaly detection (threshold | robust-z | ROC)
  → risk aggregation → payload dict (JSON-safe).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ---- Hard input guards (module-level so tests can tighten them) ----
MAX_ROWS = 200_000
MAX_COLS = 60


class SensorAnalysisError(ValueError):
    """Raised for any invalid/unusable sensor input (honest, specific)."""


# ----------------------------------------------------------------------
# Threshold rules — applied ONLY when a column name clearly matches a known
# physical quantity. Bounds are generic engineering defaults, overridable via
# request. Matching is case-insensitive substring on the column name.
# ----------------------------------------------------------------------
DEFAULT_THRESHOLD_RULES: dict[str, dict] = {
    "temperature": {"pattern": "temp", "min": None, "max": 85.0, "unit": "°C"},
    "vibration":   {"pattern": "vib",   "min": None, "max": 6.0,  "unit": "mm/s"},
    "pressure":    {"pattern": "press", "min": 2.0,  "max": 120.0, "unit": "psi"},
    "speed":       {"pattern": "rpm",   "min": 100.0, "max": 3600.0, "unit": "rpm"},
}

_TIMESTAMP_HINTS = ("timestamp", "time", "date", "ts")

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _decode(content: bytes) -> tuple[str, str]:
    """Decode bytes with explicit fallbacks. Returns (text, encoding)."""
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return content.decode(enc), enc
        except UnicodeDecodeError:
            continue
    try:
        return content.decode("latin-1"), "latin-1"
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 decodes all
        raise SensorAnalysisError(f"Could not decode file: {exc}") from exc


def _parse_csv(text: str) -> pd.DataFrame:
    """Parse CSV text with delimiter sniffing between common separators."""
    last_err: Exception | None = None
    candidate: pd.DataFrame | None = None
    for sep in (",", ";", "\t"):
        try:
            df = pd.read_csv(
                io.StringIO(text),
                sep=sep,
                engine="python",
                on_bad_lines="error",
            )
        except pd.errors.ParserError as exc:
            last_err = exc
            continue
        except ValueError as exc:  # embedded NULs / decode oddities surface here
            last_err = exc
            continue
        if df.empty or df.shape[1] == 0:
            raise SensorAnalysisError("CSV contains no data rows")
        if df.shape[1] == 1 and sep != "\t":
            candidate = df
            continue
        return df
    # Fall back to the single-column candidate if one exists; otherwise honest error
    try:
        if candidate is not None and candidate.shape[1] >= 1:
            return candidate
    except NameError:
        pass
    raise SensorAnalysisError(f"Malformed CSV: could not parse ({last_err})")


def _detect_schema(df: pd.DataFrame) -> dict:
    """
    Classify columns: timestamp / numeric / ignored.
    Numeric detection coerces object columns; coercion failures are counted,
    not hidden.
    """
    timestamp_col: str | None = None
    numeric: list[str] = []
    ignored: list[str] = []
    coercion_failures: dict[str, int] = {}

    # --- timestamp detection ---
    for col in df.columns:
        low = str(col).lower()
        looks_timey = any(h in low for h in _TIMESTAMP_HINTS)
        if looks_timey:
            parsed = pd.to_datetime(df[col], errors="coerce")
            ok_ratio = parsed.notna().mean()
            if ok_ratio >= 0.9:
                timestamp_col = col
                break

    # --- numeric classification ---
    series_map: dict[str, pd.Series] = {}
    for col in df.columns:
        if col == timestamp_col:
            continue
        raw = df[col]
        if pd.api.types.is_numeric_dtype(raw):
            series_map[str(col)] = raw.astype("float64")
            numeric.append(str(col))
            continue
        coerced = pd.to_numeric(raw.astype(str).str.strip(), errors="coerce")
        bad = int(coerced.isna().sum() - raw.isna().sum())
        if len(coerced) and coerced.notna().mean() >= 0.5:
            series_map[str(col)] = coerced
            numeric.append(str(col))
            if bad > 0:
                coercion_failures[str(col)] = bad
        else:
            ignored.append(str(col))

    return {
        "timestamp_column": str(timestamp_col) if timestamp_col is not None else None,
        "numeric_columns": numeric,
        "ignored_columns": ignored,
        "coercion_failures": coercion_failures,
        "series": series_map,
    }


def _column_stats(s: pd.Series) -> dict:
    """Deterministic descriptive statistics for one numeric series."""
    v = s.dropna()
    if v.empty:
        return {"count": 0, "missing": int(s.isna().sum())}

    q = v.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    diff = v.diff().dropna()
    roc_max_idx = diff.abs().idxmax() if not diff.empty else None

    # Least-squares slope over sample index, normalised to % of mean per step
    x = np.arange(len(v), dtype=float)
    mean = float(v.mean())
    if mean == 0 or len(v) < 2:
        slope_norm = 0.0
    else:
        slope = float(np.polyfit(x, v.to_numpy(dtype=float), 1)[0])
        slope_norm = slope / abs(mean)

    change_pct = float((v.iloc[-1] - v.iloc[0]) / abs(mean) * 100) if mean else 0.0
    trend = "stable"
    if abs(change_pct) >= 10:
        trend = "increasing" if change_pct > 0 else "decreasing"

    stats = {
        "count": int(v.size),
        "missing": int(s.isna().sum()),
        "min": float(v.min()),
        "max": float(v.max()),
        "mean": round(mean, 6),
        "median": float(q[0.5]),
        "std": float(v.std(ddof=0)),
        "p05": float(q[0.05]),
        "p25": float(q[0.25]),
        "p75": float(q[0.75]),
        "p95": float(q[0.95]),
        "roc_mean": round(float(diff.abs().mean()), 6) if not diff.empty else 0.0,
        "roc_max": round(float(diff.abs().max()), 6) if not diff.empty else 0.0,
        "roc_max_index": int(roc_max_idx) if roc_max_idx is not None and isinstance(roc_max_idx, (int, np.integer)) else None,
        "slope_per_step": round(slope_norm, 8),
        "trend": trend,
        "change_pct": round(change_pct, 3),
    }
    return stats


def _robust_z(v: pd.Series) -> pd.Series | None:
    """
    Robust z-score (Iglewicz–Hoaglin) using median/MAD.
    Degenerate fallbacks, documented:
      - MAD == 0 (constant-ish baseline): fall back to classic z = (x-mean)/std
      - std also 0: return None → caller uses zero-variance deviation check
    """
    med = v.median()
    mad = (v - med).abs().median()
    if mad and not np.isnan(mad):
        return 0.6745 * (v - med) / mad
    std = v.std(ddof=0)
    if std and not np.isnan(std):
        return (v - med) / std
    return None


def _severity_from_score(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _detect_anomalies(
    col: str,
    s: pd.Series,
    ts_labels: list[str],
    rules: dict[str, dict],
) -> list[dict]:
    """
    Transparent multi-method anomaly detection for ONE column.

    Methods:
      threshold  — configured physical bounds matched by column-name pattern
      robust_z   — median/MAD z-score ≥ 3.5 (Iglewicz–Hoaglin)
      rate_change— sudden jump/drop: |Δ| robust-z ≥ 4 vs step distribution
    Each record carries method, baseline, score, severity and a plain-language
    explanation derived strictly from the observed values.
    """
    out: list[dict] = []
    med = s.median()

    def _emit(idx, value, baseline, method, score, detail):
        sev = _severity_from_score(score)
        ts = ts_labels[idx] if idx < len(ts_labels) else f"row {idx}"
        out.append({
            "timestamp": ts,
            "row_index": int(idx),
            "sensor": col,
            "value": float(value),
            "baseline": float(baseline),
            "method": method,
            "score": round(float(score), 4),
            "severity": sev,
            "explanation": detail,
        })

    # -- 1. Threshold rules --
    low_name = col.lower()
    for rule_name, rule in rules.items():
        if rule["pattern"] in low_name:
            for idx, value in s.items():
                if pd.isna(value):
                    continue
                breached, bound = False, None
                if rule["min"] is not None and value < rule["min"]:
                    breached, bound = True, rule["min"]
                elif rule["max"] is not None and value > rule["max"]:
                    breached, bound = True, rule["max"]
                if breached:
                    span = max(abs(rule["max"] or 0) , abs(rule["min"] or 0), 1e-9)
                    beyond = abs(float(value) - bound)
                    score = min(1.0, 0.55 + 0.35 * (beyond / span))
                    side = "above maximum" if value > (rule["max"] if rule["max"] is not None else rule["min"]) else "below minimum"
                    _emit(
                        idx, value, bound, "threshold", score,
                        f"{col}={float(value):.3g} is {side} limit {bound:.3g} "
                        f"{rule.get('unit', '')} (rule: {rule_name})",
                    )
            break  # first matching rule wins (documented precedence)

    # -- 2. Robust z-score (with zero-variance fallback) --
    vals = s.dropna()
    rz = _robust_z(vals)
    if rz is not None:
        for idx in rz.index:
            z = rz[idx]
            if pd.isna(z) or abs(z) < 3.5:
                continue
            score = min(1.0, abs(z) / 12.0)
            direction = "high" if z > 0 else "low"
            _emit(
                idx, vals[idx], med, "robust_z", score,
                f"{col}={float(vals[idx]):.3g} is {direction} relative to typical "
                f"level {float(med):.3g} (z={float(z):.2f}, cutoff 3.5)",
            )
    else:
        # Fully constant baseline — any deviation IS significant; use a
        # transparent relative-tolerance gate instead of a statistical one.
        tolerance = max(1e-9, 0.02 * abs(med))
        deviations = vals[(vals - med).abs() > tolerance]
        for idx, value in deviations.items():
            score = 0.9
            _emit(
                idx, value, med, "robust_z", score,
                f"{col}={float(value):.3g} deviates from an otherwise constant "
                f"baseline {float(med):.3g}",
            )

    # -- 3. Rate-of-change spikes --
    d = s.diff()
    dz = _robust_z(d.dropna())
    if dz is not None:
        # Significance gate: ignore steps smaller than 2% of the typical level
        # so quantisation/noise alternation cannot fabricate anomalies.
        typical_level = abs(med) if med else float(s.std(ddof=0)) or 1.0
        min_significant_delta = 0.02 * typical_level
        for idx in dz.index:
            z = dz[idx]
            if pd.isna(z) or abs(z) < 4.0:
                continue
            prev = s.loc[idx - 1] if idx - 1 in s.index else np.nan
            if pd.isna(prev):
                continue
            delta = float(s.loc[idx] - prev)
            if abs(delta) < min_significant_delta:
                continue
            score = min(1.0, abs(z) / 14.0)
            kind = "jump" if z > 0 else "drop"
            _emit(
                idx, s.loc[idx], prev, "rate_change", score,
                f"{col} changed by {delta:+.3g} at row {idx} "
                f"({kind} vs typical step variation, robust z={float(z):.2f})",
            )

    return out


def _aggregate_risk(anomalies: list[dict], stats: dict) -> dict:
    """
    Risk indicators derived STRICTLY from computed counts/severities.
    Overall level = worst driver across sensors; drivers explain why.
    """
    SEV_WEIGHT = {"low": 10, "medium": 25, "high": 50, "critical": 80}
    by_sensor: dict[str, dict] = {}
    for a in anomalies:
        entry = by_sensor.setdefault(a["sensor"], {"count": 0, "worst": "low"})
        entry["count"] += 1
        if SEVERITY_ORDER[a["severity"]] > SEVERITY_ORDER[entry["worst"]]:
            entry["worst"] = a["severity"]

    drivers: list[dict] = []
    overall_score = 0
    for sensor, info in sorted(by_sensor.items()):
        st = stats.get(sensor, {})
        n = int(st.get("count") or 0)
        rate = (info["count"] / n * 100) if n else 100.0
        score = min(100, SEV_WEIGHT[info["worst"]] + int(rate))
        drivers.append({
            "sensor": sensor,
            "anomalies": info["count"],
            "affected_pct": round(rate, 2),
            "worst_severity": info["worst"],
            "trend": st.get("trend"),
            "risk_score": score,
            "reason": (
                f"{info['count']} anomalies ({rate:.1f}% of samples), worst="
                f"{info['worst']}, trend={st.get('trend')}"
            ),
        })
        overall_score = max(overall_score, score)

    drivers.sort(key=lambda d: d["risk_score"], reverse=True)
    if overall_score >= 70:
        level = "critical"
    elif overall_score >= 45:
        level = "elevated"
    elif overall_score >= 20:
        level = "watch"
    else:
        level = "healthy"

    return {
        "level": level if drivers else "healthy",
        "score": overall_score,
        "drivers": drivers[:10],
    }


def analyze_csv_bytes(
    content: bytes,
    filename: str,
    threshold_rules: dict[str, dict] | None = None,
) -> dict:
    """
    Full deterministic analysis. Returns a JSON-safe payload dict.
    Raises SensorAnalysisError on invalid input.
    """
    text, encoding = _decode(content)

    # Quick structural guard before parsing
    line_count = text.count("\n") + 1
    if line_count > MAX_ROWS + 1:
        raise SensorAnalysisError(
            f"Dataset has ~{line_count:,} rows; limit is {MAX_ROWS:,}. "
            "Export a narrower time window."
        )

    df = _parse_csv(text)
    if len(df) == 0:
        raise SensorAnalysisError("CSV contains no data rows")
    if len(df) > MAX_ROWS:
        raise SensorAnalysisError(
            f"Dataset has {len(df):,} rows; limit is {MAX_ROWS:,}"
        )
    if df.shape[1] > MAX_COLS:
        raise SensorAnalysisError(
            f"Dataset has {df.shape[1]} columns; limit is {MAX_COLS}"
        )

    schema = _detect_schema(df)
    if not schema["numeric_columns"]:
        raise SensorAnalysisError(
            "No usable numeric sensor columns found "
            f"(ignored non-numeric: {schema['ignored_columns'][:5]})"
        )

    # Timestamp labels for anomaly records (fall back to row index)
    ts_col = schema["timestamp_column"]
    if ts_col is not None:
        ts_series = pd.to_datetime(df[ts_col], errors="coerce")
        duplicate_ts = int(ts_series.duplicated().sum())
        order = ts_series.sort_values(na_position="last").index
        df = df.loc[order]
        labels = [
            str(t) if pd.notna(t) else f"row {i}"
            for i, t in zip(order, ts_series.loc[order])
        ]
    else:
        duplicate_ts = 0
        labels = [f"row {i}" for i in range(len(df))]

    rules = threshold_rules if threshold_rules is not None else DEFAULT_THRESHOLD_RULES

    stats: dict[str, dict] = {}
    anomalies: list[dict] = []
    missing_by_column: dict[str, int] = {}
    trend_preview: dict[str, list[list[float]]] = {}

    # Downsampled series previews (≤80 points, even stride) for UI charts.
    # These are real observed values — never interpolated or invented.
    PREVIEW_POINTS = 80
    n_rows = len(df)
    stride = max(1, n_rows // PREVIEW_POINTS)
    for col in schema["numeric_columns"]:
        s = schema["series"][col].reset_index(drop=True)
        stats[col] = _column_stats(s)
        missing_by_column[col] = int(s.isna().sum())
        anomalies.extend(_detect_anomalies(col, s, labels, rules))

        sampled = s.iloc[::stride]
        valid = sampled.dropna()
        # .items() yields (index_label, value) — correct pairing after dropna
        trend_preview[col] = [[float(i), float(v)] for i, v in valid.items()]

    anomalies.sort(key=lambda a: (-SEVERITY_ORDER[a["severity"]], -a["score"], a["row_index"]))
    total_anomalies = len(anomalies)

    anomaly_summary = {}
    for a in anomalies:
        summary = anomaly_summary.setdefault(a["sensor"], {
            "count": 0, "by_severity": {"low": 0, "medium": 0, "high": 0, "critical": 0},
            "methods": [],
        })
        summary["count"] += 1
        summary["by_severity"][a["severity"]] += 1
        if a["method"] not in summary["methods"]:
            summary["methods"].append(a["method"])

    risk = _aggregate_risk(anomalies, stats)

    quality = {
        "missing_by_column": missing_by_column,
        "total_missing_cells": int(sum(missing_by_column.values())),
        "invalid_numeric_values": schema["coercion_failures"],
        "duplicate_timestamps": duplicate_ts,
    }

    payload = {
        "file": {
            "original_name": filename,
            "size_bytes": len(content),
            "encoding": encoding,
            "rows": int(len(df)),
            "columns": int(df.shape[1]),
        },
        "schema": {k: schema[k] for k in (
            "timestamp_column", "numeric_columns", "ignored_columns", "coercion_failures")},
        "quality": quality,
        "stats": stats,
        "trend_preview": trend_preview,
        "anomaly_summary": anomaly_summary,
        "total_anomalies": total_anomalies,
        # Persist at most 500 most-severe records; summary always covers all
        "anomalies": anomalies[:500],
        "truncated_anomalies": max(0, total_anomalies - 500),
        "risk": risk,
        "meta": {
            "engine": "deterministic-pandas-v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "methods": ["threshold", "robust_z(mad)", "rate_change"],
        },
    }
    return payload


def build_explanation_prompt(payload: dict, max_chars: int = 6000) -> tuple[str, str]:
    """
    Build (system, user) prompts for the OPTIONAL AI explanation.
    The prompt explicitly forbids inventing numbers: everything numeric is
    supplied by the deterministic engine.
    """
    system = (
        "You are an industrial assistant explaining sensor analysis results. "
        "ALL numerical values in the supplied JSON were computed by a deterministic "
        "analysis engine. You MUST NOT invent, alter, or add any measurements. "
        "Only interpret what is present. If evidence is insufficient, say so. "
        "Structure your answer with sections: What happened; Abnormal sensors; "
        "Likely interpretation; Severity; Recommended investigation; Limitations."
    )
    compact = {
        "file": payload["file"],
        "schema": payload["schema"],
        "quality": payload["quality"],
        "stats": payload["stats"],
        "risk": payload["risk"],
        "top_anomalies": payload["anomalies"][:25],
        "anomaly_summary": payload["anomaly_summary"],
        "note": "values are engine-computed; cite them verbatim when used",
    }
    user = "Sensor analysis JSON:\n" + __import__("json").dumps(compact, default=str)[:max_chars]
    return system, user
