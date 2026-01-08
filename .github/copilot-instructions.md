# Copilot Instructions

## Project Scope
- This is a local-only Python project for experimenting with AI agents and LangGraph.
- Do NOT suggest cloud deployment, Docker, Kubernetes, CI/CD pipelines, or remote services unless explicitly requested.
- Assume the project is run locally by a single developer.

## Python Environment
- Use `venv` for virtual environments.
- Use `uv` to manage and pin Python versions.
- The project is structured as a package with `src/` as the root. Use absolute imports (e.g., `from spotify_agent...` or `from utils...`).
- Do not use `sys.path` hacks in tests or scripts; assume the package is installed in the environment.
- Do not suggest conda, poetry, or pipenv.

## Testing
- Use `pytest` as the testing framework for all Python tests.
- Distinguish tests using markers defined in `pytest.ini`:
  - `@pytest.mark.unit`: Fast, isolated tests for tools and logic (no external services).
  - `@pytest.mark.integration`: Tests for multi-node graph flows and state transitions.
  - `@pytest.mark.llm`: Tests that invoke real LLMs or external AI services.
- Mock LLM calls and external APIs in `unit` and most `integration` tests.
- Focus tests on tools, state transitions, and graph logic.
- Do not test Streamlit UI components.

## Agent Architecture
- The project contains a single agent.
- Agent logic lives in the `agent/` package.
- Separate concerns into individual files (not folders):
  - tools
  - state definitions
  - nodes
  - graph construction
- Prefer LangGraph for agent orchestration.
- Define agent state explicitly using typed dictionaries or dataclasses.
- Avoid monolithic agent implementations.

## Coding Style
- Prefer clarity and inspectability over abstraction-heavy patterns.
- Favor synchronous code unless async is clearly required.
- Name tools, nodes, and graph components descriptively.
- Keep agent logic deterministic where possible.

## UI
- Streamlit is used only for a minimal local UI.
- UI code lives in `ui/`, not inside `agent/`.
- Agent modules must not depend on Streamlit or UI-related libraries.
- Use Plotly for interactive visualizations when needed.

## Git
- Write commit messages starting with one of the following prefixes:
  feat:, fix:, docs:, style:, refactor:, test:, chore:
