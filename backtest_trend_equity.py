"""
Confronto equity-curve: trend-following (MA) vs buy&hold, sull'intero periodo a disposizione,
per capire il vero valore della strategia (protezione del capitale nei crolli), non solo
l'expectancy per singolo trade che può fuorviare quando train/test cadono in regimi diversi.

Usa MA=200, la scelta standard in letteratura (Faber 2007), non ottimizzata sui nostri dati,
per evitare l'overfitting di regime visto nello split 70/30.
"""
import numpy as np
import pandas as pd

SYMBOLS = ['BTCEUR', 'ETHEUR', 'BNBEUR', 'SOLEUR', 'ADAEUR', 'AVAXEUR']
FEE_PERCENT = 0.1
SLIPPAGE_PERCENT = 0.05
MA_PERIOD = 200


def load_daily(symbol):
    df = pd.read_csv(f'data/{symbol}_1d.csv', parse_dates=['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def equity_curve_trend(df, ma_period):
    """Ritorna la serie di equity (partendo da 1.0) per la strategia trend-following."""
    df = df.copy()
    df['ma'] = df['close'].rolling(window=ma_period).mean()
    df['in_position'] = (df['close'] > df['ma']).shift(1).fillna(False)  # decide con dati di ieri, agisce oggi

    equity = [1.0]
    position_open = False
    for i in range(1, len(df)):
        daily_ret = df['close'].iloc[i] / df['close'].iloc[i - 1] - 1
        want_position = df['in_position'].iloc[i]

        cost = 0.0
        if want_position and not position_open:
            cost = (FEE_PERCENT + SLIPPAGE_PERCENT) / 100.0
            position_open = True
        elif not want_position and position_open:
            cost = (FEE_PERCENT + SLIPPAGE_PERCENT) / 100.0
            position_open = False

        step_ret = (daily_ret if position_open or want_position else 0.0) - cost
        equity.append(equity[-1] * (1 + step_ret))

    return pd.Series(equity, index=df['timestamp'])


def equity_curve_bh(df):
    rets = df['close'].pct_change().fillna(0)
    return (1 + rets).cumprod()


def max_drawdown(equity):
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    return dd.min() * 100


if __name__ == '__main__':
    print("=" * 70)
    print(f"TREND-FOLLOWING (MA={MA_PERIOD}, standard letteratura) vs BUY & HOLD")
    print("Intero periodo disponibile, equity curve giornaliera")
    print("=" * 70)

    trend_final, bh_final = [], []
    trend_dd, bh_dd = [], []

    for symbol in SYMBOLS:
        df = load_daily(symbol)
        period_days = (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).days
        eq_trend = equity_curve_trend(df, MA_PERIOD)
        eq_bh = equity_curve_bh(df)

        t_final = (eq_trend.iloc[-1] - 1) * 100
        b_final = (eq_bh.iloc[-1] - 1) * 100
        t_dd = max_drawdown(eq_trend)
        b_dd = max_drawdown(eq_bh)

        trend_final.append(t_final)
        bh_final.append(b_final)
        trend_dd.append(t_dd)
        bh_dd.append(b_dd)

        print(f"\n{symbol}: ({len(df)} candele, {period_days / 365.25:.1f} anni, "
              f"{df['timestamp'].iloc[0].date()} -> {df['timestamp'].iloc[-1].date()})")
        print(f"   Trend-following: {t_final:+8.1f}%   Max Drawdown: {t_dd:6.1f}%")
        print(f"   Buy & Hold:      {b_final:+8.1f}%   Max Drawdown: {b_dd:6.1f}%")

    print("\n" + "=" * 70)
    print(f"MEDIE SUI {len(SYMBOLS)} SIMBOLI")
    print("=" * 70)
    print(f"Trend-following: rendimento medio {np.mean(trend_final):+.1f}%  |  drawdown medio {np.mean(trend_dd):.1f}%")
    print(f"Buy & Hold:      rendimento medio {np.mean(bh_final):+.1f}%  |  drawdown medio {np.mean(bh_dd):.1f}%")
