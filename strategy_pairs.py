"""
Strategia 'Relative Value Divergence' (pairs trading long-only) tra due asset correlati.

Base scientifica: statistical arbitrage / pairs trading (Gatev, Goetzmann & Rouwenhorst 2006;
Vidyamurthy 2004; Avellaneda & Lee 2010) — quando lo spread tra due asset storicamente
co-integrati/correlati devia in modo anomalo, tende a rivertire più velocemente e più
affidabilmente del prezzo assoluto di un singolo asset, perché la deviazione "isola" il
movimento idiosincratico da quello di mercato/settore comune ai due asset.

Limite onesto: il bot è spot LONG-only (nessuno short). Una vera pairs trade sarebbe market-
neutral (long A + short B). Qui, quando lo spread indica "A economico rispetto a B", si va
long SOLO su A: è una scommessa direzionale informata dal valore relativo, non un vero arb
market-neutral. Va validata sulla performance assoluta di A, non sullo spread in sé.
"""
import numpy as np
import pandas as pd
from config import Config


class PairsRelativeValueStrategy:
    """Segnale long-only basato sulla divergenza dello spread (hedge ratio rolling) tra A e B."""

    def __init__(self, **overrides):
        self.beta_lookback = overrides.get('beta_lookback', 720)     # barre (minuti) per l'hedge ratio rolling
        self.zscore_lookback = overrides.get('zscore_lookback', 120)  # barre per lo z-score dello spread
        self.entry_zscore_threshold = overrides.get('entry_zscore_threshold', 2.0)
        self.exit_zscore_threshold = overrides.get('exit_zscore_threshold', 0.0)  # per uscita "a convergenza"
        self.stop_loss_percent = overrides.get('stop_loss_percent', 0.6)
        self.take_profit_percent = overrides.get('take_profit_percent', 1.0)
        self.max_holding_minutes = overrides.get('max_holding_minutes', 120)

    def calculate_spread(self, df_a: pd.DataFrame, df_b: pd.DataFrame) -> pd.DataFrame:
        """Allinea le due serie sui timestamp comuni e calcola spread/hedge ratio/z-score."""
        merged = pd.merge(
            df_a[['timestamp', 'open', 'high', 'low', 'close']],
            df_b[['timestamp', 'close']].rename(columns={'close': 'close_b'}),
            on='timestamp', how='inner'
        ).reset_index(drop=True)

        log_a = np.log(merged['close'])
        log_b = np.log(merged['close_b'])

        cov = log_a.rolling(self.beta_lookback).cov(log_b)
        var_b = log_b.rolling(self.beta_lookback).var()
        beta = cov / var_b.replace(0, np.nan)

        spread = log_a - beta * log_b
        spread_mean = spread.rolling(self.zscore_lookback).mean()
        spread_std = spread.rolling(self.zscore_lookback).std()

        merged['beta'] = beta
        merged['spread'] = spread
        merged['spread_zscore'] = (spread - spread_mean) / spread_std.replace(0, np.nan)
        return merged

    def compute_signal_mask(self, merged: pd.DataFrame) -> pd.Series:
        """BUY su A quando lo spread è anomalmente negativo (A a sconto rispetto a B)."""
        not_na = merged['spread_zscore'].notna()
        return not_na & (merged['spread_zscore'] <= -self.entry_zscore_threshold)

    def get_entry_levels(self, entry_price: float) -> tuple:
        stop_loss_price = entry_price * (1 - self.stop_loss_percent / 100.0)
        take_profit_price = entry_price * (1 + self.take_profit_percent / 100.0)
        return stop_loss_price, take_profit_price
