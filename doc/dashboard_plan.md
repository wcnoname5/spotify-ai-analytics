## Dashbaord


## Purpose
This module handles:
- Data loading & preprocessing
- Reusable analysis functions
- Interactive dashboard (no LLM involved)

Designed to later expose analysis functions as LLM tools.

- Data: `polaris` Dataframe

- `ploty` for interactive visualization

## Dashboard Plans

### Folder structure

```
src/
├─ app/
│  │
│  ├─ main_page.py 
│  │  - (two tabs, one for chatbot, one for ) # TODO: please modify from `main_gui.puy`
│  │  - serve as the main entry point
│  ├─  chatbot_page.py (main chatbot page) # TODO: please split that page elements form `main_gui.puy`
│  │
│  ├─ dashborad.py # TODO: please rename `analytics/dashboard/app.py` to `dashboard.py` here
│  ├─ time_analysis.py # move from `analytics/dashboard/time_analysis.py`
│  ├─ track_analysis.py # move from `analytics/dashboard/track_analysis.py`
│
├─ agent/
│   - LLM chatbot (existing)
│   
└─ data_loader/
│     └─ data_loader.py (existing)
│        - Load Spotify JSON files
│        - Return clean polaris DataFrames
```

---

## How to Run

Launch dashboard using Streamlit
# TODO: please modify the entry path accordingly
```bash
uv run streamlit run src/app/main_page.py 
```

## Reference Examples:

1. `dashboard/`:
  - Which table/ plot should be shown?
    - Interactive degree of freedom
    
  - UI (Let's stick with streamlit right now)
    - https://goodreads.streamlit.app/?ref=streamlit-io-home-data-visualization
    - https://explorify.link/
