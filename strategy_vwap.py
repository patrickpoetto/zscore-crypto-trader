"""Strategia 'VWAP Reclaim' — VWAP + Volume + EMA200.

Razionale: in un trend rialzista di fondo (prezzo sopra EMA200), il VWAP di giornata agisce
spesso da supporto dinamico dove entrano gli operatori istituzionali (è il prezzo medio
ponderato per volume a cui è stato scambiato il grosso del volume odierno). Un pullback che
tocca/rompe il VWAP intrabar ma chiude di nuovo sopra, con volume superiore alla media, è
un pattern di "difesa del VWAP" documentato nella prassi di trading intraday (VWAP come
riferimento istituzionale, Berkowitz, Logue & Noser 1988 sull'uso del VWAP come benchmark
di esecuzione - qui usato come proxy di interesse reale all'acquisto, non solo di benchmark).

Entry (solo LONG, coerente con l'operatività spot/perp-long del bot):
  1. Trend: close > EMA200 (disattivabile per ablazione)
  2. Pullback: low della barra <= VWAP (il prezzo ha toccato/rotto il VWAP intrabar)
  3. Reclaim: close della barra > VWAP (richiusura sopra)
  4. Candela rialzista: close > open
  5. Volume: volume/volume_ma >= volume_ratio_min (disattivabile per ablazione, soglia 0)

Stop-loss: minimo dello swing recente (stop_lookback_bars, meno un piccolo buffer). Take-profit:
rischio/rendimento configurato. Esecuzione all'open della barra successiva (nessun lookahead).

ATTENZIONE — RISULTATO DELLA VALIDAZIONE (vedi backtest_vwap.py): su timeframe 5m, 256
combinazioni (volume_ma_length, volume_ratio_min, risk_reward, stop_lookback_bars,
entry_mode, direction long/short) testate con walk-forward train/test su ~90gg di dati
reali (5 coppie).

- LONG (VWAP come supporto in uptrend): la migliore su train resta a expectancy negativa
  (pf 0.79) e peggiora out-of-sample (pf 0.51).
- SHORT (setup speculare: VWAP come resistenza in downtrend, entry_mode='cross_above' cioè
  cross_below, risk_reward=3.0, stop_lookback_bars=10): pf 1.24 su train (250 trade) ma
  scende a pf 0.86 out-of-sample (92 trade, expectancy -0.07%/trade) — vicino al pareggio ma
  ancora sotto, non un'edge affidabile. L'ablazione mostra che qui volume e trend EMA200
  contribuiscono davvero (senza di essi pf scende a ~1.0 già su train).
- Su timeframe 1h (solo long testato) una variante mostra un'apparente edge su train (pf
  1.52, 76 trade) che collassa out-of-sample (pf 0.56) — overfitting su campione piccolo.

Nessuna configurazione provata (long o short, 5m o 1h) supera la validazione onesta in modo
robusto. Il lato short è il più vicino al pareggio ma resta leggermente negativo out-of-sample.
Questo modulo è mantenuto come riferimento di ricerca (metodologia + codice), NON è collegato
al bot live e NON va usato per trading reale così com'è.
"""
import pandas as pd
from indicators_vwap import calculate_all


class VwapReclaimStrategy:
    def __init__(self, ema_period=200, volume_ma_length=20, volume_ratio_min=1.0,
                 risk_reward=2.0, stop_buffer_percent=0.05, use_trend_filter=True,
                 stop_lookback_bars=1, entry_mode='touch_reclaim', direction='long'):
        self.ema_period = ema_period
        self.volume_ma_length = volume_ma_length
        self.volume_ratio_min = volume_ratio_min
        self.risk_reward = risk_reward
        self.stop_buffer_percent = stop_buffer_percent
        self.use_trend_filter = use_trend_filter
        # stop_lookback_bars > 1: SL sul minimo/massimo di uno swing di N barre (invece della
        # sola barra di segnale), per non farsi bruciare da un wick di rumore.
        self.stop_lookback_bars = stop_lookback_bars
        # entry_mode (long):  'touch_reclaim' low<=vwap poi close>vwap; 'cross_above' close
        #                     era <=vwap alla barra prima e ora chiude sopra (breakout media).
        # entry_mode (short): specchio - 'touch_reclaim' high>=vwap poi close<vwap (rigetto);
        #                     'cross_above' interpretato come 'cross_below' (rottura verso il basso).
        self.entry_mode = entry_mode
        # direction: 'long' (setup originale, VWAP come supporto in uptrend) o 'short' (setup
        # speculare, VWAP come resistenza in downtrend - richiede short/perp, non spot).
        self.direction = direction

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return calculate_all(df, self.ema_period, self.volume_ma_length)

    def compute_signal_mask(self, df: pd.DataFrame) -> pd.Series:
        if self.direction == 'short':
            if self.entry_mode == 'cross_above':  # cross_below per lo short
                price_trigger = (df['close'].shift(1) >= df['vwap'].shift(1)) & (df['close'] < df['vwap'])
            else:
                price_trigger = (df['high'] >= df['vwap']) & (df['close'] < df['vwap'])
            candle_ok = df['close'] < df['open']  # candela ribassista
        else:
            if self.entry_mode == 'cross_above':
                price_trigger = (df['close'].shift(1) <= df['vwap'].shift(1)) & (df['close'] > df['vwap'])
            else:
                price_trigger = (df['low'] <= df['vwap']) & (df['close'] > df['vwap'])
            candle_ok = df['close'] > df['open']  # candela rialzista

        volume_ok = (df['volume'] / df['volume_ma']) >= self.volume_ratio_min

        required = ['vwap', 'volume_ma']
        if self.use_trend_filter:
            required = required + ['ema200']
        not_na = df[required].notna().all(axis=1)

        signal = not_na & price_trigger & candle_ok & volume_ok
        if self.use_trend_filter:
            trend_ok = (df['close'] < df['ema200']) if self.direction == 'short' else (df['close'] > df['ema200'])
            signal = signal & trend_ok

        return signal

    def get_entry_levels(self, entry_price: float, swing_level: float) -> tuple:
        """LONG: swing_level = minimo dello swing, SL sotto, TP sopra.
        SHORT: swing_level = massimo dello swing, SL sopra, TP sotto. Stesso risk_reward."""
        if self.direction == 'short':
            stop_loss_price = swing_level * (1 + self.stop_buffer_percent / 100.0)
            risk = stop_loss_price - entry_price
            take_profit_price = entry_price - self.risk_reward * risk
        else:
            stop_loss_price = swing_level * (1 - self.stop_buffer_percent / 100.0)
            risk = entry_price - stop_loss_price
            take_profit_price = entry_price + self.risk_reward * risk
        return stop_loss_price, take_profit_price
