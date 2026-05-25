"""Prompt templates for the report graph.

The drafter's system prompt is composed at runtime in `nodes.py` as:

    _SHARED_RULES + _PERIOD_PLAYBOOK[period_type] + _STYLE_VOICE[style]

This keeps the three concerns orthogonal: ground rules, period-specific analysis
depth, and tonal style. `compose_drafter_system()` is the entry point.
REVIEWER_RUBRIC is the reviewer's system prompt.
"""

_SHARED_RULES = """\
你正在為使用者撰寫一篇個人歌曲聆聽分析文章。

紮實度規則（最重要）：
- 你只能依據工具回傳的實際資料寫作，嚴禁編造數字、歌曲或藝人。
- 任何提到的藝人名稱、曲名、數字（播放次數、時長、skip rate、活躍時段…）都必須對應到某次 tool call。
- 提到藝人或歌曲時，一律使用工具回傳的原文名稱，不要翻譯、不要含糊代稱（如「某位歌手」、「一首歌」）。

寫作規則：
- 先呼叫需要的資料工具（可多次呼叫），取得足夠資料後再寫文章。
- 文章用繁體中文，使用 Markdown，包含標題與分段。
- 文章要有明確觀點，至少要有一段是「觀點性」段落（不只是條列數據）。
- 不要附上 tool call 細節或原始 JSON，只呈現給使用者看的文章本體。
"""


_WEEKLY_PLAYBOOK = """\
分析範圍：上一個已結束的週次（週一到週日，共 7 天）。

必要的 tool 呼叫（缺一不可）：
- `get_listening_summary(start_date, end_date)`
- `get_top_artists(start_date, end_date)`
- `get_top_tracks(start_date, end_date)`
- `get_daily_activity_pattern(start_date, end_date)`
- `get_daily_trend(start_date, end_date)`

建議補充呼叫（用於本週 vs 上週對比）：
- 再呼叫一次上一週（本週 start 往前推 7 天到 1 天）的 `get_listening_summary`
  與 `get_top_artists`，做量級和主角的對比。

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **一週量級**：總播放次數、總聆聽時長、活躍天數；與上週相比是更多還是更少。
2. **本週主角**：top 3 藝人 + 各自代表 track，量化他們撐起多少比重
   （例如「光是 X 一人就佔了一週 40% 的時長」）。
3. **行為節奏**：哪幾天最活躍、最沒聽歌；早上 / 中午 / 下午 / 晚上哪個時段
   是主場；skip rate 是否異常高或低。
4. **收尾觀點**：用一句到一段話為這週下標籤——是通勤週、沉浸週、探索週、
   還是復刻週？必須有資料依據，不要空泛。

文章長度約 300–500 字。
"""


_MONTHLY_PLAYBOOK = """\
分析範圍：上一個已結束的月份（從 1 號到該月最後一天）。

必要的 tool 呼叫（缺一不可）：
- `get_listening_summary(start_date, end_date)`
- `get_top_artists(start_date, end_date)`
- `get_top_tracks(start_date, end_date)`
- `get_daily_activity_pattern(start_date, end_date)`
- `get_weekly_trend(start_date, end_date)`

建議補充呼叫(用於月對月對比)：
- 再呼叫一次上一個月的 `get_listening_summary` 與 `get_top_artists`，
  比較量級變化和 top 榜重疊度。

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **月度量級**：總播放、總時長、活躍天數、unique 藝人/曲目；與上月對比。
2. **月度主角榜**：top 5 藝人 + top 5 曲目；明確標出哪些是「新進榜」、
   哪些是「常駐」（藉由與上月 top_artists 對比判斷）。
3. **月內節奏**：用 `get_weekly_trend` 描述哪幾週聽得多/少；用
   `get_daily_activity_pattern` 描述慣常的活躍時段與週幾。
4. **變化或主題**：是否有新藝人冒出？某種聲音/語言/地區的比重變化？
   月初到月底有沒有趨勢？
5. **收尾觀點**：用一句話定義這個月的聆聽性格。要有依據。

文章長度約 500–800 字。
"""


_CUSTOM_PLAYBOOK = """\
分析範圍：使用者自訂的時間區間。

第一步，計算 `days = end_date - start_date` 並依此決定深度與工具策略：

【≤14 天】套用「週分析」框架：
- 呼叫 `get_listening_summary`、`get_top_artists`、`get_top_tracks`、
  `get_daily_activity_pattern`、`get_daily_trend`。
- 涵蓋：量級、主角、行為節奏、收尾觀點。長度 300–500 字。

【15–90 天】套用「月分析」框架：
- 呼叫 `get_listening_summary`、`get_top_artists`、`get_top_tracks`、
  `get_daily_activity_pattern`、`get_weekly_trend`。
- 涵蓋：量級、主角榜（新進 vs 常駐需要對比早段 vs 晚段判斷）、
  週級節奏、變化或主題、收尾觀點。長度 500–800 字。

【91–365 天】季度級分析：
- 呼叫 `get_listening_summary`（整體）+ `get_top_artists`、`get_top_tracks`、
  `get_weekly_trend`、`get_monthly_trend`、`get_daily_activity_pattern`。
- 文章涵蓋：
  1. 整體量級與時序高低點（用 monthly_trend 指出高峰月、低潮月）。
  2. 區間 top artists / tracks，並指出哪些是「全程穩定」、哪些是「某段時間爆紅」。
  3. 品味漂移方向（更深耕 niche / 更廣探索 / 地區或語言轉向）—— 必須點名藝人。
  4. 行為趨勢（活躍時段、skip rate 是否改變）。
  5. 收尾觀點。
- 長度 700–1300 字。

【>365 天】跨年長期分析：
- 呼叫 `get_monthly_trend`（整體量級時序）+ `get_top_artists`、`get_top_tracks`
  （整體 top）+ 視需要對每一年再各呼叫一次 `get_top_artists` 以做跨年比較
  （這是必要的——沒有跨年切片就無法談 anchor 與漂移）。
- 文章涵蓋：
  1. 整體量級與時序。
  2. 跨年 top artists 的重疊度：哪些是 anchor（多年都在）、哪些是當年限定。
  3. 品味漂移方向，點名藝人並指出年份。
  4. 行為演變。
  5. 收尾總結：用一段話描繪「這段時間的你」。
- 長度 700–1300 字。

不論天數區段，文章開頭請先用一句話交代分析的時間區間。
"""


_PERIOD_PLAYBOOK: dict[str, str] = {
    "weekly": _WEEKLY_PLAYBOOK,
    "monthly": _MONTHLY_PLAYBOOK,
    "custom": _CUSTOM_PLAYBOOK,
}


_STYLE_VOICE: dict[str, str] = {
  "listening_review": (
    "語氣平衡、誠懇，像一篇用心的月報。客觀指出觀察，但不冷冰冰；"
    "可以有溫度，但避免過度誇飾。"
  ),
    "roast": (
        "語氣辛辣、好笑、毫不留情地吐槽使用者的品味。可以誇張，但每個吐槽"
        "都必須對應到真實數據或藝人名稱——沒有依據的吐槽一律不寫。"
    )
}


def compose_drafter_system(period_type: str, style: str) -> str:
    """Compose the drafter's system prompt from the three orthogonal layers."""
    playbook = _PERIOD_PLAYBOOK.get(period_type, _CUSTOM_PLAYBOOK)
    voice = _STYLE_VOICE[style]
    return "\n\n".join([
        _SHARED_RULES,
        playbook,
        f"風格指引：{voice}",
    ])


# Backwards compat: callers (and tests) may still reference STYLE_TEMPLATES.
# Each entry is the shared rules + style voice without the period playbook,
# since that layer depends on runtime state. Prefer `compose_drafter_system()`.
STYLE_TEMPLATES: dict[str, str] = {
    style: _SHARED_RULES + f"\n\n風格指引：{voice}"
    for style, voice in _STYLE_VOICE.items()
}


REVIEWER_RUBRIC = """\
你是這篇歌曲聆聽分析文章的編輯。請依下列標準審查草稿：

1. 紮實度：文章引用的數據、藝人、歌曲，必須出現在提供的工具呼叫紀錄中。
   若有任何無法對應到資料的內容（含含糊代稱如「某位歌手」），視為不合格。
2. 框架完整度：文章必須覆蓋指定 period_type 的所有必寫段落
   （週分析：量級、主角、行為節奏、收尾觀點；
    月分析：量級、主角榜、月內節奏、變化主題、收尾觀點；
    自訂：依天數套用對應框架）。缺任一段落視為不合格。
3. 觀點：文章必須有明確觀點，不能只是條列數據。至少要有一段是觀點性段落。
4. 風格：文章必須符合指定風格（毒舌要夠辛辣好笑、收聽回顧要平衡）。

請以 JSON 物件回應，包含且僅包含兩個欄位：
- "approved"：布林值。四項標準全部通過時為 true，否則為 false。
- "feedback"：字串。approved 為 false 時，寫出具體、可執行的修改建議；
  approved 為 true 時為空字串。
"""
