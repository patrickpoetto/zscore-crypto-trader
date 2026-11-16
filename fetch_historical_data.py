"""Scarica storico klines 1m da endpoint pubblici Binance mainnet (sola lettura, nessuna chiave necessaria).
Usato per validare la strategia di scalping con un backtest realistico, dato che il book/volumi
del testnet sono sintetici e non rappresentativi.
"""
import os
import time
import argparse
import pandas as pd
from binance.client import Client

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'AVAXUSDT', 'INJUSDT']
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume',
    'close_time', 'quote_volume', 'trades', 'taker_buy_base',
    'taker_buy_quote', 'ignore'
]


def fetch_symbol(client, symbol, days):
    start_str = f"{days} day ago UTC"
    klines = client.get_historical_klines(symbol, Client.KLINE_INTERVAL_1MINUTE, start_str)
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
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    client = Client()  # pubblico, nessuna chiave: solo dati di mercato mainnet, sola lettura

    symbols = args.symbols.split(',')
    for symbol in symbols:
        out_path = os.path.join(DATA_DIR, f"{symbol}_1m.csv")
        print(f"📥 Scarico {args.days}gg di dati 1m per {symbol}...")
        t0 = time.time()
        df = fetch_symbol(client, symbol, args.days)
        df.to_csv(out_path, index=False)
        print(f"   ✅ {len(df)} candele salvate in {out_path} ({time.time()-t0:.1f}s)")
        time.sleep(1)  # cortesia verso il rate limit pubblico


if __name__ == '__main__':
    main()
