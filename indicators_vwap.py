"""Indicatori per la strategia VWAP + Volume + EMA200.

VWAP: ancorato al giorno (reset a mezzanotte UTC, convenzione standard per un mercato 24/7
senza vera "sessione" - stessa scelta di TradingView quando si usa VWAP su crypto).
    typical_price = (high + low + close) / 3
    vwap_t = cumsum(typical_price * volume) / cumsum(volume), cumulato dall'inizio del giorno.

EMA200: media mobile esponenziale di lungo periodo, filtro di trend macro (Faber 2007,
già usata in backtest_trend_equity.py come MA semplice; qui EMA come richiesto).

Volume: media mobile del volume + rapporto volume/media, per confermare che un rientro sul
VWAP sia accompagnato da reale partecipazione (non un drift a basso volume).
"""
import pandas as pd


def daily_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP ancorato al giorno UTC. Nessun lookahead: cumsum entro il giorno usa solo dati
    fino alla barra corrente inclusa."""
    df = df.copy()
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    tpv = typical_price * df['volume']
    day = df['timestamp'].dt.date
    cum_tpv = tpv.groupby(day).cumsum()
    cum_vol = df['volume'].groupby(day).cumsum()
    df['vwap'] = cum_tpv / cum_vol
    return df


def ema(df: pd.DataFrame, period: int = 200, column: str = 'close', out: str = 'ema') -> pd.DataFrame:
    df = df.copy()
    df[out] = df[column].ewm(span=period, adjust=False).mean()
    # Prime `period` barre non hanno abbastanza storia per essere affidabili: le scartiamo
    # a valle tramite dropna sulle colonne indicatori, coerente col resto del progetto.
    df.loc[df.index[:period], out] = pd.NA
    return df


def volume_with_ma(df: pd.DataFrame, ma_length: int = 20) -> pd.DataFrame:
    df = df.copy()
    df['volume_ma'] = df['volume'].rolling(window=ma_length).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    return df


def calculate_all(df: pd.DataFrame, ema_period: int = 200, volume_ma_length: int = 20) -> pd.DataFrame:
    df = daily_vwap(df)
    df = ema(df, ema_period, 'close', 'ema200')
    df = volume_with_ma(df, volume_ma_length)
    return df
