# Zscore Crypto Trader

A Python crypto trading bot built around a **Z-score mean-reversion strategy**, with support for both **decentralized (DEX)** and **centralized (CEX)** execution, a multi-strategy backtesting suite, and tooling for paper trading and portfolio reporting.

This project was built as a personal research effort to explore quantitative trading strategies, exchange/API integration, and on-chain data analysis in Python.

## What it does

The core strategy computes a rolling **Z-score** of price relative to its moving average to detect statistically significant deviations ("oversold"/"overbought" conditions), and trades the expected reversion back to the mean. Signals can optionally be filtered by momentum, moving-average trend, and (for the DEX mode) on-chain activity metrics such as gas price trends and network utilization.

Key capabilities:

- **Mean-reversion / Z-score strategy** (`strategy.py`) with configurable lookback, moving-average period, and signal thresholds.
- **Multi-pair trading**: trade several symbols simultaneously with independent position tracking and per-pair sizing.
- **DEX mode**: execution via a private Ethereum wallet (`web3`/`eth-account`), with on-chain data pulled from Alchemy (gas price, network activity) to augment signal confidence.
- **CEX mode**: execution on Binance via `python-binance`, including testnet support — recommended for smaller trade sizes where fixed DEX gas costs would dominate.
- **Hyperliquid client** (`hyperliquid_client.py`) for perpetual futures execution on Hyperliquid.
- **Backtesting suite**: a family of standalone backtests covering the core mean-reversion strategy plus variants for breakout, funding-rate, pairs trading, trend-following, and VWAP-based approaches (`backtest*.py`).
- **Paper trading scripts**: order-book and order-flow-driven simulated trading (`paper_trade_*.py`) for testing execution logic without risking capital.
- **Reporting**: structured session reports (JSON/CSV) covering PnL, win rate, and trade history (`reporting.py`).
- **Position management**: partial take-profit, capital accumulation up to a configurable cap, and position sizing logic (`position_manager.py`).
- **Strategy research tooling**: parameter optimization and ablation scripts for breakout entries/exits (`optimize_breakout_*.py`, `research_ablation.py`).

## Tech stack

- **Python 3**
- [`python-binance`](https://github.com/sammchardy/python-binance) — Binance REST/WebSocket API client
- [`web3.py`](https://web3py.readthedocs.io/) / `eth-account` — Ethereum wallet and contract interaction
- `pandas`, `numpy` — data processing and statistics
- [`ta`](https://github.com/bukosabino/ta) — technical analysis indicators
- `python-dotenv` — environment-based configuration

## Project structure

```
.
├── bot.py                     # Main trading bot (DEX + CEX modes)
├── strategy.py                 # Core Z-score / mean-reversion strategy
├── strategy_breakout.py        # Breakout strategy variant
├── strategy_pairs.py           # Pairs-trading strategy variant
├── strategy_scalping.py        # Scalping strategy variant
├── strategy_vwap.py            # VWAP-based strategy variant
├── api_client.py                # Unified API client (Binance / DEX / Alchemy)
├── hyperliquid_client.py        # Hyperliquid perpetuals client
├── config.py                    # Environment-based configuration loader
├── position_manager.py          # Position sizing, accumulation, take-profit logic
├── reporting.py                 # Session/trade reporting (JSON/CSV)
├── backtest*.py                 # Backtesting suite (core + variants)
├── paper_trade_*.py              # Paper trading / simulated execution
├── optimize_breakout_*.py        # Parameter optimization scripts
├── research_ablation.py          # Strategy component ablation study
├── fetch_historical_data.py      # Historical OHLCV data fetcher
├── fetch_hyperliquid_candles.py  # Hyperliquid candle data fetcher
├── create_wallet.py / create_test_wallet.py  # Wallet generation (mainnet/testnet)
├── requirements.txt
└── .env.example
```

## Getting started

1. **Clone and create a virtual environment:**
   ```bash
   git clone https://github.com/patrickpoetto/zscore-crypto-trader.git
   cd zscore-crypto-trader
   python3 -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your own API keys and settings
   ```
   You will need your own:
   - Binance API key/secret (for CEX mode) — testnet keys recommended for testing
   - Alchemy API key + Ethereum wallet private key (for DEX mode)
   - Hyperliquid wallet credentials (for the Hyperliquid client)

   See `BINANCE_SETUP.md` and `TESTNET_GUIDE.md` for setup walkthroughs.

4. **Run a backtest first** (no credentials required for most backtests, only historical data):
   ```bash
   python backtest.py
   ```

5. **Run the bot** (after configuring `.env` and ideally testing on testnet):
   ```bash
   python bot.py
   ```

## Disclaimer

This is a **research and educational project**, created to explore algorithmic trading concepts, exchange API integration, and backtesting methodology. It is **not financial advice** and is **not intended for production use with real funds** without your own independent review, testing, and risk management.

- Cryptocurrency trading carries substantial risk of loss.
- Past backtest performance does not guarantee future results.
- Always test thoroughly on testnet before using real capital, and never risk funds you cannot afford to lose.
- You are solely responsible for any trading activity performed using this code, and for securing your own API keys and wallet credentials (via your own `.env` file, which is intentionally excluded from this repository).

## License

MIT — see [LICENSE](LICENSE).
