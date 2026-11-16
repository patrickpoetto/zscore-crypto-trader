"""Scarica storico klines da endpoint pubblici Binance mainnet (sola lettura, nessuna chiave necessaria).
Usato per validare le varie strategie con un backtest realistico, dato che il book/volumi
del testnet sono sintetici e non rappresentativi.

Di default scarica klines 1m (per gli script di scalping/breakout/vwap/pairs). Con --interval
1h o 1d si possono generare anche i file richiesti da backtest_funding.py (prezzo 1h) e da
backtest_trend.py / backtest_trend_equity.py (prezzo giornaliero, tipicamente su pair *EUR).
"""
import os
import time
import argparse
import pandas as pd
from binance.client import Client

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'AVAXUSDT', 'INJUSDT']
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

INTERVAL_MAP = {
    '1m': Client.KLINE_INTERVAL_1MINUTE,
    '1h': Client.KLINE_INTERVAL_1HOUR,
    '1d': Client.KLINE_INTERVAL_1DAY,
}

COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume',
    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
    'taker_buy_quote', 'ignore'
]


def fetch_symbol(client, symbol, days, interval):
    start_str = f"{days} day ago UTC"
    klines = client.get_historical_klines(symbol, interval, start_str)
    df = pd.DataFrame(klines, columns=COLUMNS)
    for col in ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_buy_base']:
        df[col] = df[col].astype(float)
    df['trades'] = df['trades'].astype(int)
    df['taker_sell_base'] = df['volume'] - df['taker_buy_base']
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume',
                'quote_volume', 'trades', 'taker_buy_base', 'taker_sell_base']]


def main():
    parser = argparse.ArgumentParser(description='Scarica storico klines pubblici Binance mainnet')
    parser.add_argument('--days', type=int, default=45, help='Giorni di storico da scaricare (default 45)')
    parser.add_argument('--symbols', type=str, default=','.join(SYMBOLS), help='Simboli separati da virgola')
    parser.add_argument('--interval', type=str, default='1m', choices=sorted(INTERVAL_MAP),
                         help="Timeframe delle candele: 1m (default, per scalping/breakout/vwap/pairs), "
                              "1h (per backtest_funding.py) o 1d (per backtest_trend*.py, es. su pair *EUR)")
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    client = Client()  # pubblico, nessuna chiave: solo dati di mercato mainnet, sola lettura
    interval = INTERVAL_MAP[args.interval]

    symbols = args.symbols.split(',')
    for symbol in symbols:
        out_path = os.path.join(DATA_DIR, f"{symbol}_{args.interval}.csv")
        print(f"📥 Scarico {args.days}gg di dati {args.interval} per {symbol}...")
        t0 = time.time()
        df = fetch_symbol(client, symbol, args.days, interval)
        df.to_csv(out_path, index=False)
        print(f"   ✅ {len(df)} candele salvate in {out_path} ({time.time()-t0:.1f}s)")
        time.sleep(1)  # cortesia verso il rate limit pubblico


if __name__ == '__main__':
    main()
