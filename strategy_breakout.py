"""
Strategia breakout Donchian + LWTI + Volume, esattamente come descritta:

- Donchian Channel(96): banda superiore/inferiore/centrale
- LWTI(25, smoothing 20): conferma di momentum (deve essere "verde", cioè in salita)
- Volume + sua media mobile(30): la barra di volume deve essere sopra la MA E verde
  (candela rialzista)

Entry: quando il prezzo (high della barra) tocca/supera la banda superiore Donchian, CON
LWTI verde e volume verde sopra la sua media, sulla stessa barra.
Stop-loss: banda centrale Donchian (al momento del segnale).
Take-profit: rapporto rischio/rendimento 2:1 (TP = entry + 2 * (entry - SL)).

Solo LONG (coerente con l'operatività spot/perp-long del bot).
"""
import pandas as pd
from indicators_breakout import calculate_all


class DonchianLWTIBreakoutStrategy:
    def __init__(self, donchian_length=96, lwti_period=25, lwti_smoothing=20,
                 volume_ma_length=30, risk_reward=2.0, trend_ma_length=200,
                 require_close_breakout=False, lwti_min_level=None,
                 volume_ratio_min=1.0, use_trend_filter=False):
        """
        Parametri di rinforzo ingresso (tutti disattivati di default = setup originale):
          require_close_breakout: se True, richiede la CHIUSURA (non solo il massimo) oltre
                                   la banda superiore - filtra i falsi breakout a wick.
          lwti_min_level: se impostato (es. 50), richiede anche LWTI sopra questo livello,
                          non solo in salita.
          volume_ratio_min: soglia minima volume/media volume (1.0 = originale, "sopra media";
                             >1.0 richiede un vero spike, non solo marginalmente sopra).
          use_trend_filter: se True, richiede il prezzo sopra la media mobile di contesto
                             (trend_ma_length) - evita breakout contro il trend più ampio.
        """
        self.donchian_length = donchian_length
        self.lwti_period = lwti_period
        self.lwti_smoothing = lwti_smoothing
        self.volume_ma_length = volume_ma_length
        self.risk_reward = risk_reward
        self.trend_ma_length = trend_ma_length
        self.require_close_breakout = require_close_breakout
        self.lwti_min_level = lwti_min_level
        self.volume_ratio_min = volume_ratio_min
        self.use_trend_filter = use_trend_filter

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return calculate_all(df, self.donchian_length, self.lwti_period,
                              self.lwti_smoothing, self.volume_ma_length, self.trend_ma_length)

    def compute_signal_mask(self, df: pd.DataFrame) -> pd.Series:
        if self.require_close_breakout:
            touch_upper = df['close'] >= df['donchian_upper']
        else:
            touch_upper = df['high'] >= df['donchian_upper']

        lwti_ok = df['lwti_green'] == True
        if self.lwti_min_level is not None:
            lwti_ok = lwti_ok & (df['lwti'] >= self.lwti_min_level)

        volume_ok = df['volume_green'] & (df['volume_ratio'] >= self.volume_ratio_min)

        required = ['donchian_upper', 'donchian_middle', 'lwti', 'lwti_green', 'volume_ma', 'volume_ratio']
        if self.use_trend_filter:
            required = required + ['trend_ma']
        not_na = df[required].notna().all(axis=1)

        signal = not_na & touch_upper & lwti_ok & volume_ok
        if self.use_trend_filter:
            signal = signal & (df['close'] > df['trend_ma'])

        return signal

    def get_entry_levels(self, entry_price: float, donchian_middle: float) -> tuple:
        """SL = banda centrale Donchian al momento del segnale. TP = risk/reward configurato."""
        stop_loss_price = donchian_middle
        risk = entry_price - stop_loss_price
        take_profit_price = entry_price + self.risk_reward * risk
        return stop_loss_price, take_profit_price
