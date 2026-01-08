# Testing Guide

This document describes how to run and manage the testing suite for the Spotify AI Analytics project.

## Overview

The project uses `pytest` for all tests. Tests are categorized into three levels using custom markers:

- `unit`: Fast, isolated tests for tools and logic (no external services or graph).
- `integration`: Tests for multi-node graph flows and state transitions.
- `llm`: Tests that invoke real LLMs or external AI services.

## What we test

- class `DataLoader` functions: JSON loading, Polars dataframe transformation, and query/aggregation accuracy.
- `SpotifyQueryTools`: Direct tool method logic and LangChain compatibility.
- LangGraph Orchestration: Node transitions, out-of-scope input handling, and state preservation.

### Contract tests
- **Schema Validation**: Ensure all LLM outputs match defined Pydantic schemas (e.g., `IntentPlan`, `ToolPlan`).
- **Tool Compatibility**: Verify that analytical tools (e.g., `SpotifyQueryTools`) are compatible with LangChain's tool interface.
- **State Integrity**: Graph nodes must preserve or update the agent state correctly during transitions.

## What we do NOT test
- **LLM reasoning quality**: We don't automate the judgment of "how smart" the response is.
- **External service uptime**: We assume Spotify APIs or LLM providers are reachable (mocked in core tests).
- **Streamlit UI components**: Interaction with the dashboard and chat UI is excluded from automated testing.
- **Hallucination at semantic level**: Detecting subtle factual errors in LLM-generated narrative is out of scope.

## LLM usage in tests
- **Unit tests**: Strictly no LLM calls. Use mock objects or hardcoded responses.
- **Integration tests**: Use mocked LLM objects to simulate multi-step flows without cost or latency.
- **LLM tests (`llm` marker)**: Minimal set of connectivity tests and targeted E2E checks with live APIs.

## Prerequisites

Ensure you have the project dependencies and the local package installed:

```bash
uv sync
```

## Running Tests

### 1. Run All Tests
To run the entire test suite (excluding tests that require an LLM API key, unless configured):
```bash
uv run pytest
```

### 2. Run Only Unit Tests (Fast & Local)
These tests do not require internet access or API keys.
```bash
uv run pytest -m "unit"
```

### 3. Run Integration Tests
These test the LangGraph orchestration but typically use mocks for the LLM.
```bash
uv run pytest -m "integration"
```

### 4. Run LLM Tests
These require valid credentials (e.g., `GOOGLE_API_KEY` or `OPENAI_API_KEY` in your `.env` file).
```bash
uv run pytest -m "llm"
```

### 5. Filter by File
To run tests in a specific file:
```bash
uv run pytest tests/test_dataloader.py
```

## Test Structure

- `tests/`: Contains general logic and local unit tests.
- `tests/integration/`: Contains tests for the LangGraph agent, smoke tests, and LLM connectivity.

## Marker Configuration

Markers are defined in `pytest.ini`. If you add new tests, ensure you apply the appropriate decorator:

```python
import pytest

@pytest.mark.unit
def test_my_logic():
    pass
```

## Troubleshooting

- **Import Errors**: Ensure you have run `uv sync`. The tests rely on the package being installed in the environment to avoid `sys.path` manipulation.
- **API Failures**: If `llm` marked tests fail, verify your `.env` file contains the required API keys.
- **Windows Path Issues**: The project is configured to handle Windows paths correctly, but ensure you use `Path` from `pathlib` for any new test data generation.
