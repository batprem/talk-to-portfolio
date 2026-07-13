"""Streamlit dashboard for the efficient frontier.

Run from the repo root, e.g.:
    uv run --with streamlit --with plotly --with yfinance --with pandas --with numpy \
        streamlit run .claude/skills/efficient-frontier/scripts/app.py

All inputs live in the sidebar and default to the workshop's offline dataset so
it works even on a blocked venue network. Change the sidebar and the charts
recompute live.
"""

import os
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Import the sibling compute module regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frontier  # noqa: E402

st.set_page_config(page_title="Efficient Frontier", layout="wide")
st.title("📈 Efficient Frontier — หาพอร์ตที่เหมาะที่สุด")

# ---- Sidebar inputs -------------------------------------------------------
# Inputs are stored in st.session_state under stable keys so the AI chat can set
# them programmatically. DEFAULTS seed the first run; the chat queues changes in
# `pending_inputs`, which we apply here — before the widgets are built, the only
# point in a Streamlit run where widget state can be set safely.
DEFAULTS = {
    "ef_source": "online",
    "ef_tickers_raw": "PTT.BK,CPALL.BK,KBANK.BK,ADVANC.BK",
    "ef_csv_path": "datasets/stock_prices.csv",
    "ef_period": "5y",
    "ef_rf": 0.02,
    "ef_n_portfolios": 5000,
    "ef_cap_on": False,
    "ef_weight_cap": 0.4,
    "ef_seed": 42,
}
_SOURCE_TICKER_DEFAULTS = {"offline": "ABC,XYZ", "online": "PTT.BK,CPALL.BK,KBANK.BK,ADVANC.BK"}
for _k, _v in DEFAULTS.items():
    st.session_state.setdefault(_k, _v)
if "pending_inputs" in st.session_state:
    st.session_state.update(st.session_state.pop("pending_inputs"))


def _on_source_change():
    """Swap the ticker suggestion when the user flips source — but only if the field
    still holds the *other* source's default, so custom/chat-set tickers are kept."""
    new_src = st.session_state["ef_source"]
    other = "online" if new_src == "offline" else "offline"
    if st.session_state.get("ef_tickers_raw", "") == _SOURCE_TICKER_DEFAULTS[other]:
        st.session_state["ef_tickers_raw"] = _SOURCE_TICKER_DEFAULTS[new_src]


st.sidebar.header("Inputs")
source = st.sidebar.radio(
    "Data source", ["online", "offline"], key="ef_source", on_change=_on_source_change,
    help="online = real prices via yfinance (auto-falls back to offline CSV if blocked); "
         "offline = datasets/stock_prices.csv",
)
tickers_raw = st.sidebar.text_input("Tickers (comma-separated)", key="ef_tickers_raw")
csv_path = st.sidebar.text_input("CSV path (offline)", key="ef_csv_path")
period = st.sidebar.selectbox("Lookback (online)", ["1y", "2y", "3y", "5y", "10y"], key="ef_period")
rf = st.sidebar.number_input("Risk-free rate", step=0.005, format="%.3f", key="ef_rf")
n_portfolios = st.sidebar.slider("Random portfolios", 1000, 20000, step=1000, key="ef_n_portfolios")
cap_on = st.sidebar.checkbox("Cap single-asset weight", key="ef_cap_on")
weight_cap = st.sidebar.slider("Max weight per asset", 0.1, 1.0, step=0.05, key="ef_weight_cap") if cap_on else None
seed = st.sidebar.number_input("Random seed", step=1, key="ef_seed")

tickers = [t.strip() for t in tickers_raw.split(",") if t.strip()]

# ---- Compute --------------------------------------------------------------
try:
    res = frontier.run(
        source=source, tickers=tickers, csv_path=csv_path, period=period,
        rf=rf, n_portfolios=n_portfolios, seed=int(seed), weight_cap=weight_cap,
    )
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not build the frontier: {exc}")
    st.stop()

stats, sim, optima = res["stats"], res["sim"], res["optima"]
assets = stats["tickers"]

if res["source_used"] != source:
    st.warning(f"Requested **{source}** but used **{res['source_used']}** (network fell back to CSV).")
st.caption(f"Assets: {', '.join(assets)}  •  data: {res['source_used']}  •  rf = {rf:.1%}")

# ---- Frontier chart -------------------------------------------------------
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=sim["volatility"], y=sim["return"], mode="markers",
    marker=dict(size=5, color=sim["sharpe"], colorscale="Viridis", showscale=True,
                colorbar=dict(title="Sharpe")),
    name="portfolios", hovertemplate="vol %{x:.3f}<br>ret %{y:.3f}<extra></extra>",
))
curve = res["curve"]
if not curve.empty:
    fig.add_trace(go.Scatter(x=curve["volatility"], y=curve["return"], mode="lines",
                             line=dict(color="black", width=2), name="frontier (2-asset)"))
for label, colr, sym in [("min_variance", "blue", "star"), ("max_sharpe", "red", "diamond")]:
    row = optima[label]
    fig.add_trace(go.Scatter(
        x=[row["volatility"]], y=[row["return"]], mode="markers",
        marker=dict(size=16, color=colr, symbol=sym, line=dict(width=1, color="white")),
        name=label.replace("_", "-"),
    ))
# Individual assets for reference.
fig.add_trace(go.Scatter(
    x=stats["ann_vol"].values, y=stats["ann_return"].values, mode="markers+text",
    marker=dict(size=10, color="orange", symbol="x"), text=assets, textposition="top center",
    name="single assets",
))
fig.update_layout(xaxis_title="Volatility (annualized)", yaxis_title="Return (annualized)",
                  height=560, legend=dict(orientation="h", y=-0.2))
st.plotly_chart(fig, width="stretch")

# ---- Optimal portfolios ---------------------------------------------------
c1, c2 = st.columns(2)
for col, label, title in [(c1, "min_variance", "🛡️ Minimum-variance"), (c2, "max_sharpe", "⭐ Max-Sharpe")]:
    row = optima[label]
    with col:
        st.subheader(title)
        st.metric("Return", f"{row['return']:.2%}")
        st.metric("Volatility", f"{row['volatility']:.2%}")
        st.metric("Sharpe", f"{row['sharpe']:.2f}")
        weights = row[assets]
        st.dataframe(pd.DataFrame({"weight": weights.map(lambda v: f"{v:.1%}")}))
        st.caption(f"Weights sum = {weights.sum():.1%}")

# ---- Verify panel ---------------------------------------------------------
st.header("✅ Verify")
best_single = res["asset_sharpe"].max()
ms = optima["max_sharpe"]["sharpe"]
w_sum = optima["max_sharpe"][assets].sum()
st.write(f"- Max-Sharpe weights sum to **{w_sum:.1%}** (should be 100%).")
if ms > best_single:
    st.success(
        f"- Max-Sharpe portfolio Sharpe **{ms:.2f}** > best single asset **{best_single:.2f}** "
        f"→ diversification improved risk-adjusted return (correlation < 1)."
    )
else:
    st.info(
        f"- Max-Sharpe Sharpe {ms:.2f} vs best single asset {best_single:.2f}. With few or highly "
        f"correlated assets the gain can be small — try adding assets or a longer lookback."
    )

# ---- AI chat (Codex SDK) — explains AND controls the dashboard -------------
st.header("💬 Ask AI — explain or control the dashboard")
st.caption(
    "Ask about the numbers, **or tell the AI to change the inputs** — e.g. "
    "*“set risk-free rate to 5% and use PTT.BK, KBANK.BK”* / *“จำลอง 10000 พอร์ต ย้อนหลัง 3 ปี”*."
)
import chat as chat_mod  # noqa: E402  (sibling module; sys.path set at top)

usable, status_msg = chat_mod.codex_status()
if not usable:
    st.info(status_msg)
else:
    st.caption(status_msg)
    # Ground the assistant in the *current* on-screen numbers. The Codex call runs
    # in an isolated worker process (see chat.interpret_via_subprocess), primed with
    # this context plus recent transcript each turn, so answers reference live values
    # and a crash can't take down the dashboard.
    ctx = chat_mod.portfolio_context(res)
    st.session_state.setdefault("chat_messages", [])

    for m in st.session_state.get("chat_messages", []):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    question = st.chat_input("e.g. อธิบาย max-Sharpe portfolio / set rf to 3% and use SCB.BK, PTT.BK")
    if question:
        st.session_state.chat_messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        result = {"action": "answer", "reply": "", "updates": {}}
        with st.chat_message("assistant"):
            with st.spinner("Thinking with Codex…"):
                try:
                    result = chat_mod.interpret_via_subprocess(
                        ctx, question,
                        history=st.session_state.chat_messages[:-1],  # exclude current question
                        cwd=os.getcwd(),
                    )
                except Exception as exc:  # noqa: BLE001
                    result = {
                        "action": "answer",
                        "reply": (
                            f"⚠️ Codex error: `{exc}`\n\nCheck that the Codex CLI is installed and you're "
                            "authenticated (`CODEX_API_KEY` or `codex login`). The rest of the dashboard is unaffected."
                        ),
                        "updates": {},
                    }
            st.markdown(result["reply"])
        st.session_state.chat_messages.append({"role": "assistant", "content": result["reply"]})

        if result["action"] == "update" and result["updates"]:
            pending, notes = chat_mod.to_widget_updates(result["updates"])
            if pending:
                st.session_state.pending_inputs = pending
                st.session_state.chat_messages.append(
                    {"role": "assistant", "content": "✅ Updated inputs: " + ", ".join(notes)}
                )
                st.rerun()
