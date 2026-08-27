"""
Incident service — deterministic risk rules + evidence shaping + prompt.

DESIGN CONTRACT
---------------
- Risk is computed by DETERMINISTIC RULES from the attached sensor analysis
  payload. The LLM never determines risk.
- Evidence snapshots are built server-side from already-ownership-checked
  artefacts; nothing is collected twice or from unauthorised sources.
- The AI prompt supplies all numbers verbatim and forbids invention; its
  output is stored as INTERPRETATION only.
"""
from __future__ import annotations

import json

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ----------------------------------------------------------------------
# Deterministic risk assessment
# ----------------------------------------------------------------------
def assess_risk(sensor_payload: dict | None) -> dict:
    """
    Rule-based risk derived ONLY from engine-computed sensor data.

    Rules (transparent, listed in output):
      R1 temperature threshold breaches exist            → at least medium
      R2 temperature trend increasing                    → +1 level
      R3 vibration anomalies present                     → at least medium
      R4 vibration trend increasing                      → +1 level
      R5 any critical-severity anomaly                   → at least high
      R6 affected share of worst driver ≥ 10% of samples → at least high

    The final level is the max contribution; every rule hit is recorded so
    the UI can show WHY. With no sensor payload: "unknown".
    """
    if not sensor_payload:
        return {
            "level": "unknown", "score": None,
            "rules_hit": [], "note": "No sensor analysis attached — risk not assessed",
        }

    stats = sensor_payload.get("stats", {})
    risk = sensor_payload.get("risk", {})
    summary = sensor_payload.get("anomaly_summary", {})

    def _find(prefixes):
        for name in stats:
            low = name.lower()
            if any(p in low for p in prefixes):
                return name
        return None

    temp_col = _find(["temp"])
    vib_col = _find(["vib"])

    level_idx = 0  # low
    rules_hit: list[str] = []

    temp_breaches = 0
    if temp_col and temp_col in summary:
        thr = summary[temp_col]["by_severity"]
        # threshold-method anomalies on temperature = physical-limit breaches
        temp_anoms = [
            a for a in sensor_payload.get("anomalies", [])
            if a["sensor"] == temp_col and a["method"] == "threshold"
        ]
        temp_breaches = len(temp_anoms)
        if temp_breaches > 0:
            rules_hit.append(f"R1 temperature limit breached ({temp_breaches} samples)")
            level_idx = max(level_idx, 1)

    if temp_col and stats.get(temp_col, {}).get("trend") == "increasing":
        rules_hit.append(f"R2 {temp_col} trend increasing")
        level_idx = max(level_idx, min(2, level_idx + 1))

    vib_anom = summary.get(vib_col, {}).get("count", 0) if vib_col else 0
    if vib_col and vib_anom > 0:
        rules_hit.append(f"R3 vibration anomalies present ({vib_anom})")
        level_idx = max(level_idx, 1)

    if vib_col and stats.get(vib_col, {}).get("trend") == "increasing":
        rules_hit.append(f"R4 vibration trend increasing")
        level_idx = max(level_idx, min(2, level_idx + 1))

    worst_sev = (risk.get("drivers") or [{}])[0].get("worst_severity")
    if worst_sev == "critical":
        rules_hit.append("R5 critical-severity anomaly recorded")
        level_idx = max(level_idx, 2)

    drivers = risk.get("drivers") or []
    if drivers and drivers[0].get("affected_pct", 0) >= 10:
        rules_hit.append(
            f"R6 top driver affects {drivers[0]['affected_pct']}% of samples"
        )
        level_idx = max(level_idx, 2)

    levels = ["low", "medium", "high", "critical"]
    score_map = {"low": 20, "medium": 45, "high": 70, "critical": 90}
    level = levels[level_idx]
    return {
        "level": level,
        "score": score_map[level],
        "rules_hit": rules_hit,
        "engine": sensor_payload.get("meta", {}).get("engine"),
        "based_on_analysis": True,
    }


# ----------------------------------------------------------------------
# Evidence shaping
# ----------------------------------------------------------------------
MAX_DOC_EVIDENCE = 8
MAX_SENSOR_EVIDENCE = 15


def build_evidence(
    doc_sources: list[dict],
    sensor_payload: dict | None,
    sensor_analysis_id: str | None,
) -> dict:
    """
    Snapshot EXACTLY what the investigation used.

    documents: existing RagService sources (chunk_id/doc_id/filename/page/score/content)
    sensors:   top anomalies by severity/score from the attached analysis
    """
    documents = [
        {
            "doc_id": s.get("doc_id", ""),
            "chunk_id": s.get("chunk_id", ""),
            "filename": s.get("filename", ""),
            "page_number": s.get("page_number"),
            "score": round(float(s.get("score", 0.0)), 4),
            "content": (s.get("content", "") or "")[:600],
            "citation_label": f"[Doc {i+1}: {s.get('filename','?')}"
                              f"{', p.' + str(s['page_number']) if s.get('page_number') else ''}]",
        }
        for i, s in enumerate(doc_sources[:MAX_DOC_EVIDENCE])
    ]

    sensors: list[dict] = []
    trends: list[dict] = []
    if sensor_payload:
        raw = sorted(
            sensor_payload.get("anomalies", []),
            key=lambda a: (-SEVERITY_ORDER.get(a["severity"], 0), -a["score"]),
        )
        for a in raw[:MAX_SENSOR_EVIDENCE]:
            sensors.append({
                "analysis_id": sensor_analysis_id,
                "sensor": a["sensor"],
                "value": a["value"],
                "baseline": a["baseline"],
                "method": a["method"],
                "severity": a["severity"],
                "timestamp": a["timestamp"],
                "explanation": a["explanation"],
            })
        for col, st in (sensor_payload.get("stats") or {}).items():
            trends.append({
                "sensor": col,
                "trend": st.get("trend"),
                "change_pct": st.get("change_pct"),
                "min": st.get("min"), "max": st.get("max"),
                "mean": st.get("mean"),
            })

    insufficient = len(documents) == 0 and len(sensors) == 0
    return {
        "documents": documents,
        "sensors": sensors,
        "trends": trends,
        "insufficient_evidence": insufficient,
        "kb_had_no_hits": len(documents) == 0,
    }


def _evidence_block(evidence: dict) -> str:
    parts: list[str] = ["EVIDENCE COLLECTED BY THE DETERMINISTIC PIPELINE "
                        "(values are engine-computed; cite them exactly):"]

    if evidence["sensors"]:
        parts.append("\nSENSOR ANOMALIES (measured):")
        for s in evidence["sensors"]:
            parts.append(
                f"- [{s['timestamp']}] {s['sensor']}: value={s['value']} vs baseline="
                f"{s['baseline']} ({s['method']}, severity={s['severity']}) — {s['explanation']}"
            )
    if evidence["trends"]:
        parts.append("\nSENSOR SUMMARY/TRENDS (measured):")
        for t in evidence["trends"]:
            parts.append(
                f"- {t['sensor']}: trend={t['trend']} change={t['change_pct']}% "
                f"(min={t['min']}, max={t['max']}, mean={t['mean']})"
            )
    if evidence["documents"]:
        parts.append("\nMAINTENANCE DOCUMENT EXCERPTS:")
        for d in evidence["documents"]:
            parts.append(f"- {d['citation_label']}:\n{d['content']}")
    else:
        parts.append("\nNO DOCUMENT EVIDENCE WAS RETRIEVED from the attached knowledge base.")

    return "\n".join(parts)


def build_investigation_prompt(
    description: str,
    machine: str,
    asset_tag: str | None,
    evidence: dict,
    risk: dict,
    vision_findings: list[dict] | None = None,
) -> tuple[str, str]:
    """
    Returns (system, user). The model must answer the investigation
    questions using ONLY supplied evidence, cite document labels verbatim,
    never invent values/pages/citations/actions, and finish with an ACTION line.

    vision_findings: optional VALIDATED structured results from the local
    vision model. Presented as a separate labelled section; the model must
    not invent visual details beyond these findings.
    """
    system = (
        "You are an industrial maintenance investigator. ALL numerical values, "
        "sensor readings, document excerpts and VISION FINDINGS below were collected "
        "by deterministic pipelines from authorised sources. STRICT RULES:\n"
        "1. Never invent sensor values, manual pages, citations or visual findings.\n"
        "2. Cite document excerpts ONLY with their exact labels, e.g. [Doc 1: file.pdf, p.12].\n"
        "3. Refer to image observations ONLY through the supplied VISION FINDINGS section.\n"
        "4. If any evidence type is missing or insufficient, say so explicitly.\n"
        "5. Never claim any action was executed - you only recommend.\n"
        "Answer these sections:\n"
        "1. What evidence was found\n2. Which sensor abnormalities matter\n"
        "3. What the maintenance documentation says\n"
        "4. What the visual inspection shows (only if findings are supplied)\n"
        "5. Likely explanation\n6. What the operator should investigate\n"
        "7. Recommended action\n8. Uncertainty / limitations\n"
        "Finish with exactly one final line: 'ACTION: <one-sentence recommended action>'"
    )
    user_parts = [
        f"INCIDENT: machine={machine or 'unspecified'}"
        f" asset={asset_tag or 'unspecified'}\nDESCRIPTION/QUESTION: {description}",
        _evidence_block(evidence),
    ]

    if vision_findings:
        parts = ["\nVISION FINDINGS (from local vision model on inspection images - "
                 "reported observations; do not embellish):"]
        for v in vision_findings:
            parts.append(json.dumps(v, default=str))
        user_parts.append("\n".join(parts))
    else:
        user_parts.append("\nVISION FINDINGS: none available for this incident.")

    user_parts.append(
        "\nDETERMINISTIC RISK ASSESSMENT (rule-based, computed before you): "
        + json.dumps(risk)
    )
    if evidence["insufficient_evidence"] and not vision_findings:
        user_parts.append(
            "NOTE: no evidence could be collected. State that no grounded "
            "conclusion is possible."
        )
    return system, "\n".join(user_parts)[:16_000]


def extract_action(ai_text: str | None) -> str | None:
    """Extract the ACTION line the protocol requires. Tolerant; may be None."""
    if not ai_text:
        return None
    for line in reversed([ln.strip() for ln in ai_text.splitlines()]):
        if line.upper().startswith("ACTION:"):
            action = line[len("ACTION:"):].strip()
            return action[:500] if action else None
    return None
