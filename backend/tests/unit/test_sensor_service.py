"""
Unit tests for the deterministic sensor analysis engine.

These verify REAL computation: parsing, schema detection, statistics,
trends, anomaly methods, risk aggregation, and input guards.
No LLM involved anywhere in this module — by design.
"""
import math

import pytest

from services.sensor_analysis_service import (
    DEFAULT_THRESHOLD_RULES,
    MAX_ROWS,
    SensorAnalysisError,
    analyze_csv_bytes,
    build_explanation_prompt,
)


def _csv(rows: list[str], header: str = "timestamp,temperature,vibration,rpm\n") -> bytes:
    return (header + "\n".join(rows)).encode()


BASIC_ROWS = [f"2026-01-01T00:{i:02d}:00,{60.0 + i * 0.01:.3f},3.0,1490" for i in range(30)]


class TestParsingAndValidation:
    def test_valid_csv_basic_shape(self):
        p = analyze_csv_bytes(_csv(BASIC_ROWS), "t.csv")
        assert p["file"]["rows"] == 30
        assert set(p["schema"]["numeric_columns"]) == {"temperature", "vibration", "rpm"}
        assert p["schema"]["timestamp_column"] == "timestamp"

    def test_malformed_csv_rejected(self):
        content = b"a,b\n1,2\nthis is not csv at all,\x00\x01\x02\n\"unterminated"
        with pytest.raises(SensorAnalysisError, match="[Mm]alformed|parse"):
            analyze_csv_bytes(content, "bad.csv")

    def test_empty_data_rejected(self):
        with pytest.raises(SensorAnalysisError):
            analyze_csv_bytes(b"colA,colB\n", "empty.csv")

    def test_missing_values_counted(self):
        rows = ["2026-01-01T00:00:00,60,,1490",
                "2026-01-01T00:01:00,61,3.1,1491"]
        p = analyze_csv_bytes(_csv(rows), "m.csv")
        assert p["quality"]["missing_by_column"]["vibration"] == 1
        assert p["quality"]["total_missing_cells"] == 1
        assert p["stats"]["vibration"]["count"] == 1  # NaN excluded from stats

    def test_invalid_numeric_values_counted(self):
        # "FAULT" is NOT a pandas built-in NA token, so it must surface as a
        # coercion failure (invalid numeric), not as a missing value.
        rows = [f"2026-01-01T00:{i:02d}:00,{60 + i * 0.1:.2f},3.0,FAULT" if i % 3 == 0 else
                f"2026-01-01T00:{i:02d}:00,{60 + i * 0.1:.2f},3.0,1490"
                for i in range(12)]
        p = analyze_csv_bytes(_csv(rows), "inv.csv")
        assert p["quality"]["invalid_numeric_values"].get("rpm", 0) == 4

    def test_no_numeric_columns_rejected(self):
        with pytest.raises(SensorAnalysisError, match="[Nn]o usable numeric"):
            analyze_csv_bytes(b"name,note\nalpha,hello\nbeta,world\n", "txt.csv")

    def test_duplicate_timestamps_detected(self):
        rows = ["2026-01-01T00:00:00,60,3.0,1490"] * 5
        p = analyze_csv_bytes(_csv(rows), "dup.csv")
        assert p["quality"]["duplicate_timestamps"] == 4

    def test_row_limit_guard(self, monkeypatch):
        monkeypatch.setattr("services.sensor_analysis_service.MAX_ROWS", 10)
        rows = [f"2026-01-01T00:{i%60:02d}:00,60,3,1490" for i in range(20)]
        with pytest.raises(SensorAnalysisError, match="limit"):
            analyze_csv_bytes(_csv(rows), "big.csv")

    def test_semicolon_delimiter_supported(self):
        content = "ts;temp;vib\n2026-01-01T00:00:00;60;3.0\n2026-01-01T00:01:00;61;3.2\n".encode()
        p = analyze_csv_bytes(content, "semi.csv")
        assert set(p["schema"]["numeric_columns"]) == {"temp", "vib"}


class TestDeterministicStatistics:
    def test_stats_known_values(self):
        rows = [f"r{i},{i}" for i in range(1, 11)]  # 1..10
        p = analyze_csv_bytes(("idx,v\n" + "\n".join(rows) + "\n").encode(), "s.csv")
        st = p["stats"]["v"]
        assert st["count"] == 10
        assert st["min"] == 1.0 and st["max"] == 10.0
        assert st["median"] == 5.5
        assert math.isclose(st["mean"], 5.5)
        # std of 1..10 population = sqrt(8.25)
        assert math.isclose(st["std"], math.sqrt(8.25), rel_tol=1e-6)

    def test_trend_increasing_detected(self):
        rows = [f"r{i},{50 + i * 2}" for i in range(40)]  # strong ramp
        p = analyze_csv_bytes(("t,val\n" + "\n".join(rows) + "\n").encode(), "tr.csv")
        assert p["stats"]["val"]["trend"] == "increasing"

    def test_stable_trend(self):
        rows = [f"r{i},{50 + (i % 3)}" for i in range(40)]
        p = analyze_csv_bytes(("t,val\n" + "\n".join(rows) + "\n").encode(), "st.csv")
        assert p["stats"]["val"]["trend"] == "stable"

    def test_percentiles_present(self):
        p = analyze_csv_bytes(_csv(BASIC_ROWS), "p.csv")
        st = p["stats"]["temperature"]
        for key in ("p05", "p25", "p75", "p95"):
            assert key in st


class TestAnomalyDetection:
    def _with_spike(self, spike_value=95.0):
        vals = [60.0] * 40
        vals[25] = spike_value
        rows = [f"2026-01-01T00:{i:02d}:00,{v}" for i, v in enumerate(vals)]
        return analyze_csv_bytes(
            ("timestamp,bearing_temp_C\n" + "\n".join(rows) + "\n").encode(), "spike.csv")

    def test_robust_z_flags_spike(self):
        p = self._with_spike()
        hits = [a for a in p["anomalies"] if a["method"] == "robust_z"]
        assert len(hits) >= 1
        hit = hits[0]
        assert hit["sensor"] == "bearing_temp_C"
        assert hit["value"] == 95.0
        assert hit["baseline"] == pytest.approx(60.0)
        assert hit["severity"] in ("medium", "high", "critical")
        assert hit["timestamp"].startswith("2026-01-01")

    def test_threshold_rule_matches_temperature_name(self):
        p = self._with_spike(spike_value=120.0)  # >85°C default rule (name has 'temp')
        thr = [a for a in p["anomalies"]
               if a["method"] == "threshold" and a["value"] == 120.0]
        assert len(thr) == 1
        assert thr[0]["explanation"]  # human-readable reason derived from data
        assert "85" in thr[0]["explanation"]

    def test_rate_change_flags_sudden_jump(self):
        vals = [60.0] * 20 + [90.0] + [90.0] * 19  # step change
        rows = [f"r{i},{v}" for i, v in enumerate(vals)]
        p = analyze_csv_bytes(("t,v\n" + "\n".join(rows) + "\n").encode(), "step.csv")
        rc = [a for a in p["anomalies"] if a["method"] == "rate_change"]
        assert len(rc) >= 1

    def test_clean_data_no_anomalies(self):
        # Realistic small noise around 60°C (±0.05 quantisation steps):
        # nothing should be flagged as severe.
        rows = [f"2026-01-01T00:{i:02d}:00,{60 + ((i % 3) - 1) * 0.05:.3f}" for i in range(60)]
        p = analyze_csv_bytes(
            ("timestamp,temp\n" + "\n".join(rows) + "\n").encode(), "clean.csv")
        severe = [a for a in p["anomalies"] if a["severity"] in ("high", "critical")]
        assert severe == [], severe

    def test_anomaly_record_schema(self):
        p = self._with_spike()
        required = {"timestamp", "row_index", "sensor", "value", "baseline",
                    "method", "score", "severity", "explanation"}
        for rec in p["anomalies"]:
            assert required <= set(rec.keys())


class TestRiskAggregation:
    def test_risk_derived_from_anomalies(self):
        p = analyze_csv_bytes(_csv(BASIC_ROWS), "ok.csv")
        assert p["risk"]["level"] in ("healthy", "watch")

    def test_risk_escalates_on_breaches(self):
        vals = [85.0] * 10 + [95.0] * 10  # sustained over temp limit
        rows = [f"r{i},{v}" for i, v in enumerate(vals)]
        p = analyze_csv_bytes(("t,temp_C\n" + "\n".join(rows) + "\n").encode(), "hot.csv")
        assert p["risk"]["level"] in ("elevated", "critical")
        assert p["risk"]["drivers"], "drivers must name offending sensors"
        assert any(d["sensor"] == "temp_C" for d in p["risk"]["drivers"])
        assert all("anomalies" in d and "reason" in d for d in p["risk"]["drivers"])


class TestDeterminismAndPrompt:
    def test_two_runs_identical_except_meta(self):
        a = analyze_csv_bytes(_csv(BASIC_ROWS), "d.csv")
        b = analyze_csv_bytes(_csv(BASIC_ROWS), "d.csv")
        a["meta"]["generated_at"] = ""
        b["meta"]["generated_at"] = ""
        assert a == b, "engine output must be deterministic"

    def test_prompt_contains_numbers_and_forbids_invention(self):
        p = analyze_csv_bytes(_csv(BASIC_ROWS), "pr.csv")
        system, user = build_explanation_prompt(p)
        assert "MUST NOT invent" in system
        assert "60.0" in user or '"mean"' in user
