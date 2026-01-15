# Spotify AI Analytics Agent

## Overview

This project provides a locally runnable Python application for analyzing personalized Spotify streaming history JSON files.

It includes an LLM-powered chatbot that parses user intent from natural language inputs, calling structured data analysis tools, and generates responses based on retrieved data. 

It also features an interactive dashboard that visualizes and summarizes top artists/tracks, and temporal patterns.

## User Interface

The application uses `Streamlit` as a unified interface, displaying two primary modes:
- **Chatbot Page**: Interact with an AI agent using natural language to query your history or get music recommendations.
- **Dashboard Page**: View interactive trends, top artists, and listening patterns through high-fidelity charts.

For setup and execution details, see the [How to Run](#how-to-run) section.

## System Architecture
The system is built on a modular architecture that separates data ingestion, computational logic, and AI orchestration.

1. **DataLoader (`data_loader.py`)**: Responsible for file discovery, JSON parsing, and staged validation. It focuses strictly on data preparation and schema enforcement, exposing clean `polars.DataFrame` structures for analysis.
2. **Analysis Core (`analysis_functions.py`)**: A "pure" functional layer containing all computational logic. It is decoupled from both data storage and UI, accepting DataFrames as input and returning structured analytics for both the Dashboard and the Agent.
3. **AI Agent (`tools.py` & `graph.py`)**: Orchestrates multi-step reasoning using **LangGraph**. It wraps the Analysis Core into structured tools, allowing the LLM to query and synthesize data into natural language responses.
4. **Dashboard**: Provides a visual layer using `Plotly` and `Streamlit` to render interactive charts based on metrics derived from the Analysis Core.

```mermaid
flowchart TD
    %% Node Definitions
    
    subgraph UI ["User Interface (Streamlit)"]
        Chat["LLM Chatbot Interface"]
        Dash["Interactive Dashboard"]
    end

    JSON[("Spotify History<br/>(JSON Files)")]
    JSON@{shape: docs}
    
    subgraph Data ["Data Layer"]
        DL[("DataLoader")]
        AF["analysis_functions.py"]
    end
    
    %% Flows based on drawing
    JSON -->|load & validate| DL
    DL <-->|Query| AF
        
    AF ===>|provide DataFrame| UI

    %% Styling 
    style JSON fill:#fa29,stroke:#333,stroke-width:2px,size:10S0px
    style UI fill:#285
    %% style Logic fill:#f9f,stroke:#333,stroke-width:2px
    style Data fill:#bbf,stroke:#333,stroke-width:2px
    %% style LLM fill:#dfd,stroke:#333,stroke-width:2px
```

### Data Pipeline & Analysis Logic
The project implements a strict separation between data state, computational logic, and orchestration:
- **State Management**: `SpotifyDataLoader` handles the I/O and schema enforcement using `Polars` and `Pydantic`.
- **Functional Analysis**: Centralized in `analysis_functions.py`, offering a clean, class-independent endpoint for both the Dashboard and the AI Agent.
- **Tool Orchestration**: `SpotifyQueryTools` in `tools.py` acts as the bridge, translating LLM intents into specific calls to the Analysis Core while managing data truncation for context windows.

### Visualization & Dashboard
The dashboard offers a no-code way to explore your data through interactive visualizations.
- **Interactive Charts**: Powered by `Plotly` for zooming, filtering, and detailed tooltips.
- **Track Insights**: Deep dives into your most-played tracks, artists, and albums.
- **Time Analysis**: Specialized views for tracking listening habits over days, months, and years.

### LLM Chatbot & Tooling
The chatbot is built using **LangGraph**, orchestrating a specialized three-stage process to ensure accurate data retrieval and high-quality conversation.

```mermaid
graph TD
    subgraph Tooling [SpotifyQueryTools]
        DL[(DataLoader)]
    end

    A([User Input]) --> Intent[Intent Parser]
    Intent -->|Parse Intent Type| C{Intent Type}
    D[Data Fetch] <-->|tool calls| Tooling
    C -->|factual_query| D
    C -->|insight_analysis| D
    C -->|recommendation| D
    C -->|other| E([Direct Response])
    D --> F[Analyst]
    F --> G([Final Response])
    E --> G

style Intent fill: #7f68,stroke:#333,stroke-width:3px
style D fill: #5bf,stroke:#333,stroke-width:2px
style F fill: #1caa,stroke:#333,stroke-width:2px
style Tooling fill: #f9f
```

#### Components and Nodes

- **Intent Parser**: Classifies user requests into categories: `factual_query`, `insight_analysis`, or `recommendation` to define the execution strategy.
- **Data Fetch**: Translates the strategy into specific tool calls via `SpotifyQueryTools`. It leverages the **Analysis Core** for all computations while managing data volume to fit LLM context windows.
- **Analyst**: Synthesizes retrieved data (as JSON or text) into a final response using personas tailored to the user's intent.


## How to Run
Follow these steps to set up the project locally and start exploring your data.

1. **Install Dependencies**: Ensure you have `uv` installed, then run the sync command.
   ```bash
   uv sync
   ```
2. **Prepare Data**:
   - Request your extended streaming history from [Spotify](https://www.spotify.com/account/privacy/) (the file should be JSON format).
   - Place all JSON files in the `data/spotify_history/` directory.
3. **Configure Environment**:
   - run `copy .envtemplate .env`.
   - Add your `GEMINI_API_KEY` or `OPENAI_API_KEY` in `.env`.
4. **Launch Application**:
   ```bash
   uv run streamlit run src/app/main_page.py
   ```

## Project Structure
```bash
spotify-ai-analytics/
├── data/               # Raw Spotify JSON exports
├── src/
│   ├── app/            # Streamlit UI (Chatbot & Dashboard)
│   ├── spotify_agent/  # LangGraph orchestration & AI logic
│   ├── dataloader/     # Data ingestion & Polars transformation
│   └── analytics/      # Centralized analysis & plotting logic
├── tests/              # Unit and integration test suite
└── doc/                # Documentation and design plans
```

## Limitations

- LLM responses are not yet systematically evaluated and may hallucinate in edge cases
- The application currently only supports local execution
- Model selection and API keys are configured manually via environment variables

## Roadmap

- Improve observability and robustness of LLM tool usage
- Refactor data access and tool abstractions for better modularity
- Explore lightweight deployment options
- Support options for user uploading data via the UI