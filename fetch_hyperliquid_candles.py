"""Scarica candele storiche 5m da Hyperliquid (dati pubblici, sola lettura, nessuna chiave)
per il backtest della strategia Donchian+LWTI+Volume."""
import time
import argparse
import pandas as pd
from hyperliquid.info import Info
from hyperliquid.utils import constants

COINS = ['BTC', 'ETH', 'BNB', 'SOL', 'AVAX']
MAX_CANDLES_PER_REQUEST = 5000
INTERVAL_MINUTES = 5


def fetch_coin(info, coin, days):
    now = int(time.time() * 1000)
    total_ms = days * 24 * 3600 * 1000
    start = now - total_ms

    all_candles = []
    chunk_ms = MAX_CANDLES_PER_REQUEST * INTERVAL_MINUTES * 60 * 1000
    cursor = start
    while cursor < now:
        chunk_end = min(cursor + chunk_ms, now)
        candles = info.candles_snapshot(name=coin, interval='5m', startTime=cursor, endTime=chunk_end)
        if candles:
            all_candles.extend(candles)
        cursor = chunk_end + 1
        time.sleep(0.3)

    df = pd.DataFrame(all_candles)
    df = df.drop_duplicates(subset='t').sort_values('t').reset_index(drop=True)
    df['timestamp'] = pd.to_datetime(df['t'], unit='ms')
    for col in ['o', 'h', 'l', 'c', 'v']:
        df[col] = df[col].astype(float)
    df = df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume', 'n': 'trades'})
    return df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'trades']]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=120)
    parser.add_argument('--coins', type=str, default=','.join(COINS))
    args = parser.parse_args()

    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    for coin in args.coins.split(','):
        print(f"📥 Scarico {args.days}gg di candele 5m per {coin}...")
        df = fetch_coin(info, coin, args.days)
        out_path = f'data/hl_{coin}_5m.csv'
        df.to_csv(out_path, index=False)
        print(f"   ✅ {len(df)} candele salvate in {out_path}")
