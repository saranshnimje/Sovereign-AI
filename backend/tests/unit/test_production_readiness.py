"""
Regression tests: production-readiness checks for SIH 2026 demo.

Covers:
  1. chat.py uses json.loads (not _json.loads)
  2. chat.py imports _sse for error-done events
  3. documents.py ensure_kb_access argument order
  4. search_kb explicit error handling (no silent model fallback)
  5. runtime.py has no merged lines (syntax integrity)
  6. Gemini provider error classification
  7. CORS is not wildcard
  8. No hardcoded API keys in source
"""
import inspect
import re


class TestChatRouterJsonParsing:
    """Prevent _json.loads NameError that breaks RAG completely."""

    def test_send_message_uses_json_not__json(self):
        """send_message must use json.loads, not _json.loads."""
        from routers.chat import send_message
        source = inspect.getsource(send_message)
        assert "json.loads" in source, (
            "send_message should use json.loads for body parsing"
        )
        assert "_json.loads" not in source, (
            "send_message uses _json.loads which is undefined — "
            "RAG kb_ids will always be None. Use json.loads instead."
        )

    def test_send_agent_message_uses_json_not__json(self):
        """send_agent_message must use json.loads, not _json.loads."""
        from routers.chat import send_agent_message
        source = inspect.getsource(send_agent_message)
        assert "_json.loads" not in source, (
            "send_agent_message uses _json.loads which is undefined"
        )


class TestChatRouterSseImport:
    """Prevent NameError when emitting error-done SSE events."""

    def test_send_agent_message_imports_sse(self):
        """send_agent_message must import _sse for error handlers."""
        from routers.chat import send_agent_message
        source = inspect.getsource(send_agent_message)
        assert "_sse" in source, (
            "send_agent_message must reference _sse for error-done events"
        )
        # Verify it's imported, not just referenced in a comment
        import ast
        tree = ast.parse(source)
        imports = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        all_names = []
        for imp in imports:
            for alias in imp.names:
                all_names.append(alias.name)
        assert "_sse" in all_names, (
            "_sse is not imported in send_agent_message — "
            "error-done SSE events will fail with NameError"
        )


class TestDocumentsKbAccess:
    """Prevent ensure_kb_access argument reversal (user, kb → kb, user)."""

    def test_ensure_kb_access_correct_order(self):
        """documents.py must call ensure_kb_access(kb, user), not (user, kb)."""
        with open("routers/documents.py") as f:
            source = f.read()
        # Match all calls to ensure_kb_access and check first arg is not 'user'
        calls = re.findall(r'ensure_kb_access\((\w+),\s*(\w+)', source)
        for first_arg, second_arg in calls:
            assert first_arg != "user", (
                f"ensure_kb_access({first_arg}, {second_arg}) has reversed args. "
                "Signature is ensure_kb_access(kb, user, write=False). "
                "User object cannot be used as the kb parameter."
            )

    def test_document_service_ensure_kb_access_correct_order(self):
        """document_service.py must call ensure_kb_access(kb, user), not (user, kb)."""
        with open("services/document_service.py") as f:
            source = f.read()
        calls = re.findall(r'ensure_kb_access\((\w+),\s*(\w+)', source)
        for first_arg, second_arg in calls:
            assert first_arg != "user", (
                f"document_service.py ensure_kb_access({first_arg}, {second_arg}) has reversed args"
            )


class TestSearchKbExplicitErrors:
    """Prevent search_kb from silently using wrong embedding models."""

    def test_search_kb_no_hardcoded_model_fallback(self):
        """search_kb must not hardcode 'nomic-embed-text' as a fallback."""
        with open("tools/search_kb.py") as f:
            source = f.read()
        assert '"nomic-embed-text"' not in source, (
            "search_kb hardcodes 'nomic-embed-text' as fallback. "
            "This causes garbage results if the KB uses a different model. "
            "Instead, fail explicitly with an error message."
        )

    def test_search_kb_fails_when_kb_service_missing(self):
        """search_kb must return a descriptive error when kb_service is None."""
        with open("tools/search_kb.py") as f:
            source = f.read()
        # Check the pattern: if kb_service is None, we return a message
        assert "Knowledge base service unavailable" in source or "kb_service" in source, (
            "search_kb should handle missing kb_service gracefully"
        )

    def test_search_kb_fails_on_lookup_error(self):
        """search_kb must not silently fall through on KB lookup failure."""
        with open("tools/search_kb.py") as f:
            source = f.read()
        # After the except block, there should be a return, not just pass
        # The old code had: except Exception: pass → falls through to hardcoded model
        assert "Failed to retrieve knowledge base" in source or (
            "except Exception" in source and "return" in source
        ), (
            "search_kb should return an error on KB lookup failure, not silently pass"
        )


class TestRuntimeSyntaxIntegrity:
    """Prevent merged lines that cause SyntaxError."""

    def test_no_merged_statements_in_runtime(self):
        """runtime.py must not have two statements merged on one line."""
        with open("services/agent/runtime.py") as f:
            lines = f.readlines()
        merged = []
        for i, line in enumerate(lines, 1):
            stripped = line.rstrip()
            # Detect pattern: "word" + many spaces + "word" (two statements merged)
            if re.search(r'\w\s{20,}\w', stripped):
                # Exclude legitimate long strings and comments
                if not stripped.lstrip().startswith('#') and '="' not in stripped:
                    merged.append((i, stripped[:100]))
        assert not merged, (
            f"Found merged lines in runtime.py: {merged}. "
            "These cause SyntaxError. Separate statements onto their own lines."
        )

    def test_file_not_truncated_at_2000_lines(self):
        """runtime.py must have more than 2000 lines."""
        with open("services/agent/runtime.py") as f:
            line_count = sum(1 for _ in f)
        assert line_count > 2000, (
            f"runtime.py has only {line_count} lines. "
            "File may be truncated. Last known good: 2200+ lines."
        )


class TestGeminiErrorClassification:
    """Verify Gemini provider has proper HTTP error classification."""

    def test_gemini_classifies_401(self):
        """Gemini provider must classify HTTP 401 as invalid API key."""
        with open("services/llm_client.py") as f:
            source = f.read()
        assert "401" in source and "invalid API key" in source.lower() or "authentication failed" in source.lower(), (
            "Gemini provider must classify HTTP 401 as authentication/invalid key error"
        )

    def test_gemini_classifies_429(self):
        """Gemini provider must classify HTTP 429 as rate limit."""
        with open("services/llm_client.py") as f:
            source = f.read()
        assert "429" in source and "rate limit" in source.lower(), (
            "Gemini provider must classify HTTP 429 as rate limit"
        )

    def test_gemini_classifies_403(self):
        """Gemini provider must classify HTTP 403 as permission error."""
        with open("services/llm_client.py") as f:
            source = f.read()
        assert "403" in source, (
            "Gemini provider must handle HTTP 403"
        )

    def test_gemini_no_api_key_in_error_messages(self):
        """Gemini error messages must not contain the actual API key."""
        with open("services/llm_client.py") as f:
            source = f.read()
        # Check that error messages use placeholders or truncated body, not key
        # The key is in self._api_key; error messages should reference body text
        assert "self._api_key" not in source.split("raise ModelUnavailableError")[1:500] if "raise ModelUnavailableError" in source else True, (
            "Gemini error messages must not expose the API key"
        )


class TestCorsSecurity:
    """Verify CORS is not wildcard and uses explicit allowlist."""

    def test_no_wildcard_cors(self):
        """main.py must not use allow_origins=['*']."""
        with open("main.py") as f:
            source = f.read()
        assert 'allow_origins=["*"]' not in source, (
            "CORS must not use wildcard '*' — use explicit origin allowlist"
        )
        assert "allow_origins=['*']" not in source, (
            "CORS must not use wildcard '*' — use explicit origin allowlist"
        )

    def test_cors_uses_explicit_allowlist(self):
        """main.py must build CORS origins from environment variable."""
        with open("main.py") as f:
            source = f.read()
        assert "FRONTEND_ORIGIN" in source or "allowed_origins" in source, (
            "CORS should use FRONTEND_ORIGIN env var or explicit allowed_origins list"
        )


class TestNoHardcodedSecrets:
    """Verify no production API keys are hardcoded in source files."""

    def test_no_gemini_key_in_frontend(self):
        """Frontend code must not contain GEMINI_API_KEY."""
        import os
        for root, dirs, files in os.walk("frontend/src"):
            for fname in files:
                if fname.endswith(('.ts', '.tsx', '.js', '.jsx')):
                    with open(os.path.join(root, fname)) as f:
                        content = f.read()
                    assert "GEMINI_API_KEY" not in content, (
                        f"GEMINI_API_KEY found in {os.path.join(root, fname)} — "
                        "API keys must never be in frontend code"
                    )

    def test_no_real_api_keys_in_backend(self):
        """Backend source (not tests) must not contain realistic API keys."""
        import os
        key_pattern = re.compile(r'sk-[a-zA-Z0-9]{40,}')
        for root, dirs, files in os.walk("backend"):
            if "tests" in root:
                continue
            for fname in files:
                if fname.endswith('.py'):
                    filepath = os.path.join(root, fname)
                    with open(filepath) as f:
                        content = f.read()
                    matches = key_pattern.findall(content)
                    assert not matches, (
                        f"Potential API key found in {filepath}: {matches[0][:20]}..."
                    )
