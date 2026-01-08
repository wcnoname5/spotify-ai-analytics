### Basics: Data Loader and Query Tools

1. [x] build an data loader for simple CICD 
    - use `Polars` for now
    - class `DataLoader`: read and build a `pl.DataFrame` from JSONs
        - defining columns (defiend a pydandtic model but not used for now)
        - parsing timestamps
    - add handy methods to query from dataframe
        - filter by date range
        - get top N artists/tracks
        - get listening trends (daily/weekly/monthly)
        - get summary statistics (total listening time, unique 
        artists/tracks, etc.)
2. [ ] Get more data: (Optional, May in future)
    - Explore Spotify API/Discogs to fetch more detailed data (e.g., audio features, playlists, year, genere info...)

###  AI Agent with LangGraph Path
1. [x] Check my Google AI studio

4. [x] wrap-up the query tools
    - Implemented a few in `tool.py` (via a class) and ran unit tests
4. LangGraph main graph workflow
    - Define nodes and edges
        - 4 nodes: intent_parser, fetch_data, analyst and condtional node: should_continue
    - Define data flow between nodes
    - Question: which node requires LLM calls?
        - intent_parser: yes
        - fetch_data: maybe (if searching unstructured data)
        - analyst: yes
    - which step requires and must need to use tools?
        - intent_parser: yes (use `llm_bind_tool`)
        - analyst: NO!
5. [ ] Test Graph with basic queries
    - ChatBot/LLM provide summarize and simple analysis (no or less genre/style based analysis) via queried data
        - For advanced analysis (genre/style based), personlized recommendation, we may need to implement custom analysis functions in the future
    Idea: implement 3 types of intent for chatbot
        1. `factual_query`: simply data retrieval and summary given the user query. No extra guessing and analysis.
        2. `insight_analysis`: Simple analysis (e.g., top artists, listening trends) based on user query and retrieved data. May generate some description about user's listening habits.
        3. `recommendation`: Provide personalized music recommendations based on user's listening history and preferences. This may involve more complex analysis and pattern recognition.
            - anyway, I can still implemnt a prompt for recommendation in the `analyst` node, but may not work well for now.
        4. `other`: currently it jusct catch all other annoying queries that are not related to the data.
    - After defining the intent types, we can create different system prompts (in `analyst` node) for each type to guide the LLM's behavior accordingly.

    *Working on:*
    1. write and system prompt (for `intent_parser` and `analyst`)
    2. test with sample queries (will create `test_chatbot_scenarios.py`)
    3. check if the tools can be correctly called
    *Example Test Cases: (can be much simpler but anyway let us try them out)*
        - Simple (factual) Queries:
            - [x] "Who are my top 3 favorite artists?"
            - "Who are my top 3 favorite artists in August, 2023?",
            - "How many artist and what's the total time did I played in 2024?" 
        - Analysis (kinda hard here)
            - [x] "Analyze my music taste in last year" # ok but currently last year is literaly the year before from now.
            - [] "Analyze my music trend in last year"
            - "What music do I listen to most often in the morning?"
            - "When do I listen to music the most?" (The tools haven't implemented yet: `get_listening_by_time`)
        - Recommendation
            - [x] "Can you recommend some new artists for me according to my taste in last year?"

6. [ ] Finalize the project structure and code organization
    - Ensure modularity and readability
    - Add comments and documentation
    - Add some example queries and usage instructions in `README.md`
    - Some next-steps and future work notes in `develop_notes.md`

7. Future Work / Next Steps
    - Improve data loader to handle more complex data formats
    - Enhance AI agent with more advanced analysis capabilities
    - Integrate visualization tools for better data representation
    - Explore deployment options (e.g., web app, API)
    - RAG from some unstructured data (e.g., user reviews, social media posts about music, artist bios from Spotify API(if available) or wikipedia)

### Data Visualization Path

1. [ ] Explore visualization libraries
    - Consider using `Plotly` for data visualization
    - Create interactive charts and graphs
    - What kind of visualization?
        - Listening trends over time (line charts)
        - Top artists/tracks (bar charts)
        - Genre distribution (pie charts)
    - Self-defined Features:
        - Interactive dashboard to explore listening history
        - Filters for date ranges, genres, artists, etc.

2. How to visualize?
    - [ ] Build a simple web app using `Streamlit` or `Dash`
    - [ ] Integrate visualizations into the web app
    - [ ] Allow users to interact with the data (e.g., filter by date range, select specific artists/genres)

### Integration 

1. [ ] Integrate AI Agent with Data Visualization
    - Allow users to query their listening history and get visualizations as responses
    - Example: "Show me my listening trends over the past year" -> returns a line chart
2. [ ] Web APP (Interface)

### Notes and other settings:

- setup: i've wrap the project as a package, please run `pip install -e .` in root or just run `uv sync` since the `.toml` file had already prepared.

- loggings: 

### Don't bother them
`cli.py`
`rag.py`