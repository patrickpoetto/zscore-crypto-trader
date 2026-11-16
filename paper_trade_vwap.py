"""
Paper-trading in tempo reale della strategia VWAP Reclaim SHORT (VWAP + Volume + EMA200),
parametri rifiniti in backtest_vwap.py (vedi RIFINITURA), timeframe 5m.

Perché questo test dal vivo: il backtest onesto (walk-forward train/test, 5 coppie, ~90gg)
mostra un'edge SOLO marginale e non uniforme tra le coppie (PF aggregato 1.06 out-of-sample,
90 trade, ma 3/5 coppie individualmente negative - vedi strategy_vwap.py per il dettaglio).
Con un campione così piccolo non si può escludere che sia rumore statistico. L'unico modo
onesto di guadagnare fiducia PRIMA di rischiare capitale reale è raccogliere altri trade in
tempo reale, mai visti né nel tuning né nel test out-of-sample, in modalità paper (nessun
ordine reale). Stesso principio già usato in paper_trade_orderbook.py per l'ipotesi order-flow.

Metodologia IDENTICA al backtest, solo con candele live invece che storiche:
- Segnale valutato sulla barra 5m appena chiusa (nessun lookahead).
- Entry all'OPEN della barra successiva (si aspetta la sua chiusura per leggere l'open, che
  comunque non cambia durante la barra - nessuna differenza pratica).
- SL/TP valutati sull'high/low di ogni barra successiva (SL ha precedenza in caso di doppio
  tocco nella stessa barra, ipotesi conservativa, come nel backtest).
- Fee Hyperliquid taker (0.045%/lato) + slippage stimato (0.03%/lato).

Nessun ordine reale viene mai piazzato. Ogni trade paper è loggato in CSV per analisi.
"""
import asyncio
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import websockets

from strategy_vwap import VwapReclaimStrategy

SYMBOLS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'BNB': 'BNBUSDT', 'SOL': 'SOLUSDT', 'AVAX': 'AVAXUSDT'}
INTERVAL = '5m'
HISTORY_WARMUP_BARS = 600   # ~2 giorni, copre EMA200 + almeno un giorno pieno per il VWAP
MAX_HISTORY_BARS = 5000     # trim per non far crescere la memoria all'infinito (~17 giorni)
MAX_HOLDING_BARS = 576      # 2 giorni a 5m, come nel backtest

FEE_PERCENT = 0.045
SLIPPAGE_PERCENT = 0.03

# Parametri rifiniti in backtest_vwap.py (vedi sezione RIFINITURA):
# train pf=1.45 (216 trade), test out-of-sample pf=1.06 (90 trade, +0.44% yield portfolio/27gg)
STRATEGY_PARAMS = dict(
    ema_period=200, volume_ma_length=14, volume_ratio_min=1.5, risk_reward=4.0,
    stop_buffer_percent=0.05, use_trend_filter=True, stop_lookback_bars=20,
    entry_mode='cross_above', direction='short',
)

OUTPUT_DIR = Path(__file__).parent / 'paper_trades'
OUTPUT_DIR.mkdir(exist_ok=True)
TRADES_FILE = OUTPUT_DIR / 'vwap_short_trades.csv'
HEARTBEAT_FILE = OUTPUT_DIR / 'vwap_heartbeat.json'

STREAM_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(
    f"{sym.lower()}@kline_{INTERVAL}" for sym in SYMBOLS.values()
)


def fetch_warmup_history(binance_symbol: str) -> pd.DataFrame:
    """Scarica le ultime HISTORY_WARMUP_BARS candele chiuse via REST pubblico Binance,
    per avere subito EMA200 valida e almeno un giorno pieno di VWAP."""
    url = "https://api.binance.com/api/v3/klines"
    params = {'symbol': binance_symbol, 'interval': INTERVAL, 'limit': HISTORY_WARMUP_BARS}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    df = pd.DataFrame(rows, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
        'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms', utc=True).dt.tz_localize(None)
    for c in ('open', 'high', 'low', 'close', 'volume'):
        df[c] = df[c].astype(float)
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].reset_index(drop=True)


class SymbolState:
    def __init__(self, label, df_history):
        self.label = label
        self.df = df_history
        self.position = None       # dict: entry_time, entry_price, stop_loss, take_profit, entry_idx
        self.pending_entry = False  # armato dalla barra di segnale, entra alla prossima barra
        self.n_bars_seen = 0
        self.last_exit_bar_index = -1  # per non riarmare un segnale sulla stessa barra di uscita (come blocked_until nel backtest)

    def add_closed_bar(self, ts, o, h, l, c, v):
        new_row = pd.DataFrame([{'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v}])
        self.df = pd.concat([self.df, new_row], ignore_index=True)
        if len(self.df) > MAX_HISTORY_BARS:
            self.df = self.df.iloc[-MAX_HISTORY_BARS:].reset_index(drop=True)
        self.n_bars_seen += 1


def init_csv():
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['symbol', 'entry_time', 'exit_time', 'entry_price', 'stop_loss',
                              'take_profit', 'exit_price', 'exit_reason', 'holding_bars', 'pnl_percent'])


def log_trade(label, entry_time, entry_price, stop_loss, take_profit, exit_time, exit_price,
              exit_reason, holding_bars, pnl_percent):
    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([label, entry_time, exit_time, f"{entry_price:.6f}", f"{stop_loss:.6f}",
                          f"{take_profit:.6f}", f"{exit_price:.6f}", exit_reason, holding_bars,
                          f"{pnl_percent:.4f}"])
    print(f"[{exit_time}] {label}: {exit_reason} | entry={entry_price:.4f} exit={exit_price:.4f} "
          f"| pnl_netto={pnl_percent:+.3f}%")


def write_heartbeat(states, trades_count):
    data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'trades_logged': trades_count,
        'bars_seen': {s.label: s.n_bars_seen for s in states.values()},
        'open_positions': {s.label: s.position for s in states.values() if s.position},
    }
    with open(HEARTBEAT_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def check_exit(strategy, state, bar):
    """Verifica SL/TP sulla barra appena chiusa per una posizione già aperta. Ritorna True se ha chiuso."""
    pos = state.position
    is_short = strategy.direction == 'short'
    hit_sl = bar['high'] >= pos['stop_loss'] if is_short else bar['low'] <= pos['stop_loss']
    hit_tp = bar['low'] <= pos['take_profit'] if is_short else bar['high'] >= pos['take_profit']

    exit_reason, exit_price = None, None
    if hit_sl:
        exit_reason, exit_price = 'STOP_LOSS', pos['stop_loss']
    elif hit_tp:
        exit_reason, exit_price = 'TAKE_PROFIT', pos['take_profit']
    elif state.n_bars_seen - pos['entry_bar_index'] >= MAX_HOLDING_BARS:
        exit_reason, exit_price = 'TIME_EXIT', bar['close']

    if exit_reason is None:
        return False

    if is_short:
        exit_price_slip = exit_price * (1 + SLIPPAGE_PERCENT / 100.0)
        pnl_percent = (pos['entry_price'] - exit_price_slip) / pos['entry_price'] * 100 - 2 * FEE_PERCENT
    else:
        exit_price_slip = exit_price * (1 - SLIPPAGE_PERCENT / 100.0)
        pnl_percent = (exit_price_slip / pos['entry_price'] - 1) * 100 - 2 * FEE_PERCENT

    log_trade(state.label, pos['entry_time'], pos['entry_price'], pos['stop_loss'], pos['take_profit'],
              bar['timestamp'], exit_price_slip, exit_reason,
              state.n_bars_seen - pos['entry_bar_index'], pnl_percent)
    state.position = None
    state.last_exit_bar_index = state.n_bars_seen
    return True


def try_enter(strategy, state, bar):
    """Entry alla barra che segue il segnale (bar = barra appena chiusa, usata come entry)."""
    is_short = strategy.direction == 'short'
    if is_short:
        entry_price = bar['open'] * (1 - SLIPPAGE_PERCENT / 100.0)
    else:
        entry_price = bar['open'] * (1 + SLIPPAGE_PERCENT / 100.0)

    lookback = state.df.iloc[-(strategy.stop_lookback_bars + 1):-1]  # barre fino al segnale incluso, esclusa questa
    swing_ref = lookback['high'].max() if is_short else lookback['low'].min()
    stop_loss_price, take_profit_price = strategy.get_entry_levels(entry_price, swing_ref)

    degenerate = (stop_loss_price <= entry_price) if is_short else (stop_loss_price >= entry_price)
    state.pending_entry = False
    if degenerate:
        return

    state.position = {
        'entry_time': bar['timestamp'], 'entry_price': entry_price,
        'stop_loss': stop_loss_price, 'take_profit': take_profit_price,
        'entry_bar_index': state.n_bars_seen,
    }
    # La barra di entry è anche la prima barra scansionata per SL/TP nel backtest: verifica subito.
    check_exit(strategy, state, bar)


def process_closed_bar(strategy, state, o, h, l, c, v, ts):
    state.add_closed_bar(ts, o, h, l, c, v)
    bar = {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v}

    if state.pending_entry and state.position is None:
        try_enter(strategy, state, bar)
    elif state.position is not None:
        check_exit(strategy, state, bar)

    can_arm = (state.position is None and not state.pending_entry
               and state.n_bars_seen != state.last_exit_bar_index
               and len(state.df) >= strategy.ema_period + strategy.stop_lookback_bars + 5)
    if can_arm:
        df_ind = strategy.calculate_indicators(state.df)
        signal = strategy.compute_signal_mask(df_ind).iloc[-1]
        state.pending_entry = bool(signal)


async def run():
    init_csv()
    print("📥 Scaricamento storico di warmup (REST, candele chiuse)...")
    states = {}
    for label, sym in SYMBOLS.items():
        df_hist = fetch_warmup_history(sym)
        states[label] = SymbolState(label, df_hist)
        print(f"   {label}: {len(df_hist)} candele caricate, ultima {df_hist['timestamp'].iloc[-1]}")

    sym_by_stream = {sym.lower(): label for label, sym in SYMBOLS.items()}
    trades_count = sum(1 for _ in open(TRADES_FILE)) - 1 if TRADES_FILE.exists() else 0
    last_heartbeat = time.time()

    print(f"\n🔌 Connessione WebSocket a Binance ({INTERVAL})...")
    reconnect_delay = 1
    while True:
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20, ping_timeout=20) as ws:
                print("✅ Connesso. Paper-trading VWAP SHORT avviato (nessun ordine reale verrà piazzato).")
                reconnect_delay = 1
                async for message in ws:
                    data = json.loads(message)
                    stream = data.get('stream', '')
                    sym_lower = stream.split('@')[0]
                    label = sym_by_stream.get(sym_lower)
                    if label is None:
                        continue

                    k = data['data']['k']
                    if not k.get('x'):  # candela non ancora chiusa, ignora
                        continue

                    state = states[label]
                    strategy = VwapReclaimStrategy(**STRATEGY_PARAMS)
                    ts = pd.to_datetime(k['t'], unit='ms', utc=True).tz_localize(None)
                    o, h, l, c, v = float(k['o']), float(k['h']), float(k['l']), float(k['c']), float(k['v'])

                    had_position = state.position is not None
                    process_closed_bar(strategy, state, o, h, l, c, v, ts)
                    if had_position and state.position is None:
                        trades_count += 1

                    if time.time() - last_heartbeat > 30:
                        write_heartbeat(states, trades_count)
                        last_heartbeat = time.time()

        except Exception as e:
            print(f"⚠️  Connessione persa ({e}), riconnessione tra {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n🛑 Paper-trading fermato dall'utente.")
