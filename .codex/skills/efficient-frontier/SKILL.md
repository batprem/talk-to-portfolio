---
name: efficient-frontier
description: >-
  Build an efficient frontier and find the optimal portfolio (min-variance and
  max-Sharpe) from a set of assets, then show it as an interactive Streamlit
  dashboard. Use this whenever the user wants portfolio optimization, asset
  allocation, diversification analysis, a risk-return / Markowitz / mean-variance
  frontier, "the best mix of stocks", or to compare how weighting several
  tickers changes portfolio risk and return — even if they don't say the words
  "efficient frontier". Works online (yfinance) or fully offline from a CSV of
  prices.
author: Claude
version: 1.0.0
---

# Efficient Frontier

Compute the efficient frontier for a basket of assets, mark the min-variance and
max-Sharpe portfolios, and present it as a live Streamlit dashboard. This is
Lab 3.2 of the "Claude Code for Finance" workshop — the teaching point is that
the frontier curves because assets don't move together (correlation < 1), so a
diversified basket beats putting every egg in one basket.

## Expected inputs

Everything has a sensible default so the skill can run end-to-end, but **ask the
user about anything below that is unclear from their request** before running —
these choices change the result and the teaching value.

| Input | Default | Ask when… |
|---|---|---|
| **Assets (tickers)** | `ABC,XYZ` offline / `PTT.BK,CPALL.BK,KBANK.BK,ADVANC.BK` online | the user hasn't named which assets — the frontier is meaningless without knowing them |
| **Data source** | auto: offline CSV, or online if tickers look like real market symbols | ambiguous whether they want live data or the workshop dataset |
| **Risk-free rate** | `2%` (0.02) | they care about Sharpe and haven't given a rate (Thai policy rate ≈ 2–2.5%) |
| **Lookback period** (online only) | `5y` | they mention a specific horizon; irrelevant offline (CSV is fixed) |
| **# simulated portfolios** | `5000` | rarely — only if they want a denser/sparser cloud |
| **Weight constraints** | long-only, no cap | they mention a max position size (e.g. "no more than 40% in one stock") |

### Interview guidance

Don't interrogate — a single short batch of questions is enough, and skip any
the user already answered. A good opening when the request is bare (e.g. "make
me an efficient frontier"):

> Which assets should I use, and should I pull live prices (yfinance) or use the
> workshop's offline dataset (ABC/XYZ)? I'll assume a 2% risk-free rate and 5
> years of history unless you'd like different.

If the user names Thai/US tickers, default to **online**. If they say "offline",
"use the dataset", mention `datasets/stock_prices.csv`, or the network is
blocked, use **offline** with tickers `ABC` and `XYZ`. The offline path only has
2 assets, which still produces the classic smooth 2-asset frontier curve.

## Workflow

1. **Resolve inputs** using the table above; ask only for what's genuinely
   missing.
2. **Sanity-check the numbers first (Verify), before the dashboard.** Run the
   compute module in print-only mode so you and the user can see the weights,
   returns, and Sharpe:
   ```bash
   uv run --with yfinance --with pandas --with numpy \
     python .claude/skills/efficient-frontier/scripts/frontier.py \
     --source offline --tickers ABC,XYZ --rf 0.02
   ```
   Confirm the optimal weights sum to 100% and that the max-Sharpe portfolio's
   Sharpe beats the best single asset — that's the diversification lesson.
3. **Launch the dashboard:**
   ```bash
   uv run --with streamlit --with plotly --with yfinance --with pandas --with numpy --with openai-codex \
     streamlit run .claude/skills/efficient-frontier/scripts/app.py
   ```
   Run it from the repo root so the default CSV path resolves. Tell the user the
   local URL Streamlit prints (usually http://localhost:8501) and that every
   sidebar input recomputes the charts live. (`openai-codex` is only needed for
   the optional AI chat — drop that `--with` if you don't want it.)

The dashboard shows: the portfolio cloud coloured by Sharpe, the frontier curve
(a smooth analytic sweep when there are exactly 2 assets), the min-variance and
max-Sharpe markers, the individual assets for reference, a weights table for
each optimal portfolio, a **Verify** panel, and an **AI chat** panel.

## AI chat — explain *and* control the dashboard (Codex SDK)

`scripts/chat.py` adds a "💬 Ask AI — explain or control the dashboard" panel.
Students can do two things in plain language (Thai or English), from the same box:

1. **Ask about the result** — "อธิบาย max-Sharpe portfolio", "why is XYZ weighted
   near zero?", "what is a Sharpe ratio?". Answers reference the *current*
   on-screen weights/returns, not generic finance boilerplate.
2. **Change the inputs** — "set risk-free rate to 5% and use PTT.BK, KBANK.BK",
   "จำลอง 10000 พอร์ต ย้อนหลัง 3 ปี", "cap each stock at 40%", "go offline". The
   AI updates the matching sidebar inputs and the charts recompute — the "AI
   drives the dashboard" moment.

How it works:
- Every message goes to Codex, which replies with a small JSON action
  (`{action, updates, reply}`). `action="update"` carries the changed inputs;
  `action="answer"` is a plain explanation. `chat.py` validates/clamps the
  requested values (e.g. a bad lookback is dropped, `n_portfolios` is clamped to
  1000–20000) so a control command can never push a widget out of range.
- Applied updates are queued in `st.session_state["pending_inputs"]` and consumed
  at the top of the next run, *before* the keyed sidebar widgets are built — the
  only point where Streamlit lets you set a widget's value programmatically.
- Controllable inputs: **source, tickers, risk-free rate, lookback, #
  portfolios, weight cap, and seed** (all of the sidebar).
- Each turn re-primes a fresh Codex thread with the current portfolio context
  **plus the recent transcript**, so answers reference live numbers with short-term
  memory. The visible transcript is **kept** across a chat-driven recompute, so it
  doesn't erase the conversation that triggered it.
- **The Codex call runs in an isolated worker process** (`chat_worker.py`, launched
  by `chat.interpret_via_subprocess` with `start_new_session=True`). This is
  required: calling the Codex SDK directly inside Streamlit hard-kills the whole
  server (Codex's sandbox tooling signals its process group, which — without a new
  session — also kills the co-located Streamlit). Isolating it means a Codex crash
  only kills the child and shows a graceful in-chat error.
- It runs in a **read-only sandbox** (`Sandbox.read_only`) — the assistant reads
  to answer and emits input changes as data; it never modifies files. The UI
  changes happen in Streamlit session state, not on disk.
- The panel **degrades gracefully**: if the SDK or credentials are missing it
  shows setup instructions instead of erroring, and the rest of the dashboard is
  unaffected. (Control is Codex-only; on a fully blocked venue network students
  still change inputs manually in the sidebar.)

Enabling it (optional):
1. Install the SDK — `pip install openai-codex` (or the `--with openai-codex`
   above). It may also need the Codex CLI/app-server; install per OpenAI's docs.
2. Authenticate — set `CODEX_API_KEY` (an OpenAI Platform key, billed at API
   rates) **or** run `codex login` to sign in with ChatGPT.
3. Chat needs network access, so it won't work on a fully blocked venue network —
   that's expected for any live-AI feature; the charts still work offline.

## What the code does (so you can explain or extend it)

`scripts/frontier.py` is dependency-light (numpy/pandas + optional yfinance) and
holds all the math:

- `load_prices` — yfinance download, or pivot the long-format CSV
  (`Date,Ticker,Close`) to wide. **Auto-falls back to the CSV** if an online
  fetch fails, so a blocked venue network never breaks the demo.
- `compute_stats` — annualized returns (`mean × 252`), covariance (`× 252`),
  volatility (`std × √252`) from daily returns.
- `simulate_portfolios` — Monte-Carlo of random long-only weights (Dirichlet),
  with an optional per-asset weight cap.
- `find_optima` — picks min-variance and max-Sharpe from the cloud.
- `two_asset_curve` — the smooth analytic frontier for the 2-asset case.

`scripts/app.py` is the Streamlit UI; it imports `frontier.py` and does no math
of its own. Method is Monte-Carlo (not a scipy solver) on purpose — it makes the
"cloud + curve" concept visible, and keeps dependencies to what the workshop venv
already ships.

## Verify (always do this)

The workshop principle is "Claude Code is your analyst intern, not your
calculator" — never present the frontier without checking it:

- **Do the optimal weights sum to 100%?** (long-only, no leverage)
- **Is the max-Sharpe Sharpe higher than any single asset's Sharpe?** It should
  be, because correlation < 1 lets diversification cut risk without cutting
  return proportionally. If it isn't higher, the assets are too few or too
  correlated — say so and suggest adding assets or a longer lookback.

## Notes

- **Offline fallback is mandatory** (workshop convention): the default path uses
  `datasets/stock_prices.csv`, and even the online path degrades to it on failure.
- If the user then wants a combined **wealth dashboard** (allocation pie + goal
  projection + rebalancing, Lab 3.3), the max-Sharpe weights from here are the
  hand-off; that's a separate skill/step.
