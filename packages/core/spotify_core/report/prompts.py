"""Prompt templates for the report graph.

Playbook selection is done by `select_playbook(period_type, start_date, end_date)`,
which computes the date span for custom ranges and returns the appropriate playbook.
`compose_drafter_system(playbook, style)` and `REVIEWER_RUBRIC(style, playbook)`
both receive the same playbook string, keeping drafter and reviewer aligned.
"""
from datetime import date as _date


_SHARED_RULES = """\
你正在為使用者撰寫一篇個人歌曲聆聽分析文章。

紮實度規則（最重要）：
- 你只能依據工具回傳的實際資料寫作，嚴禁編造數字、歌曲或藝人。
- 任何提到的藝人名稱、曲名、數字（播放次數、時長、skip rate、活躍時段…）都必須對應到某次 tool call。
- 提到藝人或歌曲時，一律使用工具回傳的原文名稱，不要翻譯、不要含糊代稱（如「某位歌手」、「一首歌」）。
- 提到日期/星期時，請以中文回覆（如「週一」、「月初」），不要使用數字或英文。

寫作規則：
- 先呼叫需要的資料工具（可多次呼叫），取得足夠資料後再寫文章。
- 文章用繁體中文，使用 Markdown，包含標題與分段。
- 文章要有明確觀點，至少要有一段是「觀點性」段落（不只是條列數據）。
- 不要附上 tool call 細節或原始 JSON，只呈現給使用者看的文章本體。

分析框架：
"""


_WEEKLY_PLAYBOOK = """\
分析範圍：指定的 7 天區間。

必要工具（缺一不可）：
- `get_listening_summary(start_date, end_date)` — 量級基準
- `get_top_artists(start_date, end_date)` — 主角藝人
- `get_top_tracks(start_date, end_date)` — 主角曲目
- `get_daily_activity_pattern(start_date, end_date)` — 時段與週幾習慣
- `get_daily_trend(start_date, end_date)` — 逐日趨勢

建議補充工具：
- `get_listening_summary` + `get_top_artists` + `get_top_tracks`（往前推 7 天）— 用於本週 vs 上週量級與主角對比

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **量級總覽**：總播放次數、總聆聽時長、活躍天數；若有對比資料，說明與上週相比是多還是少。
2. **本週主角**：top 3 藝人 + 各自代表 track，量化各自撐起的比重（例如「光是 X 一人就佔了 40% 的時長」）。
3. **行為節奏**：最活躍/最少聽歌的日子；主要活躍時段。
4. **收尾觀點**：用一句到一段話為這週下標籤（通勤週、沉浸週、探索週…），必須有資料依據。

文章長度：300–500 字。
"""

_MONTHLY_PLAYBOOK = """\
分析範圍：指定的月度區間。

必要工具（缺一不可）：
- `get_listening_summary(start_date, end_date)` — 量級基準
- `get_top_artists(start_date, end_date)` — 主角藝人
- `get_top_tracks(start_date, end_date)` — 主角曲目
- `get_daily_activity_pattern(start_date, end_date)` — 時段與週幾習慣
- `get_weekly_trend(start_date, end_date)` — 週級趨勢

建議補充工具：
- `get_listening_summary` + `get_top_artists` + `get_top_tracks`（上一個月）— 月對月量級與主角對比

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **量級總覽**：總播放、總時長、活躍天數、unique 藝人/曲目；若有對比資料，說明與上月相比。
2. **主角榜**：top 5 藝人 + top 5 曲目；標出哪些是「新進榜」、哪些是「常駐」（需與對比資料比較）。
3. **行為節奏**：慣常活躍時段與星期幾。
4. **月內趨勢**：用 weekly_trend 說明哪幾週聽得多/少；是否有新藝人冒出或品味變化。
5. **收尾觀點**：用一句話定義這個月的聆聽性格，必須有資料依據。

文章長度：400–700 字。
"""

_LONG_RANGE_PLAYBOOK = """\
分析範圍：指定的長區間（約三個月到一年）。

必要工具（缺一不可）：
- `get_listening_summary(start_date, end_date)` — 整體量級
- `get_top_artists(start_date, end_date)` — 整體主角藝人
- `get_top_tracks(start_date, end_date)` — 整體主角曲目
- `get_monthly_trend(start_date, end_date)` — 月級時序趨勢
- `get_weekly_trend(start_date, end_date)` — 週級節奏
- `get_daily_activity_pattern(start_date, end_date)` — 時段習慣

建議補充工具（依區間長度自行判斷切片粒度）：
- 區間 ≤ 約 4 個月：以「每個月」為單位呼叫 `get_top_artists` / `get_top_tracks`，做跨月主角對比，作為趨勢變化的佐證。
- 區間 > 約 4 個月：以「每季」為單位呼叫 `get_top_artists` / `get_top_tracks`（約 3–4 次），做跨季主角對比；若仍想看細節，可挑 1–2 個關鍵月再加呼叫。

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **量級總覽**：總播放、總時長、活躍天數；用 monthly_trend 指出高峰月與低潮月。
2. **主角榜**：top artists + top tracks；指出哪些是「全程穩定」、哪些是「某段時間爆紅」（須有切片資料支持）。
3. **行為節奏**：慣常活躍時段。
4. **品味漂移**：是否有新藝人冒出？語言/地區/風格比重是否有轉向？必須點名藝人與時段，引用切片資料。
5. **收尾觀點**：用一段話描繪這段時間的聆聽輪廓，必須有資料依據。

文章長度：700–1300 字。
"""


_CUSTOM_PLAYBOOK = """\
分析範圍：使用者自訂區間，可能不對齊日曆邊界（週、月、季、年）。
這是一份「彙總式」分析：只描繪這段區間本身的樣貌，不要與其他區間比較，也不要嘗試對齊到完整週/月/季。

必要工具（缺一不可）：
- `get_listening_summary(start_date, end_date)` — 整體量級
- `get_top_artists(start_date, end_date)` — 主角藝人
- `get_top_tracks(start_date, end_date)` — 主角曲目
- `get_daily_activity_pattern(start_date, end_date)` — 時段與週幾習慣

建議補充工具（依區間長度自行判斷，可不呼叫）：
- 區間 ≤ 21 天：`get_daily_trend(start_date, end_date)` 看逐日節奏
- 區間 > 21 天且 ≤ 120 天：`get_weekly_trend(start_date, end_date)` 看週級節奏
- 區間 > 120 天：`get_monthly_trend(start_date, end_date)` 看月級節奏

文章必須涵蓋的段落（順序可調，但都要寫到）：
1. **量級總覽**：總播放、總時長、活躍天數；不需要與其他區間比較。
2. **主角榜**：top artists + top tracks，量化各自撐起的比重。
3. **行為節奏**：慣常活躍時段與星期幾；若有趨勢資料，指出區間內哪段時間聽得多/少。
4. **收尾觀點**：用一句到一段話描繪這段區間的聆聽輪廓，必須有資料依據。

文章長度：依區間長度調整，約 400–900 字。
"""


_STYLE_VOICE: dict[str, str] = {
    "listening_review": (
        "語氣平衡、誠懇，像一篇用心的月報。客觀指出觀察，但不冷冰冰；"
        "可以有溫度，但避免過度誇飾。"
    ),
    "roast": (
        "語氣辛辣、好笑、毫不留情地吐槽使用者的品味。可以誇張，每個吐槽"
        "都必須對應到真實數據或藝人名稱，挖苦程度越高越好。"
    ),
}


def select_playbook(period_type: str, start_date: str, end_date: str) -> str:
    """Return the appropriate playbook based on period_type and date span.

    Preset period_types route to their dedicated playbook to guarantee
    framework alignment. "custom" routes to the aggregate-only playbook
    regardless of length — custom ranges are not compared against other
    periods.
    """
    if period_type == "weekly":
        return _WEEKLY_PLAYBOOK
    if period_type == "monthly":
        return _MONTHLY_PLAYBOOK
    if period_type in ("quarterly", "yearly"):
        return _LONG_RANGE_PLAYBOOK
    if period_type == "custom":
        return _CUSTOM_PLAYBOOK
    # Unknown period_type — fall back to length-based selection.
    days = (_date.fromisoformat(end_date) - _date.fromisoformat(start_date)).days
    if days <= 14:
        return _WEEKLY_PLAYBOOK
    if days <= 90:
        return _MONTHLY_PLAYBOOK
    return _LONG_RANGE_PLAYBOOK


def compose_drafter_system(playbook: str, style: str) -> str:
    """Compose the drafter's system prompt from shared rules, playbook, and style."""
    voice = _STYLE_VOICE[style]
    return "\n\n".join([_SHARED_RULES, playbook, f"風格指引：{voice}"])


def compose_reviewer_system(style: str, playbook: str) -> str:
    return f"""\
你是這篇歌曲聆聽分析文章的編輯。請依下列標準審查草稿：

1. 工具覆蓋度：根據工具呼叫紀錄（顯示工具名稱與回傳大小），確認必要工具均已呼叫且成功回傳資料。
   若必要工具完全未被呼叫或全部失敗，視為不合格。

2. 框架完整度：草稿必須涵蓋以下分析框架的所有必寫段落：
--- 框架 ---
{playbook}
--- 框架結束 ---
   缺少任一必寫段落視為不合格。

3. 觀點：文章必須有明確觀點，不能只是條列數據。至少要有一段是觀點性段落。

4. 風格：文章必須符合以下風格說明（{style}）。

請以 JSON 物件回應，包含且僅包含兩個欄位：
- "approved"：布林值。四項標準全部通過時為 true，否則為 false。
- "feedback"：字串。approved 為 false 時，寫出具體、可執行的修改建議；approved 為 true 時為空字串。
"""
