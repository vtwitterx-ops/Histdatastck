"""
Stock Historical Data Explorer
──────────────────────────────
Streamlit app: enter a stock symbol, pick a date range and candle
interval (daily / weekly / monthly / etc.), fetch OHLCV data via
yfinance, view it as a table + candlestick chart, and download as CSV.

Run locally with:
    pip install streamlit yfinance pandas plotly requests
    streamlit run stock_history_app.py
"""

import time
from datetime import date, timedelta

import pandas as pd
import requests
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go

# ─────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────
st.set_page_config(page_title="Stock Historical Data Explorer", layout="wide")
st.title("📈 Stock Historical Data Explorer")
st.caption("Enter a stock symbol, choose a date range and candle interval, and fetch OHLCV history.")

# Interval options: label shown to user -> yfinance interval code
INTERVAL_OPTIONS = {
    "Daily":     "1d",
    "Weekly":    "1wk",
    "Monthly":   "1mo",
    "Quarterly (resampled from monthly)": "3mo_custom",  # yfinance has no native 3mo; we resample
}

# Common NIFTY 50 shortcuts (optional convenience, not required)
NIFTY_SHORTCUTS = {
    "RELIANCE": "Energy / Conglomerate",
    "TCS": "IT Services",
    "HDFCBANK": "Banking",
    "INFY": "IT Services",
    "ICICIBANK": "Banking",
    "HINDUNILVR": "FMCG",
    "BAJFINANCE": "NBFC / Finance",
    "MARUTI": "Automobile",
    "SUNPHARMA": "Pharma",
    "ITC": "FMCG / Conglomerate",
}

# ─────────────────────────────────────────
# Sidebar inputs
# ─────────────────────────────────────────
with st.sidebar:
    st.header("Query Settings")

    symbol_input = st.text_input(
        "Stock symbol",
        value="RELIANCE",
        help="For NSE (India) stocks, just type the name e.g. RELIANCE, TCS, INFY. "
             "For US/other exchanges, type the full ticker e.g. AAPL, MSFT.",
    )

    market = st.radio(
        "Market",
        options=["NSE (India) — auto add .NS", "Other / Global — use symbol as-is"],
        index=0,
    )

    with st.expander("NIFTY 50 quick picks"):
        pick = st.selectbox("Choose a stock", ["-- none --"] + list(NIFTY_SHORTCUTS.keys()))
        if pick != "-- none --":
            symbol_input = pick
            st.info(f"Selected: {pick} ({NIFTY_SHORTCUTS[pick]})")

    today = date.today()
    default_start = today - timedelta(days=5 * 365)

    start_date = st.date_input("Start date", value=default_start, max_value=today)
    end_date = st.date_input("End date", value=today, max_value=today)

    interval_label = st.selectbox("Candle interval", list(INTERVAL_OPTIONS.keys()))

    fetch_clicked = st.button("Fetch Data", type="primary", use_container_width=True)

# ─────────────────────────────────────────
# Helpers (adapted from the original script:
# browser-like session + retry logic)
# ─────────────────────────────────────────
def make_yf_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://finance.yahoo.com/",
        "Origin": "https://finance.yahoo.com",
    })
    return session


def resolve_ticker(symbol: str, market_choice: str) -> str:
    symbol = symbol.strip().upper()
    if market_choice.startswith("NSE") and not symbol.endswith(".NS"):
        return f"{symbol}.NS"
    return symbol


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_ohlcv(ticker_sym: str, start: str, end: str, interval: str, retries: int = 3, delay_between: int = 3):
    """Download OHLCV with retry logic. Returns (df, error_message)."""
    yf_interval = "1mo" if interval == "3mo_custom" else interval

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            session = make_yf_session()
            ticker = yf.Ticker(ticker_sym, session=session)

            df = ticker.history(
                start=start,
                end=end,
                interval=yf_interval,
                auto_adjust=True,
                actions=False,
            )

            if df.empty:
                last_error = "No data returned (symbol may be wrong, delisted, or range has no trading days)."
                time.sleep(delay_between * attempt)
                continue

            if hasattr(df.index, "tz") and df.index.tz is not None:
                df.index = df.index.tz_convert(None)
            df.index.name = "Date"

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]

            ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
            df = df[[c for c in ohlcv_cols if c in df.columns]].round(2)

            # Resample to quarterly if that was requested (from monthly data)
            if interval == "3mo_custom":
                df = df.resample("3ME").agg({
                    "Open": "first",
                    "High": "max",
                    "Low": "min",
                    "Close": "last",
                    "Volume": "sum",
                }).dropna(how="all")

            df["Daily_Change"] = (df["Close"] - df["Open"]).round(2)
            df["Daily_Change_Pct"] = ((df["Close"] - df["Open"]) / df["Open"] * 100).round(2)
            df["Range"] = (df["High"] - df["Low"]).round(2)

            return df, None

        except Exception as e:
            last_error = str(e)
            time.sleep(delay_between * attempt)

    return pd.DataFrame(), last_error


# ─────────────────────────────────────────
# Main panel
# ─────────────────────────────────────────
if fetch_clicked:
    if not symbol_input.strip():
        st.error("Please enter a stock symbol.")
    elif start_date >= end_date:
        st.error("Start date must be before end date.")
    else:
        ticker_sym = resolve_ticker(symbol_input, market)
        interval_code = INTERVAL_OPTIONS[interval_label]

        with st.spinner(f"Fetching {ticker_sym} data ({interval_label.lower()})..."):
            df, error = fetch_ohlcv(
                ticker_sym,
                start_date.strftime("%Y-%m-%d"),
                (end_date + timedelta(days=1)).strftime("%Y-%m-%d"),  # end is exclusive in yfinance
                interval_code,
            )

        if df.empty:
            st.error(f"Could not fetch data for **{ticker_sym}**. {error or ''}")
            st.info("Tips: double-check the symbol, try a shorter date range, or wait a bit if Yahoo Finance is rate-limiting your IP.")
        else:
            st.success(f"Fetched {len(df):,} {interval_label.lower()} candles for **{ticker_sym}** "
                       f"({df.index.min().date()} → {df.index.max().date()})")

            # ── Summary metrics ──────────────────────────
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Latest Close", f"{df['Close'].iloc[-1]:,.2f}")
            c2.metric("Period High", f"{df['High'].max():,.2f}")
            c3.metric("Period Low", f"{df['Low'].min():,.2f}")
            total_return = (df['Close'].iloc[-1] / df['Close'].iloc[0] - 1) * 100
            c4.metric("Period Return", f"{total_return:+.2f}%")

            # ── Candlestick chart ────────────────────────
            fig = go.Figure(data=[go.Candlestick(
                x=df.index,
                open=df["Open"], high=df["High"],
                low=df["Low"], close=df["Close"],
                name=ticker_sym,
            )])
            fig.update_layout(
                title=f"{ticker_sym} — {interval_label} Candles",
                xaxis_title="Date",
                yaxis_title="Price",
                xaxis_rangeslider_visible=False,
                height=500,
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

            # ── Volume chart ─────────────────────────────
            vol_fig = go.Figure(data=[go.Bar(x=df.index, y=df["Volume"], name="Volume")])
            vol_fig.update_layout(
                title="Volume",
                height=200,
                margin=dict(l=10, r=10, t=30, b=10),
            )
            st.plotly_chart(vol_fig, use_container_width=True)

            # ── Data table ────────────────────────────────
            st.subheader("Historical Data")
            st.dataframe(df, use_container_width=True)

            # ── Download ──────────────────────────────────
            csv_bytes = df.to_csv().encode("utf-8")
            st.download_button(
                "⬇️ Download CSV",
                data=csv_bytes,
                file_name=f"{ticker_sym.replace('.', '_')}_{interval_code}_history.csv",
                mime="text/csv",
                use_container_width=True,
            )
else:
    st.info("Set your options in the sidebar and click **Fetch Data** to begin.")
