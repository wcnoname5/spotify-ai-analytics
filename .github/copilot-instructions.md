# Copilot Instructions

## Project Scope
- This project analyzes Spotify listening history using AI agents and LangGraph.
- It is designed to run both locally and as a deployed application on **Streamlit Cloud**.
- Assume the project is run by a developer or used by end-users via the cloud.

## Python Environment
- Use `venv` for virtual environments.
- Use `uv` to manage and pin Python versions.
- The project's source code is in `src/`. Use absolute imports (e.g., `from spotify_agent...`, `from utils...`, `from app...`).
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
- Do not test Streamlit UI components (in `src/app/`).

## Agent Architecture
- The project contains a single agent.
- Agent logic lives in the `src/spotify_agent/` package.
- Separate concerns into individual files:
  - `tools.py`
  - `state.py` (state definitions)
  - `nodes.py`
  - `graph.py` (graph construction)
- Prefer LangGraph for agent orchestration.
- Define agent state explicitly using typed dictionaries or dataclasses in `state.py`.
- Avoid monolithic agent implementations.

## Coding Style
- Prefer clarity and inspectability over abstraction-heavy patterns.
- Favor synchronous code unless async is clearly required.
- Name tools, nodes, and graph components descriptively.
- Keep agent logic deterministic where possible.

## UI
- Streamlit is used for the interactive UI, supporting both local execution and Streamlit Cloud deployment.
- UI code lives in `src/app/`, not inside `spotify_agent/`.
- Agent modules must not depend on Streamlit or UI-related libraries.
- Use Plotly for interactive visualizations when needed.

## Git
- Write commit messages starting with one of the following prefixes:
  feat:, fix:, docs:, style:, refactor:, test:, chore:
