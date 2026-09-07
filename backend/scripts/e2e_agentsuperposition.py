"""Live E2E: agentic chat through the real HTTP API.

Runs the exact Superposition Theorem scenario against the running stack
(Docker backend on :8000), then asserts every TASK-8 checklist item from the
observed SSE timeline, the persisted agent-events, and the conversation detail.

Requires an analyst-role account (web_search/web_fetch are analyst-only).
Usage:
    python scripts/e2e_agentsuperposition.py --email e2e_analyst@test.com --password '...'
"""
import argparse
import json
import sys
import time

import requests

BASE = "http://localhost:8000/api/v1"

PROMPT = (
    "Prove the Superposition Theorem in linear circuit theory from first principles. "
    "Research the formal statement, then verify it numerically with a concrete "
    "two-source circuit calculation. Cite your web sources and show the arithmetic."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()

    s = requests.Session()

    # 1) Login (analyst)
    r = s.post(f"{args.base}/auth/login",
               json={"email": args.email, "password": args.password}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"
    me = s.get(f"{args.base}/auth/me", timeout=30)
    me.raise_for_status()
    role = me.json().get("role")
    print(f"1) login ok, role: {role}")

    # 2) Locate the OpenRouter provider id (real provider-resolver discovery)
    provs = s.get(f"{args.base}/models/providers/", timeout=30)
    provs.raise_for_status()
    openrouter_id = None
    for p in provs.json():
        if p.get("provider_type") == "openrouter" or "openrouter" in (p.get("name") or "").lower():
            openrouter_id = p["id"]
    print("2) openrouter provider id:", openrouter_id)

    # 3) Create conversation with model openrouter/free
    r = s.post(f"{args.base}/chat/conversations",
               json={"model_name": "openrouter/free",
                     "title": "E2E Superposition"},
               timeout=30)
    r.raise_for_status()
    conv = r.json()
    conv_id = conv["id"]
    print("3) conversation:", conv_id, "model=", conv["model_name"])

    # 4) Fire the agent run (Agent=autonomous, Tools=Auto) and capture SSE
    payload = {
        "content": PROMPT,
        "model_name": "openrouter/free",
        "provider_id": openrouter_id,
        "agent_mode": "agent",
        "tool_mode": "auto",
        "tools": [],
    }
    print("4) streaming agent run...")
    t0 = time.monotonic()
    events = []          # (event_name, payload)
    terminal_ok = False
    with s.post(f"{args.base}/chat/conversations/{conv_id}/agent",
                json=payload, stream=True, timeout=(30, 600)) as resp:
        print("   http status:", resp.status_code)
        if resp.status_code != 200:
            body = resp.text[:2000]
            print("   ERROR BODY:", body)
            return 1
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or raw.startswith(":"):
                continue
            if raw.startswith("event: "):
                cur_name = raw[len("event: "):].strip()
                cur_data = ""
            elif raw.startswith("data: ") and cur_name:
                cur_data = raw[len("data: "):].strip()
                try:
                    payload_d = json.loads(cur_data)
                except Exception:
                    payload_d = {"raw": cur_data}
                events.append((cur_name, payload_d))
                if cur_name == "done":
                    terminal_ok = True
    elapsed = time.monotonic() - t0
    print(f"   stream done in {elapsed:.1f}s, events={len(events)}")

    # ---- TASK 8 checklist assertions on the SSE timeline ----
    names = [e for e, _ in events]
    fails = []

    # Group the checks by nature so a model-capability shortfall (the free model
    # giving up) is reported honestly rather than as a pipeline invariant failure.
    last_done = events[-1][1] if events and events[-1][0] == "done" else {}
    FINAL_STATE = last_done.get("state", "n/a")

    def _check_sys(cond, msg):
        """Invariant the runtime MUST uphold regardless of model capability."""
        print(("  [SYS  PASS] " if cond else "  [SYS  FAIL] ") + msg)
        if not cond:
            fails.append(msg)

    def _check_task(cond, msg):
        """Outcome that requires the model to genuinely complete the task."""
        print(("  [TASK PASS] " if cond else "  [TASK FAIL] ") + msg)
        if not cond:
            fails.append(msg)

    check = _check_sys
    print(f"   final run state: {FINAL_STATE}")

    check("agent_started" in names, "agent_started emitted exactly once")
    check(names.count("agent_started") == 1, "no duplicate agent_started")
    check(terminal_ok, "stream terminated with a done event")
    check(events[-1][0] == "done", "done is the final event")

    # final_response + completed only occur when the model actually completes
    # the task; openrouter/free often gives up (honest FAIL). Classified TASK.
    _check_task("final_response" in names, "final_response emitted before done")
    fr_done_order = True
    if "final_response" in names and "done" in names:
        fr_done_order = names.index("final_response") < names.index("done")
    _check_task(fr_done_order, "final_response precedes done")

    # The done event is always the last SSE event
    done_payload = events[-1][1] if events and events[-1][0] == "done" else {}
    _check_task("completed" in (done_payload.get("state") or ""), "final state == completed")
    _check_task(done_payload.get("tool_calls", -1) >= 1, "tools were executed (tool_calls>=1)")

    # Tool timeline: web_search executes, calculator executes, no RUNNING leftover
    tool_calls = [ (n, d) for n, d in events if n == "tool_call" ]
    terminators = [ (n, d) for n, d in events if n in ("tool_result", "tool_timeout", "tool_error") ]
    _check_task(len(tool_calls) >= 2, f"at least web_search + calculator called ({len(tool_calls)})")
    web_tool = any(d.get("tool") == "web_search" for _, d in tool_calls)
    calc_tool = any(d.get("tool") == "calculator" for _, d in tool_calls)
    _check_task(web_tool and calc_tool, "web_search AND calculator both executed")
    check(len(tool_calls) == len(terminators), "every tool_call has exactly one terminal event")

    running_states = [d.get("state") for _, d in events if d.get("state") == "running"]
    check(len(running_states) == 0, "no tool left RUNNING")

    # Verification ran before final response
    verify_idx = names.index("verification") if "verification" in names else -1
    verification_before_done = verify_idx >= 0 and (names.index("done") if "done" in names else 0) > verify_idx
    _check_task(verify_idx >= 0, "verification event present")
    _check_task(verification_before_done, "verification occurred before final response")

    # 5) Persisted agent-events (what a refreshed browser timeline loads)
    ev = s.get(f"{args.base}/chat/conversations/{conv_id}/agent-events", timeout=30)
    ev.raise_for_status()
    evdata = ev.json()
    evnames = [e["event_type"] for e in evdata.get("events", [])]
    runs = evdata.get("runs", [])
    check(len(evnames) > 0, "agent-events persisted for timeline")
    check(evnames.count("agent_started") == 1, "persisted agent_started exactly once")
    _check_task(
        "tool_result" in evnames or "tool_call" in evnames,
        "tool events persisted (requires the model to drive tools)",
    )
    _check_task(
        any(r.get("status") == "completed" for r in runs),
        "AgentRun status == completed (model-dependent; failed runs correctly persist 'failed')",
    )

    # 6) Conversation detail (what a refreshed browser shows): assistant final answer
    det = s.get(f"{args.base}/chat/conversations/{conv_id}", timeout=30)
    det.raise_for_status()
    msgs = det.json().get("messages", [])
    assistant_msgs = [m for m in msgs if m.get("role") == "assistant"]
    _check_task(len(assistant_msgs) >= 1, "assistant final response persisted")
    if assistant_msgs:
        _check_task(bool(assistant_msgs[0].get("content")), "final response content non-empty")
    else:
        _check_task(False, "final response content non-empty")

    # 7) Conversation list still served (sidebar not stuck: list endpoint healthy post-run)
    lst = s.get(f"{args.base}/chat/conversations", timeout=30)
    lst.raise_for_status()
    check(any(c["id"] == conv_id for c in lst.json()), "conversation present in list")

    print("\n=== SUMMARY ===")
    if fails:
        print(f"E2E OUTCOME ({len(fails)} unresolved):")
        for f in fails:
            print("  -", f)
        if FINAL_STATE != "completed":
            print(
                f"\nNOTE: final state was '{FINAL_STATE}'. The openrouter/free model "
                "often cannot complete this task (rate limits / capability), in which "
                "case the runtime CORRECTLY ends failed - not a fabricated success. "
                "The [SYS] invariant checks validate the runtime fixes; [TASK] checks "
                "require the model to genuinely finish."
            )
        return 1 if fails else 0
    print("ALL E2E CHECKS PASSED  (final state: %s)" % FINAL_STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())