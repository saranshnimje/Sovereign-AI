"""
Dead code removal tests — verify AgentService is dead code and
can be safely removed or deprecated.

AgentService in agent_service.py is referenced only in tests/unit/test_tools.py
for _parse_action. No router or service imports it in production code.
"""
import pytest
import importlib
import sys


# ------------------------------------------------------------------
# 1. AgentService import tests
# ------------------------------------------------------------------
class TestAgentServiceDeadCode:
    """Tests that AgentService is dead code."""

    def test_agent_service_exists(self):
        """AgentService module should exist."""
        try:
            import services.agent_service
            assert hasattr(services.agent_service, 'AgentService')
        except ImportError:
            pytest.skip("AgentService module not found")

    def test_agent_service_not_imported_by_routers(self):
        """AgentService should not be imported by any router."""
        import os
        router_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'routers')
        if not os.path.isdir(router_dir):
            pytest.skip("Routers directory not found")

        for filename in os.listdir(router_dir):
            if filename.endswith('.py') and filename != '__init__.py':
                filepath = os.path.join(router_dir, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                    # AgentService should not be imported in routers
                    assert 'AgentService' not in content or 'agent_service' not in content, \
                        f"AgentService found in router: {filename}"

    def test_agent_service_not_imported_by_services(self):
        """AgentService should not be imported by other services."""
        import os
        services_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'services')
        if not os.path.isdir(services_dir):
            pytest.skip("Services directory not found")

        for filename in os.listdir(services_dir):
            if filename.endswith('.py') and filename != '__init__.py' and filename != 'agent_service.py':
                filepath = os.path.join(services_dir, filename)
                with open(filepath, 'r') as f:
                    content = f.read()
                    # AgentService should not be imported in other services
                    assert 'AgentService' not in content, \
                        f"AgentService found in service: {filename}"

    def test_agent_runtime_is_canonical(self):
        """AgentRuntime should be the canonical agent loop."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, 'run')

    def test_agent_service_only_in_tests(self):
        """AgentService should only be imported in test files (not used in production)."""
        import os
        import re
        tests_dir = os.path.join(os.path.dirname(__file__), '..', '..')
        if not os.path.isdir(tests_dir):
            pytest.skip("Tests directory not found")

        # Look for actual imports of AgentService (not just string mentions in comments)
        import_pattern = re.compile(r'(?:from\s+.*agent_service\s+import|import\s+.*agent_service)')
        found_in = []
        for root, dirs, files in os.walk(tests_dir):
            for filename in files:
                if filename.endswith('.py'):
                    filepath = os.path.join(root, filename)
                    if 'agent_service.py' in filepath or 'test_dead_code' in filepath:
                        continue
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for line in f:
                                if import_pattern.search(line):
                                    found_in.append(filepath)
                                    break
                    except (UnicodeDecodeError, OSError):
                        continue

        # Should only be in test_tools.py
        for filepath in found_in:
            assert 'test_tools.py' in filepath, \
                f"AgentService imported outside tests: {filepath}"


# ------------------------------------------------------------------
# 2. AgentRuntime canonical tests
# ------------------------------------------------------------------
class TestAgentRuntimeCanonical:
    """Tests that AgentRuntime is the only canonical agent loop."""

    def test_agent_runtime_has_run_method(self):
        """AgentRuntime should have run method."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, 'run')
        assert callable(getattr(AgentRuntime, 'run'))

    def test_agent_runtime_has_planner(self):
        """AgentRuntime should have planner."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, '_create_plan')

    def test_agent_runtime_has_reasoner(self):
        """AgentRuntime should have reasoner."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, '_decide')

    def test_agent_runtime_has_verifier(self):
        """AgentRuntime should have verifier."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, '_verify')

    def test_agent_runtime_has_tool_execution(self):
        """AgentRuntime should have tool execution."""
        from services.agent.runtime import AgentRuntime
        assert hasattr(AgentRuntime, '_execute_tool')
