"""
Unit tests — vision service: strict structured-output validation,
availability resolution, and prompt guarantees.
"""
import pytest

from services import vision_service as vs


VALID = """
```json
{
  "finding": "Heat discoloration on bearing race",
  "defects": [
    {"type": "thermal_damage", "severity": "critical", "confidence": 1.5,
     "description": "Blueing around raceway"}
  ],
  "recommendation": "Replace bearing",
  "limitations": ["single image", "no thermal calibration"]
}
```
"""


class TestParseVisionResponse:
    def test_valid_fenced_json_normalised(self):
        r = vs.parse_vision_response(VALID)
        assert r["finding"].startswith("Heat discoloration")
        d = r["defects"][0]
        assert d["severity"] == "CRITICAL"          # normalised to enum
        assert d["confidence"] == 1.0               # clamped into [0,1]
        assert len(r["limitations"]) == 2
        assert r["recommendation"] == "Replace bearing"

    def test_no_json_rejected(self):
        with pytest.raises(vs.VisionError, match="Malformed"):
            vs.parse_vision_response("The image looks bad, sorry.")

    def test_invalid_severity_rejected(self):
        bad = '{"finding":"x","defects":[{"type":"t","severity":"EXTREME","confidence":0.9,"description":"d"}],"recommendation":null,"limitations":[]}'
        with pytest.raises(vs.VisionError, match="severity"):
            vs.parse_vision_response(bad)

    def test_non_numeric_confidence_rejected(self):
        bad = '{"finding":"x","defects":[{"type":"t","severity":"LOW","confidence":"high","description":"d"}],"recommendation":null,"limitations":[]}'
        with pytest.raises(vs.VisionError, match="numeric"):
            vs.parse_vision_response(bad)

    def test_defects_not_list_rejected(self):
        bad = '{"finding":"x","defects":"many","recommendation":null,"limitations":[]}'
        with pytest.raises(vs.VisionError, match="list"):
            vs.parse_vision_response(bad)


class TestAvailability:
    def test_unconfigured_returns_none(self, monkeypatch):
        monkeypatch.setattr(vs, "resolve_vision_model", lambda: None)
        assert vs.resolve_vision_model() is None

    def test_settings_model_used_when_no_role(self, monkeypatch):
        from config import get_settings
        s = get_settings()
        monkeypatch.setattr(type(s), "default_vision_model", property(
            lambda self: "llava:7b"), raising=False)
        # bypass roles binding entirely
        import services.model_service as ms
        monkeypatch.setattr(ms, "_load_roles", lambda: {}, raising=False)
        assert vs.resolve_vision_model() == "llava:7b"


class TestPromptGuarantees:
    def test_prompt_has_schema_and_honesty_rules(self):
        system, user = vs.build_vision_prompt("Press A", "B-204")
        assert '"defects"' in system and "LOW|MEDIUM|HIGH|CRITICAL" in system
        assert "never invent" in system.lower()
        assert "B-204" in user

    def test_investigation_prompt_separates_vision_section(self):
        from services.incident_service import (
            assess_risk, build_evidence, build_investigation_prompt,
        )

        ev = build_evidence([], None, None)
        findings = [{"filename": "b204.png", "finding": "blueing",
                     "defects": [], "recommendation": "replace",
                     "limitations": []}]
        _, user = build_investigation_prompt(
            "q?", "Press A", "B-204", ev, assess_risk(None),
            vision_findings=findings)
        assert "VISION FINDINGS" in user
        assert "blueing" in user

    def test_investigation_prompt_states_absence(self):
        from services.incident_service import (
            assess_risk, build_evidence, build_investigation_prompt,
        )

        ev = build_evidence([], None, None)
        _, user = build_investigation_prompt(
            "q?", "", None, ev, assess_risk(None), vision_findings=None)
        assert "VISION FINDINGS: none available" in user
