"""
Strategia 'Exhaustion Reversal' per scalping a brevissimo termine.

Razionale scientifico (non promette certezza, cerca un'edge statistica reale):
- A orizzonti di pochi minuti il prezzo è dominato da rumore di order-flow (Kyle 1985,
  Glosten-Milgrom); nessun segnale nella letteratura seria ha accuratezza "quasi certa".
- Ciò che è documentato con edge modesta ma reale:
    * Order/trade-flow imbalance predice il breve termine (Cont, Kukanov & Stoikov 2014;
      Easley, Lopez de Prado & O'Hara - VPIN).
    * Nel crypto in particolare, mosse impulsive + volume anomalo sono spesso liquidazioni
      forzate (long/short squeeze) seguite da mean-reversion parziale ("exhaustion").
- Strategia: cerca un impulso di prezzo anomalo (z-score) accompagnato da volume anomalo e
  da uno sbilanciamento di trade-flow (proxy: taker buy/sell volume dai klines pubblici,
  senza bisogno di L2 order book), poi richiede un segno di "assorbimento" (il flow più
  recente torna verso i buyer) prima di entrare in contrarian LONG. Un filtro di trend più
  lungo evita di comprare dentro un vero trend ribassista (falling knife).
- Nota: essendo il bot spot LONG-only (nessuno short), la strategia opera solo sul lato
  BUY-the-dip-exhaustion; il fade dei rally (SELL) richiederebbe margine/futures.

Uscita: solo tramite take-profit / stop-loss / time-exit gestiti da PositionManager
(nessuna uscita "a segnale" come nella strategia Z-score originale).

ATTENZIONE — RISULTATO DELLA VALIDAZIONE (vedi backtest.py e research_ablation.py):
su 3456 combinazioni di parametri testate con walk-forward train/test su 45gg di dati reali
(7 coppie), NESSUNA mostra expectancy positiva out-of-sample. Anche l'ablazione dei singoli
filtri e l'ipotesi opposta (momentum) sono state respinte. Questo modulo è mantenuto come
riferimento di ricerca (metodologia + codice), NON è collegato al bot live e NON va usato per
trading reale così com'è. Vedi il report di sessione per i dettagli e le alternative provate.
"""
import numpy as np
import pandas as pd

# Default del modulo di ricerca (non letti da .env: questa strategia non è attiva nel bot live)
DEFAULT_IMPULSE_LOOKBACK = 3
DEFAULT_VOL_LOOKBACK = 60
DEFAULT_IMPULSE_ZSCORE_THRESHOLD = 2.5
DEFAULT_VOLUME_ZSCORE_THRESHOLD = 2.0
DEFAULT_SELL_IMBALANCE_THRESHOLD = 0.60
DEFAULT_EXHAUSTION_CONFIRM_BARS = 1
DEFAULT_TREND_FILTER_LOOKBACK = 60
DEFAULT_TREND_FILTER_MAX_DROP = 3.0
DEFAULT_STOP_LOSS_PERCENT = 0.45
DEFAULT_TAKE_PROFIT_PERCENT = 0.9
DEFAULT_MAX_HOLDING_MINUTES = 20


class ExhaustionReversalStrategy:
    """Scalping contrarian su overshoot da likely-liquidazione, confermato da trade-flow.
    NON VALIDATA: vedi nota in cima al file. Solo per ricerca/backtest."""

    def __init__(self, **overrides):
        self.impulse_lookback = overrides.get('impulse_lookback', DEFAULT_IMPULSE_LOOKBACK)
        self.vol_lookback = overrides.get('vol_lookback', DEFAULT_VOL_LOOKBACK)
        self.impulse_z_threshold = overrides.get('impulse_z_threshold', DEFAULT_IMPULSE_ZSCORE_THRESHOLD)
        self.volume_z_threshold = overrides.get('volume_z_threshold', DEFAULT_VOLUME_ZSCORE_THRESHOLD)
        self.sell_imbalance_threshold = overrides.get('sell_imbalance_threshold', DEFAULT_SELL_IMBALANCE_THRESHOLD)
        self.exhaustion_confirm_bars = overrides.get('exhaustion_confirm_bars', DEFAULT_EXHAUSTION_CONFIRM_BARS)
        self.trend_lookback = overrides.get('trend_lookback', DEFAULT_TREND_FILTER_LOOKBACK)
        self.trend_max_drop = overrides.get('trend_max_drop', DEFAULT_TREND_FILTER_MAX_DROP)
        self.stop_loss_percent = overrides.get('stop_loss_percent', DEFAULT_STOP_LOSS_PERCENT)
        self.take_profit_percent = overrides.get('take_profit_percent', DEFAULT_TAKE_PROFIT_PERCENT)
        self.max_holding_minutes = overrides.get('max_holding_minutes', DEFAULT_MAX_HOLDING_MINUTES)

        # Flag di ablazione (solo per ricerca/backtest): permettono di disattivare singoli
        # filtri per capire quanto contribuiscono davvero all'edge, invece di darli per buoni.
        self.use_volume_filter = overrides.get('use_volume_filter', True)
        self.use_exhaustion_confirm = overrides.get('use_exhaustion_confirm', True)
        self.use_trend_filter = overrides.get('use_trend_filter', True)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calcola gli indicatori necessari. Richiede colonne: close, volume, taker_buy_base, taker_sell_base."""
        min_len = max(self.vol_lookback, self.trend_lookback) + self.impulse_lookback + 1
        if len(df) < min_len:
            return None

        df = df.copy()

        # Rendimento a 1 barra e volatilità baseline (rolling, esclude la barra corrente dal lookahead
        # implicito perché rolling() a fine barra usa solo dati fino a t incluso, coerente con l'uso live)
        df['ret_1b'] = df['close'].pct_change()
        df['ret_impulse'] = df['close'] / df['close'].shift(self.impulse_lookback) - 1

        rolling_std_1b = df['ret_1b'].rolling(window=self.vol_lookback).std()
        # Scala la std a 1 barra sulla finestra dell'impulso (assunzione iid, approssimazione standard)
        expected_std_impulse = rolling_std_1b * np.sqrt(self.impulse_lookback)
        df['impulse_zscore'] = df['ret_impulse'] / expected_std_impulse.replace(0, np.nan)

        # Volume anomalo nella finestra dell'impulso vs baseline
        vol_window_sum = df['volume'].rolling(window=self.impulse_lookback).sum()
        vol_baseline_mean = vol_window_sum.rolling(window=self.vol_lookback).mean()
        vol_baseline_std = vol_window_sum.rolling(window=self.vol_lookback).std()
        df['volume_zscore'] = (vol_window_sum - vol_baseline_mean) / vol_baseline_std.replace(0, np.nan)

        # Sbilanciamento trade-flow nella finestra dell'impulso (quota venduta in aggressione)
        sell_window = df['taker_sell_base'].rolling(window=self.impulse_lookback).sum()
        df['sell_ratio_window'] = sell_window / vol_window_sum.replace(0, np.nan)

        # Flow più recente (conferma di assorbimento/esaurimento della pressione di vendita)
        buy_recent = df['taker_buy_base'].rolling(window=self.exhaustion_confirm_bars).sum()
        vol_recent = df['volume'].rolling(window=self.exhaustion_confirm_bars).sum()
        df['buy_ratio_recent'] = buy_recent / vol_recent.replace(0, np.nan)

        # Filtro di trend di contesto (più lungo dell'impulso): evita di comprare in un trend forte al ribasso
        df['trend_return'] = df['close'] / df['close'].shift(self.trend_lookback) - 1

        return df

    def evaluate_row(self, row) -> tuple:
        """
        Valuta una singola riga (già dotata di indicatori) e ritorna (signal, confidence).
        Riutilizzato sia da get_signal/get_confidence (live, su DataFrame) sia dal backtest
        (che itera righe precomputate senza risliceare il DataFrame ad ogni barra).
        """
        required = ('impulse_zscore', 'volume_zscore', 'sell_ratio_window', 'buy_ratio_recent', 'trend_return')
        for c in required:
            v = row[c] if hasattr(row, '__getitem__') else getattr(row, c)
            if pd.isna(v):
                return 'HOLD', 0.0

        impulse_zscore = row['impulse_zscore']
        volume_zscore = row['volume_zscore']
        sell_ratio_window = row['sell_ratio_window']
        buy_ratio_recent = row['buy_ratio_recent']
        trend_return = row['trend_return']

        # 1. Impulso ribassista anomalo
        impulse_down = impulse_zscore <= -self.impulse_z_threshold
        # 2. Volume anomalo (partecipazione reale, non rumore) - disattivabile per ablazione
        volume_spike = (volume_zscore >= self.volume_z_threshold) if self.use_volume_filter else True
        # 3. L'impulso è dominato da vendite aggressive (coerente con liquidazioni/panico)
        sell_dominated = sell_ratio_window >= self.sell_imbalance_threshold
        # 4. Segno di assorbimento: il flow più recente non è più a dominanza sell - disattivabile
        exhaustion_confirmed = (buy_ratio_recent >= 0.5) if self.use_exhaustion_confirm else True
        # 5. Filtro di trend: evita di comprare dentro un trend ribassista forte - disattivabile
        trend_not_opposing = (trend_return >= -self.trend_max_drop / 100.0) if self.use_trend_filter else True

        if not (impulse_down and volume_spike and sell_dominated and exhaustion_confirmed and trend_not_opposing):
            return 'HOLD', 0.0

        impulse_strength = min(1.0, max(0.0, (abs(impulse_zscore) - self.impulse_z_threshold) / self.impulse_z_threshold))
        volume_strength = min(1.0, max(0.0, (volume_zscore - self.volume_z_threshold) / self.volume_z_threshold))
        flow_strength = min(1.0, max(0.0, (sell_ratio_window - self.sell_imbalance_threshold) / (1 - self.sell_imbalance_threshold)))
        confidence = round((impulse_strength + volume_strength + flow_strength) / 3.0, 4)

        return 'BUY', confidence

    def compute_signal_mask(self, df: pd.DataFrame) -> pd.Series:
        """Versione vettoriale di evaluate_row su tutto il DataFrame (per backtest veloce)."""
        impulse_down = df['impulse_zscore'] <= -self.impulse_z_threshold
        volume_spike = (df['volume_zscore'] >= self.volume_z_threshold) if self.use_volume_filter else True
        sell_dominated = df['sell_ratio_window'] >= self.sell_imbalance_threshold
        exhaustion_confirmed = (df['buy_ratio_recent'] >= 0.5) if self.use_exhaustion_confirm else True
        trend_not_opposing = (df['trend_return'] >= -self.trend_max_drop / 100.0) if self.use_trend_filter else True
        required = ['impulse_zscore', 'volume_zscore', 'sell_ratio_window', 'buy_ratio_recent', 'trend_return']
        not_na = df[required].notna().all(axis=1)
        return not_na & impulse_down & volume_spike & sell_dominated & exhaustion_confirmed & trend_not_opposing

    def get_signal(self, df: pd.DataFrame) -> str:
        """Ritorna 'BUY' o 'HOLD'. Nessun segnale SELL: le uscite sono gestite da TP/SL/time-exit."""
        if df is None or len(df) < 2:
            return 'HOLD'
        signal, _ = self.evaluate_row(df.iloc[-1])
        return signal

    def get_confidence(self, df: pd.DataFrame) -> float:
        """Confidence 0-1 basata sull'intensità combinata dei segnali (solo se il segnale è BUY)."""
        if df is None or len(df) < 2:
            return 0.0
        _, confidence = self.evaluate_row(df.iloc[-1])
        return confidence

    def get_entry_levels(self, entry_price: float) -> tuple:
        """Calcola stop-loss e take-profit assoluti in base ai parametri configurati."""
        stop_loss_price = entry_price * (1 - self.stop_loss_percent / 100.0)
        take_profit_price = entry_price * (1 + self.take_profit_percent / 100.0)
        return stop_loss_price, take_profit_price
