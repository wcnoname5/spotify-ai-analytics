"""AI 聽歌分析 — report-generation section of the dashboard (Streamlit)."""

import streamlit as st
from loguru import logger

from spotify_core.config import settings
from spotify_core.db.queries import is_history_empty
from spotify_core.report.graph import generate_report
from spotify_core.report.models import build_chat_model

from spotify_web.config import get_llm_config

from spotify_web.period_filter import render_period_dates

_DB_PATH = str(settings.history_db_path)

# Style key -> UI label.
_STYLES = {
    "monthly_review": "📅 月度回顧",
    "roast": "🔥 毒舌",
    # "gentle": "😊 溫和",
    # "critic": "🎼 專業樂評",
}


def _render_report(result, model_label: str) -> None:
    """Render a finished ReportResult: the article plus a status caption."""
    st.markdown(result.text)
    tools_used = ", ".join(sorted({r.name for r in result.tool_log})) or "（無）"
    status = "✅ 已通過審查" if result.approved else "⚠️ 已達修訂上限"
    st.caption(
        f"{status}｜模型：{model_label}｜修訂次數：{result.revision_count}｜"
        f"使用工具：{tools_used}"
    )
    if result.trace_url:
        st.caption(f"[在 Langfuse 查看追蹤]({result.trace_url})")


def render_ai_block() -> None:
    """Render the AI report section below the dashboard."""
    st.divider()
    st.subheader("🤖 AI 聽歌分析")

    if is_history_empty(_DB_PATH):
        st.info("資料庫沒有播放紀錄，無法產生分析。")
        return

    llm_config = get_llm_config()
    if not llm_config["models"]:
        st.info(
            "尚未設定 LLM 金鑰。請在 .env 加入 `GEMINI_API_KEY` 後重新啟動，"
            "即可使用 AI 分析。"
        )
        return

    col_style, col_model = st.columns(2)
    with col_style:
        style = st.selectbox(
            "分析風格",
            options=list(_STYLES),
            format_func=lambda k: _STYLES[k],
            key="ai_style",
        )
    with col_model:
        model_choice = st.selectbox(
            "模型",
            options=llm_config["models"],
            format_func=lambda m: f"{m['provider']} / {m['model']}",
            key="ai_model",
        )

    start, end, period_type = render_period_dates("ai_period")
    st.session_state["ai_filter"] = {
        "start": start,
        "end": end,
        "period_type": period_type,
    }

    if st.button("✨ 產生分析", key="ai_generate"):
        st.session_state.pop("ai_report", None)
        st.session_state.pop("ai_report_model", None)
        try:
            with st.spinner("AI 正在分析你的聽歌資料…"):
                model = build_chat_model(
                    model_choice["provider"], model_choice["model"]
                )
                result = generate_report(
                    style=style,
                    start_date=start,
                    end_date=end,
                    db_path=_DB_PATH,
                    model=model,
                    period_type=period_type,
                )
            st.session_state["ai_report"] = result
            st.session_state["ai_report_model"] = (
                f"{model_choice['provider']} / {model_choice['model']}"
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            logger.exception("AI report generation failed")
            st.error(f"產生分析時發生錯誤：{exc}")

    if "ai_report" in st.session_state:
        _render_report(
            st.session_state["ai_report"],
            st.session_state.get("ai_report_model", ""),
        )
