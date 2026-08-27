"""
Unit tests for incident service: deterministic risk rules, evidence shaping,
prompt construction guarantees, ACTION extraction.
"""
import pytest

from services.incident_service import (
    MAX_DOC_EVIDENCE,
    assess_risk,
    build_evidence,
    build_investigation_prompt,
    extract_action,
)


def _payload(temp_breaches=0, vib_anoms=0, temp_trend="stable", vib_trend="stable",
             worst=None, affected_pct=0.0):
    anomalies = []
    for _ in range(temp_breaches):
        anomalies.append({"timestamp": "t", "row_index": 1, "sensor": "bearing_temp_C",
                          "value": 95.0, "baseline": 60.0, "method": "threshold",
                          "score": 0.8, "severity": "high", "explanation": "over limit"})
    for _ in range(vib_anoms):
        anomalies.append({"timestamp": "t", "row_index": 2, "sensor": "vib_mm_s",
                          "value": 9.0, "baseline": 3.0, "method": "robust_z",
                          "score": 0.7, "severity": "high", "explanation": "spike"})
    summary = {}
    if temp_breaches:
        summary["bearing_temp_C"] = {"count": temp_breaches,
                                     "by_severity": {"high": temp_breaches},
                                     "methods": ["threshold"]}
    if vib_anoms:
        summary["vib_mm_s"] = {"count": vib_anoms,
                               "by_severity": {"high": vib_anoms},
                               "methods": ["robust_z"]}
    drivers = []
    if worst:
        drivers.append({"sensor": "bearing_temp_C", "worst_severity": worst,
                        "affected_pct": affected_pct})
    return {
        "stats": {
            "bearing_temp_C": {"trend": temp_trend, "change_pct": 40.0},
            "vib_mm_s": {"trend": vib_trend, "change_pct": 5.0},
        },
        "anomaly_summary": summary,
        "anomalies": anomalies,
        "risk": {"level": worst or "low", "drivers": drivers},
        "meta": {"engine": "deterministic-pandas-v1"},
    }


class TestDeterministicRisk:
    def test_no_payload_unknown(self):
        r = assess_risk(None)
        assert r["level"] == "unknown" and r["rules_hit"] == []

    def test_clean_payload_low(self):
        r = assess_risk(_payload())
        assert r["level"] == "low"
        assert r["rules_hit"] == []

    def test_temp_breach_plus_increasing_is_high(self):
        r = assess_risk(_payload(temp_breaches=12, temp_trend="increasing"))
        assert r["level"] in ("high", "critical")
        joined = " ".join(r["rules_hit"])
        assert "R1" in joined and "R2" in joined

    def test_vibration_anomaly_at_least_medium(self):
        r = assess_risk(_payload(vib_anoms=3))
        assert r["level"] in ("medium", "high", "critical")
        assert any(x.startswith("R3") for x in r["rules_hit"])

    def test_critical_driver_and_share_force_high(self):
        r = assess_risk(_payload(worst="critical", affected_pct=31.0))
        assert r["level"] in ("high", "critical")
        assert any(x.startswith("R5") for x in r["rules_hit"])
        assert any(x.startswith("R6") for x in r["rules_hit"])

    def test_rules_are_transparent(self):
        r = assess_risk(_payload(temp_breaches=5, vib_anoms=2,
                                 temp_trend="increasing", vib_trend="increasing",
                                 worst="critical", affected_pct=20))
        assert len(r["rules_hit"]) >= 5


class TestEvidenceShaping:
    def test_caps_documents_and_labels_citations(self):
        srcs = [{"doc_id": f"d{i}", "chunk_id": f"c{i}", "filename": "manual.pdf",
                 "page_number": i + 1, "score": 0.5, "content": "x" * 700}
                for i in range(12)]
        ev = build_evidence(srcs, None, None)
        assert len(ev["documents"]) == MAX_DOC_EVIDENCE
        d0 = ev["documents"][0]
        assert d0["citation_label"].startswith("[Doc 1: manual.pdf, p.1]")
        assert len(d0["content"]) <= 600

    def test_sensor_evidence_carries_required_fields(self):
        p = _payload(temp_breaches=2)
        ev = build_evidence([], p, "analysis-123")
        s = ev["sensors"][0]
        for key in ("analysis_id", "sensor", "value", "baseline", "method",
                    "severity", "timestamp", "explanation"):
            assert key in s
        assert s["analysis_id"] == "analysis-123"

    def test_insufficient_flag_when_nothing_collected(self):
        ev = build_evidence([], None, None)
        assert ev["insufficient_evidence"] is True
        assert ev["kb_had_no_hits"] is True


class TestPromptGuarantees:
    def test_prompt_supplies_numbers_verbatim_and_forbids_invention(self):
        p = _payload(temp_breaches=1)
        p["anomalies"][0]["value"] = 95.7
        ev = build_evidence(
            [{"doc_id": "d", "chunk_id": "c", "filename": "m.pdf",
              "page_number": 4, "score": 0.9, "content": "Lubricate bearing"}],
            p, "sa1")
        risk = assess_risk(p)
        system, user = build_investigation_prompt("why hot?", "Press A", "B-204", ev, risk)
        assert "MUST NOT invent" in system or "Never invent" in system
        assert "95.7" in user                      # measured value supplied
        assert "[Doc 1: m.pdf, p.4]" in user       # citation label exact
        assert '"level"' in user                   # deterministic risk included

    def test_insufficient_note_present(self):
        ev = build_evidence([], None, None)
        _, user = build_investigation_prompt("q", "", None, ev, assess_risk(None))
        assert "no evidence could be collected" in user


class TestActionExtraction:
    def test_extracts_last_action_line(self):
        text = "blah\nACTION: Replace bearing within 48 hours.\ntrailing"
        assert extract_action(text) == "Replace bearing within 48 hours."

    def test_missing_action_returns_none(self):
        assert extract_action("no protocol here") is None
        assert extract_action(None) is None
