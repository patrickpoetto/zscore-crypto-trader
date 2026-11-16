"""
Paper-trading in tempo reale su order-flow imbalance da order book L2 (Binance WebSocket).

Perché questo e non un altro backtest: le 4 ipotesi precedenti (exhaustion reversal, momentum,
pairs, funding rate) usavano candele da 1 minuto come miglior proxy possibile di order-flow,
e sono state tutte respinte — probabilmente perché a 1 minuto il segnale genuino si è già
consumato. L'order book L2 vero (bid/ask reali, aggiornati ogni 100ms) è l'unico modo di
testare l'ipotesi order-flow-imbalance (Cont, Kukanov & Stoikov 2014) alla sua vera scala
temporale (secondi). Binance non fornisce storico L2 gratuito: la sola via onesta di
validazione è raccogliere risultati REALI in tempo reale (paper trading, nessun ordine vero).

Segnale: Order Book Imbalance (OBI) = (bid_volume - ask_volume) / (bid_volume + ask_volume)
sui migliori N livelli. Si traccia uno z-score rolling dell'OBI (regime-relative, non soglia
assoluta) e si apre una posizione PAPER long quando l'OBI è anomalamente sbilanciato verso i
buyer, uscendo dopo un holding brevissimo (secondi) o a TP/SL stretti.

Nessun ordine reale viene mai piazzato. Ogni trade simulato viene loggato in CSV per analisi
successiva. Il processo è pensato per girare per ore/giorni in background.
"""
import asyncio
import csv
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets

SYMBOLS = ['BTCEUR', 'ETHEUR', 'BNBEUR', 'SOLEUR', 'ADAEUR', 'AVAXEUR']
DEPTH_LEVELS = 10          # livelli usati per calcolare l'OBI
OBI_HISTORY_LEN = 300      # ~30s di storico a 100ms per lo z-score rolling
OBI_ZSCORE_THRESHOLD = 2.5
MAX_HOLDING_SECONDS = 120  # v1 (15s, TP/SL 0.15%) era sbagliato: TP < fee round-trip,
                            # e in 15s i prezzi non si muovono abbastanza (std osservata ~0.035%).
                            # v2: più tempo per lasciare respirare il movimento.
TAKE_PROFIT_PERCENT = 0.4   # ben sopra le fee round-trip (0.2%), lascia margine netto reale
STOP_LOSS_PERCENT = 0.25    # risk/reward ~1.6:1, serve win rate < 50% per essere in pareggio
FEE_PERCENT = 0.1  # per lato, stima Binance spot

OUTPUT_DIR = Path(__file__).parent / 'paper_trades'
OUTPUT_DIR.mkdir(exist_ok=True)
TRADES_FILE = OUTPUT_DIR / 'orderbook_trades.csv'
HEARTBEAT_FILE = OUTPUT_DIR / 'heartbeat.json'

STREAM_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(
    f"{s.lower()}@depth{DEPTH_LEVELS}@100ms" for s in SYMBOLS
)


class SymbolState:
    def __init__(self, symbol):
        self.symbol = symbol
        self.obi_history = deque(maxlen=OBI_HISTORY_LEN)
        self.position = None  # dict con entry_price, entry_time, obi_at_entry
        self.update_count = 0

    def update(self, bids, asks):
        bid_vol = sum(float(q) for _, q in bids)
        ask_vol = sum(float(q) for _, q in asks)
        total = bid_vol + ask_vol
        obi = (bid_vol - ask_vol) / total if total > 0 else 0.0
        self.obi_history.append(obi)
        self.update_count += 1

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        return obi, best_bid, best_ask

    def obi_zscore(self, obi):
        if len(self.obi_history) < OBI_HISTORY_LEN:
            return None
        import statistics
        mean = statistics.mean(self.obi_history)
        std = statistics.pstdev(self.obi_history)
        if std == 0:
            return None
        return (obi - mean) / std


def init_csv():
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['entry_time', 'exit_time', 'symbol', 'obi_zscore_entry',
                              'entry_price', 'exit_price', 'exit_reason',
                              'pnl_percent_gross', 'pnl_percent_net'])


def log_trade(symbol, entry_time, entry_price, obi_z, exit_time, exit_price, reason):
    gross_pnl = (exit_price / entry_price - 1) * 100
    net_pnl = gross_pnl - 2 * FEE_PERCENT
    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([entry_time.isoformat(), exit_time.isoformat(), symbol,
                          f"{obi_z:.3f}", entry_price, exit_price, reason,
                          f"{gross_pnl:.4f}", f"{net_pnl:.4f}"])
    print(f"[{exit_time.strftime('%H:%M:%S')}] {symbol}: {reason} | "
          f"entry={entry_price} exit={exit_price} | pnl_netto={net_pnl:+.3f}%")


def write_heartbeat(states, trades_count):
    data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'trades_logged': trades_count,
        'updates_per_symbol': {s.symbol: s.update_count for s in states.values()},
        'open_positions': {s.symbol: s.position for s in states.values() if s.position},
    }
    with open(HEARTBEAT_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


async def run():
    init_csv()
    states = {s: SymbolState(s) for s in SYMBOLS}
    trades_count = sum(1 for _ in open(TRADES_FILE)) - 1 if TRADES_FILE.exists() else 0
    last_heartbeat = time.time()

    print(f"🔌 Connessione a {STREAM_URL[:80]}...")
    reconnect_delay = 1
    while True:
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20, ping_timeout=20) as ws:
                print("✅ Connesso. Paper-trading avviato (nessun ordine reale verrà piazzato).")
                reconnect_delay = 1
                async for message in ws:
                    data = json.loads(message)
                    stream = data.get('stream', '')
                    symbol = stream.split('@')[0].upper()
                    if symbol not in states:
                        continue
                    payload = data['data']
                    bids, asks = payload.get('bids'), payload.get('asks')
                    if not bids or not asks:
                        continue

                    state = states[symbol]
                    obi, best_bid, best_ask = state.update(bids, asks)
                    now = datetime.now(timezone.utc)

                    if state.position:
                        pos = state.position
                        held = (now - pos['entry_time']).total_seconds()
                        current_price = best_bid  # uscita: si vende al bid
                        pnl_pct = (current_price / pos['entry_price'] - 1) * 100

                        exit_reason = None
                        if pnl_pct <= -STOP_LOSS_PERCENT:
                            exit_reason = 'STOP_LOSS'
                        elif pnl_pct >= TAKE_PROFIT_PERCENT:
                            exit_reason = 'TAKE_PROFIT'
                        elif held >= MAX_HOLDING_SECONDS:
                            exit_reason = 'TIME_EXIT'

                        if exit_reason:
                            log_trade(symbol, pos['entry_time'], pos['entry_price'],
                                      pos['obi_zscore'], now, current_price, exit_reason)
                            trades_count += 1
                            state.position = None
                    else:
                        z = state.obi_zscore(obi)
                        if z is not None and z >= OBI_ZSCORE_THRESHOLD:
                            state.position = {
                                'entry_time': now,
                                'entry_price': best_ask,  # entrata: si compra all'ask
                                'obi_zscore': z,
                            }

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
