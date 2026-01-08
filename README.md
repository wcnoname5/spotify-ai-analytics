# Spotify AI Analytics Agent

## Overview
This module implements a chatbot that leverages LLMs to answer user queries about their Spotify listening history. It uses preprocessed data and analysis functions from the analytics module to provide insights.

Also provide a dashboard module that handles data loading, preprocessing, and interactive visualization using Plotly. (Under Construction)

### Key Features
- **Natural Language Queries**: Users can ask questions in plain English about their listening habits.
- **Retrive User Data**: The chatbot retrieves relevant data from the user's Spotify history.
- **Insightful Responses**: Provides detailed answers, trends, and recommendations based on user data. Curerently supports three main types of intents:
    1. `factual_query`: simply data retrieval and summary given the user query. No extra guessing and analysis.
    2. `insight_analysis`: Simple analysis (e.g., top artists, listening trends) based on user query and retrieved data. May generate some description about user's listening habits.
    3. `recommendation`: Provide personalized music recommendations based on user's listening history and preferences. This may involve more complex analysis and pattern recognition.

    4. `other`: It jusct catch all other annoying queries that are not related to the data

## Note:

Project is under active development. The dashboard module is still being built out, and more analysis functions will be added over time. Contributions and feedback are welcome!