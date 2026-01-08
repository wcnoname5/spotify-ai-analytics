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

src/
├─ analytics/
│  │
│  ├─ features/
│  │  ├─ listening.py
│  │  │  - listening_trend(df, freq)
│  │  │  - compare_periods(df, period_a, period_b)
│  │  │
│  │  └─ artists.py
│  │     - top_artists(df, k, date_range)
│  │
│  ├─ plots/
│  │  └─ exploratory.py
│  │     - One-off plots for debugging / exploration
│  │
│  └─ dashboard/
│     └─ app.py
│        - Dash app entry point
│        - Launches browser-based interactive dashboard
│
├─ agent/
│   - LLM chatbot (existing)
│   
└─ utils/
│     └─ data_loader.py (existing)
│        - Load Spotify JSON files
│        - Return clean polaris DataFrames

---

## Design Rules

- No plotting logic inside `features/`
- No data loading inside `dashboard/`
- All analysis functions should be pure and reusable
- Functions in `features/` are future LLM tools

---

## How to Run

- Debug single plot:
  ```bash
  python src/analytics/plots/exploratory.py
  ```

Launch dashboard using Streamlit
```bash
uv run streamlit run src/analytics/dashboard/app.py
```

## Ideas:

1. `dashboard/`:
  - Which table/ plot should be shown?
    - Interactive degree of freedom
    
  - UI (Let's stick with streamlit right now)
    - https://goodreads.streamlit.app/?ref=streamlit-io-home-data-visualization
  - plot: line plot(s):
    - x axis: time(montly/weekly)
    - y axis: listenlingtime (or normalized to proportion of total listening time) / rank 
    - lines: favrotite artists / tracks (this may not work)
      - lines can be selectively shown or not
  - Mouse-based to manually change date infos
  - no sidebar, maybe headers
  - need to consider where to place the LLM bot into
2. `features/`:
  - inplement functions: