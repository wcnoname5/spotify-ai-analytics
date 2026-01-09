import streamlit as st
import plotly.express as px
from analytics.features.analysis_functions import get_monthly_listening_trend, get_weekly_listening_trend

def render_time_analysis(loader, start_date, end_date, show_tables):
    st.header("Time-based Trends & Patterns")
    
    # Define Row 2 with fixed height for symmetry
    row_height = 450
    row = st.container()
    
    with row:
        col1, col2 = st.columns(2)
        
        with col1:
            with st.spinner("Calculating monthly trend..."):
                trend_df = get_monthly_listening_trend(loader, start_date=start_date, end_date=end_date)

                if not trend_df.is_empty():
                    fig_trend = px.bar(
                        trend_df.to_pandas(),
                        x="month_label",
                        y="total_minutes",
                        title="Monthly Listening Time",
                        labels={
                            "year":"Year",
                            "month_label": "Month", "total_minutes": "Minutes Played"
                        },
                        hover_data=["year", "month", "total_tracks_played", "unique_listened_tracks"],
                        color="total_minutes",
                        color_continuous_scale="Viridis"
                    )
                    fig_trend.update_layout(
                        xaxis_tickangle=-45,
                        xaxis_tickformat="%Y",
                        xaxis_dtick="M6",
                        xaxis_title="Month",
                        coloraxis_showscale=False,
                        height=row_height
                    )
                    st.plotly_chart(fig_trend, width="stretch")
                    
                    if show_tables:
                        with st.expander("Show Trend Data Table"):
                            st.dataframe(trend_df.to_pandas(), width="stretch")
                else:
                    st.info("No trend data found for the selected date range.")

        # Weekly Listening Trend Section
        with col2:
            with st.spinner("Calculating weekly trend..."):
                weekly_df = get_weekly_listening_trend(loader, start_date=start_date, end_date=end_date)
                
                if not weekly_df.is_empty():
                    # Define daytime colors (using standard hex or rgba)
                    daytime_colors = {
                        "Night": "rgba(31, 96, 180, 0.9)",
                        "Morning": "rgba(231, 185, 0, 0.9)",
                        "Afternoon": "rgba(255, 126, 14, 0.9)",
                        "Evening": "rgba(214, 39, 39, 0.85)"
                    }
                    
                    fig_weekly = px.bar(
                        weekly_df.to_pandas(),
                        x="weekday",
                        y="total_minutes",
                        color="time_range",
                        title="Daily Activity Pattern",
                        labels={"total_minutes": "Minutes Played", "weekday": "Day of Week", "time_range": "Period"},
                        color_discrete_map=daytime_colors,
                        category_orders={
                            "weekday": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
                            "time_range": ["Morning", "Afternoon", "Evening", "Night"]
                        }
                    )
                    fig_weekly.update_layout(
                        barmode='stack',
                        xaxis_title="",
                        legend_title="",
                        height=row_height
                    )
                    st.plotly_chart(fig_weekly, width="stretch")
                    
                    if show_tables:
                        with st.expander("Show Weekly Data Table"):
                            st.dataframe(weekly_df.to_pandas(), width="stretch")
                else:
                    st.info("No weekly trend data found.")
