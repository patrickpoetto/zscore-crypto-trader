"""
Indicatori per la strategia breakout Donchian + LWTI + Volume, replicati per corrispondere
esattamente al setup TradingView descritto dall'utente.

LWTI (Larry Williams Large Trade Index / LWPI): formula confermata dall'utente —
    momentum   = SMA(close - close[period], period)
    range_avg  = SMA(high - low, period)
    lwti_raw   = (momentum / range_avg) * 50 + 50
    lwti       = SMA(lwti_raw, smoothing_period)
    colore     = verde se lwti > lwti[1] (in salita), rosso altrimenti (pendenza, non soglia a 50)
"""
import pandas as pd


def donchian_channel(df: pd.DataFrame, length: int = 96) -> pd.DataFrame:
    """Upper = massimo high su `length` barre, Lower = minimo low, Middle = media dei due.
    Usa solo dati fino alla barra corrente inclusa (nessun lookahead)."""
    df = df.copy()
    df['donchian_upper'] = df['high'].rolling(window=length).max()
    df['donchian_lower'] = df['low'].rolling(window=length).min()
    df['donchian_middle'] = (df['donchian_upper'] + df['donchian_lower']) / 2
    return df


def lwti(df: pd.DataFrame, period: int = 25, smoothing_period: int = 20) -> pd.DataFrame:
    df = df.copy()
    momentum = (df['close'] - df['close'].shift(period)).rolling(window=period).mean()
    range_avg = (df['high'] - df['low']).rolling(window=period).mean()
    lwti_raw = (momentum / range_avg) * 50 + 50
    df['lwti'] = lwti_raw.rolling(window=smoothing_period).mean()
    df['lwti_green'] = df['lwti'] > df['lwti'].shift(1)
    return df


def volume_with_ma(df: pd.DataFrame, ma_length: int = 30) -> pd.DataFrame:
    """Volume + sua media mobile. Barra 'verde' = candela rialzista (close > open),
    convenzione standard TradingView per la colorazione delle barre di volume."""
    df = df.copy()
    df['volume_ma'] = df['volume'].rolling(window=ma_length).mean()
    df['volume_above_ma'] = df['volume'] > df['volume_ma']
    df['volume_green'] = df['close'] > df['open']
    return df


def calculate_all(df: pd.DataFrame, donchian_length: int = 96, lwti_period: int = 25,
                   lwti_smoothing: int = 20, volume_ma_length: int = 30,
                   trend_ma_length: int = 200) -> pd.DataFrame:
    """Applica tutti gli indicatori in sequenza. trend_ma_length: MA di contesto più ampia,
    usata solo come filtro opzionale per rinforzare l'ingresso (non fa parte del setup originale)."""
    df = donchian_channel(df, donchian_length)
    df = lwti(df, lwti_period, lwti_smoothing)
    df = volume_with_ma(df, volume_ma_length)
    df['trend_ma'] = df['close'].rolling(window=trend_ma_length).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    return df
