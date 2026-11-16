"""
Studio di ablazione + grid search estesa per la strategia Exhaustion Reversal.
Tutto valutato SOLO su dati TRAIN (70% iniziale) per non contaminare il test out-of-sample
usato poi per la validazione finale in backtest.py.
"""
import itertools
import numpy as np
import pandas as pd

from backtest import SYMBOLS, load_data, split_train_test, simulate, summarize
from strategy_scalping import ExhaustionReversalStrategy


def eval_params_on_train(data, params):
    strategy = ExhaustionReversalStrategy(**params)
    all_trades = []
    total_days = 0.0
    for symbol, df in data.items():
        train_df, _ = split_train_test(df)
        df_ind = strategy.calculate_indicators(train_df)
        if df_ind is None:
            continue
        trades = simulate(df_ind, params)
        all_trades.extend(trades)
        total_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400
    return summarize(all_trades, total_days)


def load_all(symbols):
    return {s: load_data(s) for s in symbols}


if __name__ == '__main__':
    data = load_all(SYMBOLS)

    baseline_params = {
        'impulse_z_threshold': 2.5,
        'sell_imbalance_threshold': 0.60,
        'stop_loss_percent': 0.45,
        'take_profit_percent': 0.9,
        'max_holding_minutes': 20,
    }

    print("=" * 70)
    print("STUDIO DI ABLAZIONE (solo su TRAIN, baseline params)")
    print("=" * 70)
    variants = {
        'baseline (tutti i filtri attivi)': {},
        'senza filtro volume spike': {'use_volume_filter': False},
        'senza conferma esaurimento (buy_ratio_recent)': {'use_exhaustion_confirm': False},
        'senza filtro di trend': {'use_trend_filter': False},
        'senza volume + senza trend (solo impulso+flow)': {'use_volume_filter': False, 'use_trend_filter': False},
    }
    for label, extra in variants.items():
        params = dict(baseline_params)
        params.update(extra)
        s = eval_params_on_train(data, params)
        if s.get('n_trades', 0) == 0:
            print(f"\n{label}: nessun trade")
        else:
            print(f"\n{label}:")
            print(f"   trades={s['n_trades']} ({s['trades_per_day']:.2f}/g) win={s['win_rate_pct']:.1f}% "
                  f"exp={s['expectancy_pct_per_trade']:+.4f}% pf={s['profit_factor']:.2f}")

    print("\n" + "=" * 70)
    print("GRID SEARCH ESTESA (solo su TRAIN)")
    print("=" * 70)

    grid = {
        'impulse_lookback': [1, 2, 3, 5],
        'impulse_z_threshold': [1.5, 2.0, 2.5, 3.0],
        'sell_imbalance_threshold': [0.55, 0.60, 0.65, 0.70],
        'exhaustion_confirm_bars': [1, 2, 3],
        'stop_loss_percent': [0.3, 0.45, 0.6],
        'take_profit_percent': [0.8, 1.0],
        'max_holding_minutes': [10, 20, 30],
    }

    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"Combinazioni totali da valutare: {len(combos)}")

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        s = eval_params_on_train(data, params)
        s['params'] = params
        results.append(s)

    valid = [r for r in results if r.get('n_trades', 0) >= 50]  # soglia minima per significatività
    print(f"Combinazioni con >= 50 trade su train: {len(valid)}/{len(results)}")

    valid.sort(key=lambda r: r['expectancy_pct_per_trade'], reverse=True)
    print("\nTop 10 per expectancy/trade (con >= 50 trade):")
    for r in valid[:10]:
        p = r['params']
        print(f"   {p} -> trades={r['n_trades']} ({r['trades_per_day']:.2f}/g) "
              f"win={r['win_rate_pct']:.1f}% exp={r['expectancy_pct_per_trade']:+.4f}% pf={r['profit_factor']:.2f}")

    # Ordina anche per frequenza tra quelli a expectancy non troppo negativa, utile per capire
    # il vero trade-off frequenza/qualità richiesto dall'utente (12-15/giorno)
    by_freq = sorted(results, key=lambda r: r.get('trades_per_day', 0), reverse=True)
    print("\nTop 10 per frequenza (trades/giorno), qualunque expectancy:")
    for r in by_freq[:10]:
        if r.get('n_trades', 0) == 0:
            continue
        p = r['params']
        print(f"   {p} -> trades={r['n_trades']} ({r['trades_per_day']:.2f}/g) "
              f"win={r['win_rate_pct']:.1f}% exp={r['expectancy_pct_per_trade']:+.4f}% pf={r['profit_factor']:.2f}")
