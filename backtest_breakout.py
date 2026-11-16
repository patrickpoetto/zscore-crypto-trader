"""
Backtest della strategia Donchian(96) + LWTI(25,20) + Volume(30), timeframe 5m.

Dati: Binance 1m resampled a 5m (storico lungo, per un campione statisticamente sensato).
Lo storico 5m nativo di Hyperliquid copre solo ~18 giorni via API pubblica: troppo poco per
un backtest robusto. I prezzi BTC/ETH/BNB/SOL/AVAX seguono comunque Hyperliquid molto da
vicino per arbitraggio, quindi Binance è un proxy ragionevole per la validazione storica;
l'esecuzione reale/paper resta comunque su Hyperliquid.

Nessun lookahead: segnale valutato sulla barra chiusa, esecuzione all'open della barra
successiva. Fee e slippage realistici. SL/TP fissi decisi al momento dell'ingresso.
"""
import numpy as np
import pandas as pd

from strategy_breakout import DonchianLWTIBreakoutStrategy

SYMBOLS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'BNB': 'BNBUSDT', 'SOL': 'SOLUSDT', 'AVAX': 'AVAXUSDT'}
# Fee reale Hyperliquid perpetual, base tier, verificata via API (user_fees -> feeSchedule.cross):
# taker 0.045% per lato. Prima usavo per errore la fee Binance spot (0.1%) - corretto.
FEE_PERCENT = 0.045
SLIPPAGE_PERCENT = 0.03


def load_and_resample_5m(binance_symbol):
    df = pd.read_csv(f'data/{binance_symbol}_1m.csv', parse_dates=['timestamp'])
    df = df.set_index('timestamp')
    agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    df5 = df.resample('5min').agg(agg).dropna().reset_index()
    return df5


def simulate(df: pd.DataFrame, strategy: DonchianLWTIBreakoutStrategy, max_holding_bars=576):
    """max_holding_bars di default = 2 giorni a 5m, come safety-net se non tocca mai SL/TP."""
    n = len(df)
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    donchian_middle = df['donchian_middle'].values
    timestamps = df['timestamp'].values

    signal_mask = strategy.compute_signal_mask(df).values
    candidate_idx = np.where(signal_mask)[0]
    candidate_idx = candidate_idx[candidate_idx < n - 1]

    trades = []
    blocked_until = -1
    for i in candidate_idx:
        if i <= blocked_until:
            continue

        entry_idx = i + 1
        entry_price = opens[entry_idx] * (1 + SLIPPAGE_PERCENT / 100.0)
        stop_loss_price, take_profit_price = strategy.get_entry_levels(entry_price, donchian_middle[i])

        if stop_loss_price >= entry_price:
            continue  # caso degenere: SL sopra l'entry, salta

        last_scan_idx = min(entry_idx + max_holding_bars, n - 1)
        exit_idx, exit_price, exit_reason = last_scan_idx, closes[last_scan_idx], 'TIME_EXIT'
        for j in range(entry_idx, last_scan_idx + 1):
            if lows[j] <= stop_loss_price:
                exit_idx, exit_price, exit_reason = j, stop_loss_price, 'STOP_LOSS'
                break
            if highs[j] >= take_profit_price:
                exit_idx, exit_price, exit_reason = j, take_profit_price, 'TAKE_PROFIT'
                break

        exit_price_slip = exit_price * (1 - SLIPPAGE_PERCENT / 100.0)
        net_pnl_percent = (exit_price_slip / entry_price - 1) * 100 - 2 * FEE_PERCENT

        trades.append({
            'entry_time': timestamps[entry_idx], 'exit_time': timestamps[exit_idx],
            'entry_price': entry_price, 'stop_loss': stop_loss_price, 'take_profit': take_profit_price,
            'exit_price': exit_price_slip, 'exit_reason': exit_reason,
            'holding_bars': exit_idx - entry_idx, 'pnl_percent': net_pnl_percent,
        })
        blocked_until = exit_idx

    return trades


def summarize(trades, n_days):
    if not trades:
        return {'n_trades': 0}
    pnl = np.array([t['pnl_percent'] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    reasons = pd.Series([t['exit_reason'] for t in trades]).value_counts().to_dict()
    return {
        'n_trades': len(trades),
        'trades_per_day': len(trades) / n_days if n_days > 0 else 0,
        'win_rate_pct': 100 * len(wins) / len(trades),
        'avg_win_pct': wins.mean() if len(wins) else 0.0,
        'avg_loss_pct': losses.mean() if len(losses) else 0.0,
        'expectancy_pct_per_trade': pnl.mean(),
        'total_pnl_pct_sum': pnl.sum(),
        'profit_factor': (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf'),
        'exit_reasons': reasons,
    }


if __name__ == '__main__':
    print("=" * 70)
    print("BACKTEST — Donchian(96) + LWTI(25,20) + Volume(30) MA, timeframe 5m")
    print("=" * 70)

    strategy = DonchianLWTIBreakoutStrategy(donchian_length=96, lwti_period=25,
                                             lwti_smoothing=20, volume_ma_length=30, risk_reward=2.0)

    all_trades = []
    total_days = 0.0
    per_symbol = {}

    for label, binance_symbol in SYMBOLS.items():
        df5 = load_and_resample_5m(binance_symbol)
        df_ind = strategy.calculate_indicators(df5)
        trades = simulate(df_ind, strategy)
        for t in trades:
            t['symbol'] = label
        all_trades.extend(trades)
        days = (df5['timestamp'].iloc[-1] - df5['timestamp'].iloc[0]).total_seconds() / 86400
        total_days += days
        s = summarize(trades, days)
        per_symbol[label] = s
        if s['n_trades'] > 0:
            print(f"\n{label}: {s['n_trades']} trade ({s['trades_per_day']:.2f}/g) "
                  f"win={s['win_rate_pct']:.1f}% exp={s['expectancy_pct_per_trade']:+.3f}% "
                  f"pf={s['profit_factor']:.2f}")
            print(f"      uscite: {s['exit_reasons']}")
        else:
            print(f"\n{label}: nessun trade generato")

    print("\n" + "=" * 70)
    print("AGGREGATO (tutti gli asset)")
    print("=" * 70)
    total_summary = summarize(all_trades, total_days / len(SYMBOLS))
    print(total_summary)

    # Salva log dettagliato
    import csv
    import os
    os.makedirs('reports', exist_ok=True)
    with open('reports/backtest_breakout_trades.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['symbol', 'entry_time', 'exit_time', 'entry_price', 'stop_loss',
                          'take_profit', 'exit_price', 'exit_reason', 'holding_bars', 'pnl_percent'])
        for t in sorted(all_trades, key=lambda x: x['entry_time']):
            writer.writerow([t['symbol'], t['entry_time'], t['exit_time'], t['entry_price'],
                              t['stop_loss'], t['take_profit'], t['exit_price'], t['exit_reason'],
                              t['holding_bars'], f"{t['pnl_percent']:.4f}"])
    print(f"\n💾 Log dettagliato salvato in reports/backtest_breakout_trades.csv")
