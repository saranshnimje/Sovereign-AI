"""
Regression tests for the Agentic Chat fix phase (tasks D–K).

  D/E/F  Tool-name alias canonicalization: model-emitting "websearch"/"search"/
         "webfetch" must resolve to canonical web_search/web_fetch BEFORE the
         registry lookup, permission check, and execution — and the canonical
         name must appear in lifecycle/UI events.
  G      Reasoner malformed-output recovery: prose-wrapped / fenced JSON is
         tolerated; a corrective retry rescues a genuinely malformed response.
  H      Reasoner persistent failure: after parse + corrective retry both fail,
         the run emits error + done and marks the agent FAILED — never left running.
  I      Tool lifecycle invariant: every tool_call has exactly one terminal
         event (tool_result / tool_timeout), even when execution raises.
  J      Successful stream: final_response then done(state=completed).
  K      Failed stream: error then done(state=failed).
"""
import json
from unittest.mock import MagicMock

import pytest

from services.agent.runtime import AgentRuntime, canonicalize_tool_name
from services.agent_state import AgentStateMachine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evt(event: str) -> tuple[str, dict | None]:
    """Parse an SSE event string -> (event_name, payload)."""
    name = None
    data = None
    for line in event.split("\n"):
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                data = None
    return name, data


def _collect(events: list[str], name: str) -> list[dict]:
    out: list[dict] = []
    for e in events:
        n, d = _evt(e)
        if n == name and d is not None:
            out.append(d)
    return out


def _collect_raw(events: list[str], name: str) -> list[str]:
    return [e for e in events if e.startswith(f"event: {name}")]


def _sink_execute(*, succeed: bool = True, raise_exc: bool = False):
    """Build a _execute_tool replacement that records the tool name passed in."""
    calls = []
    duration_ms = {"n": 3}

    async def execute(tool_name, tool_input, **kwargs):
        calls.append((tool_name, tool_input))
        if raise_exc:
            raise RuntimeError("boom")
        if not succeed:
            return {"error": "non-transient failure", "failure_type": "TOOL_ERROR"}
        return {"result": "ok", "duration_ms": duration_ms["n"]}

    return execute, calls


def _runner(responders, *, tool_names=None):
    """Build AgentRuntime + llm pairing.

    responders: dict mapping a system-prompt substring -> payload (dict) or
    callable(per_key_call_index, global_call_index). Each responder key gets its
    OWN monotonically increasing index so a REASONER lambda sees 1,2,3… no matter
    how many UNDERSTAND/PLANNER calls the runtime makes first.
    """
    counters = {key: {"n": 0} for key in responders}
    global_n = {"n": 0}

    async def mock_chat(**kwargs):
        global_n["n"] += 1
        messages = kwargs.get("messages", [])
        system = (messages[0].content if messages else "") or ""
        for key, payload in responders.items():
            if key.lower() in system.lower():
                counters[key]["n"] += 1
                if callable(payload):
                    result = payload(counters[key]["n"], global_n["n"])
                    # Strings are delivered verbatim (prose / garbage / JSON text);
                    # dicts are JSON-encoded. Never double-encode a string.
                    content = result if isinstance(result, str) else json.dumps(result)
                    return MagicMock(content=content)
                return MagicMock(content=json.dumps(payload))
        return MagicMock(content="not valid json at all")

    llm = MagicMock()
    llm.chat = mock_chat
    runtime = AgentRuntime()
    return runtime, llm


# ---------------------------------------------------------------------------
# D / E / F — Tool-name alias canonicalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,canonical", [
    ("websearch", "web_search"),
    ("web-search", "web_search"),
    ("search", "web_search"),
    ("webfetch", "web_fetch"),
    ("web-fetch", "web_fetch"),
    ("WebSearch", "web_search"),
    ("  web_search  ", "web_search"),
    ("google", "web_search"),
    ("google_search", "web_search"),
    ("bing", "web_search"),
    ("duckduckgo", "web_search"),
    ("fetch", "web_fetch"),
    ("fetch_url", "web_fetch"),
])
def test_canonicalize_tool_name(alias, canonical):
    assert canonicalize_tool_name(alias) == canonical


@pytest.mark.asyncio
async def test_reasoner_alias_routes_to_canonical_web_search():
    """Reasoner proposes 'websearch' → runtime executes canonical 'web_search'."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "search web", "tool": "web_search", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "use tool",
            "next_action": {"tool": "websearch", "input": {"query": "q"}, "reasoning": "need info"},
        } if n == 1 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None,
            "answer": "Result obtained.",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_search"],
        tool_descriptions="web_search: search the web", agent_state=agent,
    ):
        events.append(event)

    # The alias was canonicalized before execution/lookup.
    assert len(calls) == 1
    assert calls[0][0] == "web_search", f"expected canonical web_search, got {calls[0][0]}"

    # Lifecycle/UI events carry the canonical name only.
    tool_call_payloads = _collect(events, "tool_call")
    assert len(tool_call_payloads) == 1
    assert tool_call_payloads[0]["tool"] == "web_search"
    assert not any("websearch" in e for e in events)

    # Run completed properly.
    done = _collect(events, "done")
    assert len(done) == 1
    assert done[0]["state"] == "completed"
    assert _collect(events, "final_response")


@pytest.mark.asyncio
async def test_reasoner_search_alias_routes_to_web_search():
    """Reasoner proposes 'search' → canonical 'web_search' executes."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "search", "tool": "web_search", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "go",
            "next_action": {"tool": "search", "input": {"query": "q"}, "reasoning": "r"},
        } if n == 1 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "ok",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_search"],
        tool_descriptions="web_search: search", agent_state=agent,
    ):
        events.append(event)

    assert len(calls) == 1 and calls[0][0] == "web_search"
    payloads = _collect(events, "tool_call")
    assert payloads[0]["tool"] == "web_search"
    assert _collect(events, "done")[0]["state"] == "completed"


@pytest.mark.asyncio
async def test_reasoner_webfetch_alias_routes_to_web_fetch():
    """Reasoner proposes 'webfetch' → canonical 'web_fetch' executes."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "fetch", "tool": "web_fetch", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "go",
            "next_action": {"tool": "webfetch", "input": {"url": "https://x"}, "reasoning": "r"},
        } if n == 1 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "ok",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_fetch"],
        tool_descriptions="web_fetch: fetch a url", agent_state=agent,
    ):
        events.append(event)

    assert len(calls) == 1 and calls[0][0] == "web_fetch"
    payloads = _collect(events, "tool_call")
    assert payloads[0]["tool"] == "web_fetch"
    assert _collect(events, "done")[0]["state"] == "completed"


# ---------------------------------------------------------------------------
# G — Malformed reasoner output recovery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoner_prose_wrapped_json_is_recovered():
    """Reasoner wraps JSON in prose → parse_llm_json still extracts it; tool runs."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ((
            "Here is my reasoning for the next move. "
            '{"decision": "CONTINUE", "reason": "compute", '
            '"next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"}}'
            " That should solve it."
        ) if n == 1 else (
            "Great, the tool gave us what we need: "
            '{"decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": null, "answer": "2"}'
            " Final."
        )),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    assert len(calls) == 1 and calls[0][0] == "calculator"
    assert _collect(events, "done")[0]["state"] == "completed"
    # The malformed-but-recoverable reasoner output never triggered a FAIL.
    assert not _collect_raw(events, "error")


@pytest.mark.asyncio
async def test_reasoner_corrective_retry_rescues_bad_json():
    """First reasoner response unparseable → corrective retry (valid) rescues the run."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        # Call 1 (normal REASONER): unparseable garbage.
        # Call 2 (corrective retry): valid JSON rescues the run.
        # Call 3+ : ANSWER_DIRECTLY so the loop terminates cleanly.
        "REASONER": lambda n, g: (
            "I think we should maybe do something but I won't produce valid JSON."
        ) if n == 1 else ({
            "decision": "CONTINUE", "reason": "compute",
            "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"},
        } if n == 2 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "2",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    # The corrective retry produced valid output → tool executed → completed.
    assert len(calls) == 1 and calls[0][0] == "calculator"
    assert agent.state.value == "completed", agent.state.value
    assert _collect(events, "done")[0]["state"] == "completed"


# ---------------------------------------------------------------------------
# H — Persistent reasoner failure marks the run FAILED (never left running)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoner_persistent_failure_emits_error_and_marks_failed():
    """Parse + corrective retry both fail after a tool already ran → error + done(failed)."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        # Call 1 = valid CONTINUE (a tool runs, tool_call_count > 0).
        # Call >= 2 = garbage (both normal AND corrective retry unparseable).
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "compute",
            "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"},
        } if n == 1 else "This is not JSON. Just rambling text with no structure."),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    assert _collect_raw(events, "error"), "expected an error event"
    done = _collect(events, "done")
    assert len(done) == 1
    assert done[0]["state"] == "failed"
    assert agent.state.value == "failed"
    # Exactly one tool ran (the successful CONTINUE one); the recovery failure
    # did not leave the agent 'running'.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reasoner_garbage_after_evidence_routes_to_verify_and_completes():
    """2+ tools executed then reasoner goes unparseable → VERIFY can still finish the run.

    This is the convergence guard for real-world free models (openrouter/free)
    that loop on tools and never emit a terminal decision: after real evidence
    was gathered (>=2 tool calls), a reasoner hiccup must NOT destroy the run.
    The verifier independently judges the acceptance criteria.
    """
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "step a", "tool": "calculator", "success_criteria": "ok"},
                       {"id": 2, "description": "step b", "tool": "calculator", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "go",
            "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"},
        } if n < 3 else "This is not JSON. The model lost coherence after many tool calls."),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    # TWO tools ran (>=2 = real evidence) before the reasoner went garbage;
    # the run then routed to VERIFY, the verifier approved, and it COMPLETED.
    assert len(calls) == 2
    assert agent.state.value == "completed", agent.state.value
    assert _collect(events, "done")[0]["state"] == "completed"
    assert _collect_raw(events, "verification")


# ---------------------------------------------------------------------------
# L — Native function-call token recovery (no JSON at all)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoner_gemma_native_tool_call_is_recovered():
    """<|tool_call_start|>web_search(query='...')<|tool_call_end|> → executes web_search."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "search", "tool": "web_search", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: (
            "I need to research this online.\n"
            "<|tool_call_start|>web_search(query='Superposition theorem', source='duckduckgo')<|tool_call_end|>"
        ) if n == 1 else ({
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "ok",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_search"],
        tool_descriptions="web_search: search", agent_state=agent,
    ):
        events.append(event)

    # The native token format was decoded into a real tool call.
    assert len(calls) == 1 and calls[0][0] == "web_search"
    assert calls[0][1].get("query") == "Superposition theorem"
    assert _collect(events, "done")[0]["state"] == "completed"


@pytest.mark.asyncio
async def test_reasoner_qwen_xml_tool_call_is_recovered():
    """<tool_call>web_search<arg_key>query</arg_key>...</tool_call> → executes web_search."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "search", "tool": "web_search", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: (
            "<tool_call>web_search<arg_key>query</arg_key>"
            "<arg_value>Superposition theorem</arg_value></tool_call>"
        ) if n == 1 else ({
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "ok",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_search"],
        tool_descriptions="web_search: search", agent_state=agent,
    ):
        events.append(event)

    assert len(calls) == 1 and calls[0][0] == "web_search"
    assert calls[0][1].get("query") == "Superposition theorem"
    assert _collect(events, "done")[0]["state"] == "completed"


@pytest.mark.asyncio
async def test_reasoner_schema_drift_is_normalized():
    """Model sends 'reasoning' (not 'reason') + next_action as a LIST → still validates."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            # Common model drift: 'reasoning' instead of 'reason', and a LIST of
            # parallel tool calls instead of a single next_action object.
            "decision": "CONTINUE",
            "reasoning": "compute the sum",
            "next_action": [
                {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "first"},
                {"tool": "calculator", "input": {"expression": "2+2"}, "reasoning": "second"},
            ],
        } if n == 1 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "2",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    # First action in the list was chosen and executed; the run completed.
    assert len(calls) == 1 and calls[0][0] == "calculator"
    assert calls[0][1].get("expression") == "1+1"
    assert _collect(events, "done")[0]["state"] == "completed"


@pytest.mark.asyncio
async def test_reasoner_bracketed_native_list_with_alias_is_recovered():
    """<|tool_call_start|>[google(...), google(...)]<|tool_call_end|> → first call, canonicalized."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "search", "tool": "web_search", "success_criteria": "ok"}],
        },
        # Real-world shape from the live E2E: a bracketed LIST of parallel calls
        # using a non-registry engine name 'google'.
        "REASONER": lambda n, g: (
            "<|tool_call_start|>[google(query='Superposition theorem'), "
            "google(query='numerical example two source circuit')]<|tool_call_end|>"
        ) if n == 1 else ({
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "ok",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["web_search"],
        tool_descriptions="web_search: search", agent_state=agent,
    ):
        events.append(event)

    # Only the FIRST call of the bracketed list is executed, and 'google' was
    # canonicalized to the registry name 'web_search'.
    assert len(calls) == 1 and calls[0][0] == "web_search"
    assert calls[0][1].get("query") == "Superposition theorem"
    assert _collect(events, "done")[0]["state"] == "completed"


def test_extract_native_tool_call_bracket_list():
    """Unit-level: extract_native_tool_call returns the first call of a bracket list."""
    from services.agent.schemas import extract_native_tool_call
    tc = extract_native_tool_call(
        "<|tool_call_start|>[google(query='a'), web_fetch(url='b')]<|tool_call_end|>"
    )
    assert tc and tc["tool"] == "google"
    assert tc["input"]["query"] == "a"


def test_extract_native_tool_call_single():
    """Unit-level: single-call Gemma format with quoted args."""
    from services.agent.schemas import extract_native_tool_call
    tc = extract_native_tool_call(
        "<|tool_call_start|>web_search(query='Superposition theorem', source='duckduckgo')<|tool_call_end|>"
    )
    assert tc and tc["tool"] == "web_search"
    assert tc["input"]["query"] == "Superposition theorem"
    assert tc["input"]["source"] == "duckduckgo"


# ---------------------------------------------------------------------------
# I — Exactly one terminal event per tool_call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_every_tool_call_has_exactly_one_terminal_event():
    """A successful tool_call is followed by exactly one tool_result terminal."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        "REASONER": lambda n, g: ({
            "decision": "CONTINUE", "reason": "compute",
            "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"},
        } if n == 1 else {
            "decision": "ANSWER_DIRECTLY", "reason": "done", "next_action": None, "answer": "2",
        }),
        "VERIFIER": {"verified": True, "confidence": 0.9, "criteria": [], "missing": [], "unsupported_claims": []},
    })
    execute, calls = _sink_execute(succeed=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    tool_calls = _collect_raw(events, "tool_call")
    terminals = _collect_raw(events, "tool_result") + _collect_raw(events, "tool_timeout") + _collect_raw(events, "tool_error")
    assert len(tool_calls) == len(terminals) == 1, \
        f"Expected 1 tool_call with exactly 1 terminal, got {len(tool_calls)} calls / {len(terminals)} terminals"

    _, payload = _evt(terminals[0])
    assert payload["status"] in ("success", "failed", "error")


@pytest.mark.asyncio
async def test_exception_safety_net_emits_terminal_error_result():
    """If _execute_tool raises, a terminal tool_result(status=error) is still emitted."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "calc", "tool": "calculator", "success_criteria": "ok"}],
        },
        "REASONER": {
            "decision": "CONTINUE", "reason": "compute",
            "next_action": {"tool": "calculator", "input": {"expression": "1+1"}, "reasoning": "r"},
        },
    })
    execute, calls = _sink_execute(raise_exc=True)
    runtime._execute_tool = execute

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=["calculator"],
        tool_descriptions="calculator: math", agent_state=agent,
    ):
        events.append(event)

    tool_calls = _collect_raw(events, "tool_call")
    terminals = _collect_raw(events, "tool_result") + _collect_raw(events, "tool_timeout") + _collect_raw(events, "tool_error")
    assert len(tool_calls) == 1 and len(terminals) == 1
    _, payload = _evt(terminals[0])
    assert payload["status"] == "error"
    # The run terminated (failed), never left running.
    assert agent.state.value == "failed"


# ---------------------------------------------------------------------------
# J / K — Successful vs failed stream terminal states
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_stream_ends_completed_with_final_response():
    """COMPLETE + verifier-approved → final_response then done(state=completed)."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "step", "tool": None, "success_criteria": "done"}],
        },
        "REASONER": {
            "decision": "COMPLETE", "reason": "goal achieved", "next_action": None,
        },
        "VERIFIER": {
            "verified": True, "confidence": 0.95, "criteria": [], "missing": [], "unsupported_claims": [],
        },
    })

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=[], tool_descriptions="",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value == "completed"
    done = _collect(events, "done")
    assert len(done) == 1
    assert done[0]["state"] == "completed"
    final = _collect(events, "final_response")
    assert final and final[0]["content"]
    # Stream terminated — exactly one done, no lingering running.
    assert len(_collect_raw(events, "done")) == 1


@pytest.mark.asyncio
async def test_failed_stream_ends_failed_with_error_then_done():
    """Reasoner FAIL → error then done(state=failed)."""
    runtime, llm = _runner({
        "PLANNER": {
            "goal": "test", "acceptance_criteria": ["done"],
            "steps": [{"id": 1, "description": "step", "tool": None, "success_criteria": "done"}],
        },
        "REASONER": {"decision": "FAIL", "reason": "cannot resolve", "next_action": None},
    })

    agent = AgentStateMachine()
    events = []
    async for event in runtime.run(
        goal="test", user_id="u1", user_role="admin", model="test",
        llm=llm, db=MagicMock(), tool_names=[], tool_descriptions="",
        agent_state=agent,
    ):
        events.append(event)

    assert agent.state.value == "failed"
    assert _collect_raw(events, "error"), "expected an error event"
    done = _collect(events, "done")
    assert len(done) == 1
    assert done[0]["state"] == "failed"
    assert len(_collect_raw(events, "done")) == 1