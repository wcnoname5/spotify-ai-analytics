# Spotify AI Analytics

## Goals

-   Upload Personal Spotify Data
-   LLM Chatbot can analyze your data via chat
    - `factual_query`, `insight_analysis`, `recommendation`, or `other`
    - Currently Pure text output, no plots for output
-   Interactive Visualization Dashboard
-   A simple UI

## Current Status/ TODOs

-   [x] Inplemnt Dataloader class, can load jsons into Polars dataframe
    -   [x] with simple methods to query/aggrgate the data

-   [x] Implement llm chatbot
    -  able to do simple chats
    -  equipped with tool calls to call Dataloader to extract data for analysis

-   [] Build Interactive Plots
    -   build functions so that is can produce meaningful features and tables
    -   plot the results

-   [] Build Integration UI
    -  That have clear dashborad plot and the llm chat interface
    -  use steamlit for now.

    
