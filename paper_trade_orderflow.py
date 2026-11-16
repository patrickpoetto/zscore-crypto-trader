"""
Paper-trading in tempo reale su TRADE-FLOW IMBALANCE reale (esecuzioni, non book esposto),
versione raffinata rispetto a paper_trade_orderbook.py — vedi discussione nel log di sessione
per il razionale completo. Sintesi:

- Segnale primario: squilibrio buyer-aggressor vs seller-aggressor sulle esecuzioni reali
  (stream aggTrade di Binance, campo 'm' = isBuyerMaker → se True il buyer era maker, quindi
  il TAKER/aggressore era il seller; se False il taker era il buyer). A differenza dell'Order
  Book Imbalance (size esposta nel book), le esecuzioni non sono cancellabili: non soffrono di
  spoofing/quote-stuffing. Base teorica: Kyle (1985), Glosten-Milgrom (1985) - è il flusso di
  ordini aggressivi cumulato a tradire la presenza di informati, non la size mostrata nel book.
- Barre a volume costante (dollar bar, non barre a tempo fisso): si chiude una barra quando il
  controvalore scambiato raggiunge una soglia in USD, non dopo N secondi. Base teorica: Easley,
  Lopez de Prado & O'Hara (VPIN) - l'attività informata si concentra in raffiche, un orologio a
  tempo fisso la annacqua; l'orologio a volume si adatta automaticamente all'intensità.
- Persistenza obbligatoria: richiede uno squilibrio sostenuto su CONFIRM_BARS barre consecutive
  (media, non singolo picco) prima di entrare - un singolo print anomalo (blocco/liquidazione
  isolata) non basta.
- L'Order Book Imbalance (book esposto) resta come FILTRO SECONDARIO di conferma (non deve
  contraddire la direzione del flusso), non più come segnale primario.
- Direzione: CONTINUAZIONE (si compra il flusso in acquisto sostenuto, si vende quello in
  vendita sostenuto) - opposto della vecchia ipotesi Exhaustion Reversal (contrarian, già
  respinta). Supporta LONG e SHORT (esecuzione reale prevista su Hyperliquid perpetual).
- TP/SL ricalibrati rispetto alla v1/v2 di paper_trade_orderbook.py: quella versione aveva un
  SL netto (-0.45%) quasi doppio del TP netto (+0.2%), richiedendo >69% win rate solo per
  pareggiare - un rapporto rischio/rendimento sbagliato in partenza per un'edge sottile.
- Si logga anche MFE/MAE (massima escursione favorevole/avversa) durante l'holding, per poter
  ricalibrare onestamente TP/SL sui dati reali raccolti, senza dover rilanciare la raccolta.

Nessun ordine reale viene mai piazzato. Ogni trade paper è loggato in CSV per analisi.
"""
import asyncio
import csv
import json
import statistics
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import websockets

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'AVAXUSDT']

# Dimensione barra in controvalore USD, calibrata su un probe reale del throughput aggTrade
# (40s, vedi log di sessione): BTC ~$675/s, ETH ~$277/s, BNB ~$158/s, SOL ~$348/s, AVAX ~$3.7/s
# (molto sottile in questo momento). Target ~7s/barra per i 4 liquidi; AVAX resta più lento
# per costruzione (mercato meno attivo), si autoregola comunque nel tempo essendo a volume.
DOLLAR_BAR_SIZE = {
    'BTCUSDT': 5_000, 'ETHUSDT': 2_000, 'BNBUSDT': 1_000,
    'SOLUSDT': 2_500, 'AVAXUSDT': 300,
}

FLOW_HISTORY_LEN = 300      # barre di storico per lo z-score rolling dello squilibrio di flusso
MIN_HISTORY_FOR_SIGNAL = 100  # barre minime prima di fidarsi dello z-score
FLOW_ZSCORE_THRESHOLD = 2.0
CONFIRM_BARS = 3            # persistenza: media dello z-score sulle ultime N barre, non un picco isolato
OBI_LEVELS = 10              # livelli di book usati per l'OBI (filtro secondario)

MAX_HOLDING_SECONDS = 180
TAKE_PROFIT_PERCENT = 0.5
STOP_LOSS_PERCENT = 0.25
FEE_PERCENT = 0.1            # per lato, stima Binance spot (round-trip 0.2%)

OUTPUT_DIR = Path(__file__).parent / 'paper_trades'
OUTPUT_DIR.mkdir(exist_ok=True)
TRADES_FILE = OUTPUT_DIR / 'orderflow_trades.csv'
HEARTBEAT_FILE = OUTPUT_DIR / 'orderflow_heartbeat.json'

STREAM_URL = "wss://stream.binance.com:9443/stream?streams=" + "/".join(
    f"{s.lower()}@depth{OBI_LEVELS}@100ms/{s.lower()}@aggTrade" for s in SYMBOLS
)


class SymbolState:
    def __init__(self, symbol):
        self.symbol = symbol
        self.bar_size_usd = DOLLAR_BAR_SIZE[symbol]

        # Barra di flusso in formazione
        self.buy_notional = 0.0
        self.sell_notional = 0.0

        self.flow_history = deque(maxlen=FLOW_HISTORY_LEN)   # squilibrio di flusso per barra (-1..1)
        self.recent_zscores = deque(maxlen=CONFIRM_BARS)     # ultimi z-score per la conferma di persistenza
        self.bars_formed = 0

        self.best_bid = None
        self.best_ask = None
        self.obi = None

        self.position = None  # dict: direction, entry_time, entry_price, mfe_pct, mae_pct

    def on_agg_trade(self, price, qty, is_buyer_maker):
        notional = price * qty
        if is_buyer_maker:
            self.sell_notional += notional   # taker era il seller (buyer era maker)
        else:
            self.buy_notional += notional    # taker era il buyer

        total = self.buy_notional + self.sell_notional
        if total < self.bar_size_usd:
            return None  # barra non ancora chiusa

        flow_imbalance = (self.buy_notional - self.sell_notional) / total
        self.buy_notional = 0.0
        self.sell_notional = 0.0
        self.bars_formed += 1

        z = None
        if len(self.flow_history) >= MIN_HISTORY_FOR_SIGNAL:
            mean = statistics.mean(self.flow_history)
            std = statistics.pstdev(self.flow_history)
            if std > 0:
                z = (flow_imbalance - mean) / std

        self.flow_history.append(flow_imbalance)
        if z is not None:
            self.recent_zscores.append(z)
        else:
            self.recent_zscores.clear()

        return flow_imbalance, z

    def update_book(self, bids, asks):
        bid_vol = sum(float(q) for _, q in bids)
        ask_vol = sum(float(q) for _, q in asks)
        total = bid_vol + ask_vol
        self.obi = (bid_vol - ask_vol) / total if total > 0 else 0.0
        self.best_bid = float(bids[0][0])
        self.best_ask = float(asks[0][0])

    def check_persistent_signal(self):
        """Ritorna 'LONG', 'SHORT' o None. Richiede la MEDIA degli ultimi CONFIRM_BARS z-score
        sopra soglia nella stessa direzione (persistenza), non un singolo picco."""
        if len(self.recent_zscores) < CONFIRM_BARS:
            return None
        avg_z = sum(self.recent_zscores) / len(self.recent_zscores)
        if avg_z >= FLOW_ZSCORE_THRESHOLD and all(z > 0 for z in self.recent_zscores):
            direction = 'LONG'
        elif avg_z <= -FLOW_ZSCORE_THRESHOLD and all(z < 0 for z in self.recent_zscores):
            direction = 'SHORT'
        else:
            return None

        # Filtro secondario: l'OBI del book esposto non deve contraddire la direzione del flusso
        if self.obi is None:
            return None
        if direction == 'LONG' and self.obi < 0:
            return None
        if direction == 'SHORT' and self.obi > 0:
            return None

        return direction, avg_z


def init_csv():
    if not TRADES_FILE.exists():
        with open(TRADES_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['symbol', 'direction', 'entry_time', 'entry_price', 'flow_zscore_avg',
                              'obi_at_entry', 'exit_time', 'exit_price', 'exit_reason',
                              'holding_seconds', 'pnl_percent_net', 'mfe_percent', 'mae_percent'])


def log_trade(symbol, direction, entry_time, entry_price, flow_z, obi, exit_time, exit_price,
              reason, mfe_pct, mae_pct):
    holding_seconds = (exit_time - entry_time).total_seconds()
    if direction == 'LONG':
        gross_pnl = (exit_price / entry_price - 1) * 100
    else:
        gross_pnl = (entry_price / exit_price - 1) * 100
    net_pnl = gross_pnl - 2 * FEE_PERCENT

    with open(TRADES_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([symbol, direction, entry_time.isoformat(), entry_price, f"{flow_z:.3f}",
                          f"{obi:.4f}", exit_time.isoformat(), exit_price, reason,
                          f"{holding_seconds:.0f}", f"{net_pnl:.4f}", f"{mfe_pct:.4f}", f"{mae_pct:.4f}"])
    print(f"[{exit_time.strftime('%H:%M:%S')}] {symbol} {direction}: {reason} | "
          f"entry={entry_price} exit={exit_price} | pnl_netto={net_pnl:+.3f}% "
          f"(mfe={mfe_pct:+.3f}% mae={mae_pct:+.3f}%)")


def write_heartbeat(states, trades_count):
    data = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'trades_logged': trades_count,
        'bars_formed': {s.symbol: s.bars_formed for s in states.values()},
        'open_positions': {s.symbol: s.position for s in states.values() if s.position},
    }
    with open(HEARTBEAT_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


async def run():
    init_csv()
    states = {s: SymbolState(s) for s in SYMBOLS}
    trades_count = sum(1 for _ in open(TRADES_FILE)) - 1 if TRADES_FILE.exists() else 0
    last_heartbeat = time.time()

    print(f"🔌 Connessione a {STREAM_URL[:90]}...")
    reconnect_delay = 1
    while True:
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20, ping_timeout=20) as ws:
                print("✅ Connesso. Paper-trading order-flow avviato (nessun ordine reale verrà piazzato).")
                reconnect_delay = 1
                async for message in ws:
                    data = json.loads(message)
                    stream = data.get('stream', '')
                    symbol = stream.split('@')[0].upper()
                    if symbol not in states:
                        continue
                    state = states[symbol]
                    payload = data['data']
                    now = datetime.now(timezone.utc)

                    if '@depth' in stream:
                        bids, asks = payload.get('bids'), payload.get('asks')
                        if not bids or not asks:
                            continue
                        state.update_book(bids, asks)

                        # Gestione posizione aperta: mark-to-market su ogni tick di book
                        if state.position:
                            pos = state.position
                            current_price = state.best_bid if pos['direction'] == 'LONG' else state.best_ask
                            if pos['direction'] == 'LONG':
                                pnl_pct = (current_price / pos['entry_price'] - 1) * 100
                            else:
                                pnl_pct = (pos['entry_price'] / current_price - 1) * 100

                            pos['mfe_pct'] = max(pos['mfe_pct'], pnl_pct)
                            pos['mae_pct'] = min(pos['mae_pct'], pnl_pct)
                            held = (now - pos['entry_time']).total_seconds()

                            exit_reason = None
                            if pnl_pct <= -STOP_LOSS_PERCENT:
                                exit_reason = 'STOP_LOSS'
                            elif pnl_pct >= TAKE_PROFIT_PERCENT:
                                exit_reason = 'TAKE_PROFIT'
                            elif held >= MAX_HOLDING_SECONDS:
                                exit_reason = 'TIME_EXIT'

                            if exit_reason:
                                log_trade(symbol, pos['direction'], pos['entry_time'], pos['entry_price'],
                                          pos['flow_z'], pos['obi'], now, current_price, exit_reason,
                                          pos['mfe_pct'], pos['mae_pct'])
                                trades_count += 1
                                state.position = None

                    elif '@aggTrade' in stream:
                        price = float(payload['p'])
                        qty = float(payload['q'])
                        is_buyer_maker = bool(payload['m'])
                        result = state.on_agg_trade(price, qty, is_buyer_maker)

                        if result is not None and state.position is None:
                            signal = state.check_persistent_signal()
                            if signal is not None and state.best_bid is not None:
                                direction, avg_z = signal
                                entry_price = state.best_ask if direction == 'LONG' else state.best_bid
                                state.position = {
                                    'direction': direction, 'entry_time': now, 'entry_price': entry_price,
                                    'flow_z': avg_z, 'obi': state.obi, 'mfe_pct': 0.0, 'mae_pct': 0.0,
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
