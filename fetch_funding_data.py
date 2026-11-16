"""Scarica lo storico del funding rate dei perpetual Binance (endpoint pubblico futures,
nessuna chiave necessaria). Richiesto da backtest_funding.py, che si aspetta un file
data/{symbol}_funding.csv per ciascun simbolo (insieme al prezzo 1h, vedi
fetch_historical_data.py --interval 1h).
"""
import os
import time
import argparse
import pandas as pd
from binance.client import Client

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'AVAXUSDT', 'INJUSDT']
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')


def fetch_funding(client, symbol, limit=1000):
    """Il funding stampa ogni 8h: limit=1000 (massimo per chiamata) copre ~333 giorni,
    più che sufficiente per sovrapporsi allo storico prezzo 1h scaricato in parallelo."""
    records = client.futures_funding_rate(symbol=symbol, limit=limit)
    df = pd.DataFrame(records)
    df['fundingRate'] = df['fundingRate'].astype(float)
    df['fundingTime'] = pd.to_datetime(df['fundingTime'], unit='ms')
    return df[['symbol', 'fundingTime', 'fundingRate']].sort_values('fundingTime').reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description='Scarica storico funding rate pubblico Binance futures')
    parser.add_argument('--symbols', type=str, default=','.join(SYMBOLS), help='Simboli separati da virgola')
    args = parser.parse_args()

    os.makedirs(DATA_DIR, exist_ok=True)
    client = Client()  # pubblico, nessuna chiave: solo dati di mercato futures, sola lettura

    for symbol in args.symbols.split(','):
        out_path = os.path.join(DATA_DIR, f"{symbol}_funding.csv")
        print(f"📥 Scarico storico funding rate per {symbol}...")
        df = fetch_funding(client, symbol)
        df.to_csv(out_path, index=False)
        print(f"   ✅ {len(df)} stampe salvate in {out_path} "
              f"({df['fundingTime'].iloc[0].date()} -> {df['fundingTime'].iloc[-1].date()})")
        time.sleep(0.5)  # cortesia verso il rate limit pubblico


if __name__ == '__main__':
    main()
