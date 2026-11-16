"""
Rinforzo dell'INGRESSO (non dell'uscita, già esplorata in optimize_breakout_exits.py):
chiusura decisa oltre la banda, LWTI anche sopra soglia, volume realmente anomalo, filtro
di trend più ampio. SL/TP tenuti fissi all'originale (banda centrale, RR 2:1) per isolare
l'effetto dei filtri di ingresso. Selezione SOLO su train (70%), validazione su test (30%).
"""
import itertools
import numpy as np
import pandas as pd

from strategy_breakout import DonchianLWTIBreakoutStrategy
from backtest_breakout import SYMBOLS, load_and_resample_5m, simulate, summarize


def split_train_test(df, train_frac=0.7):
    idx = int(len(df) * train_frac)
    return df.iloc[:idx].reset_index(drop=True), df.iloc[idx:].reset_index(drop=True)


if __name__ == '__main__':
    grid = {
        'require_close_breakout': [False, True],
        'lwti_min_level': [None, 50],
        'volume_ratio_min': [1.0, 1.3, 1.5, 2.0],
        'use_trend_filter': [False, True],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"Combinazioni totali: {len(combos)}")

    # Precalcola indicatori una sola volta per simbolo (uguali per tutte le combo)
    raw_data = {}
    for label, binance_symbol in SYMBOLS.items():
        df5 = load_and_resample_5m(binance_symbol)
        raw_data[label] = df5

    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        strategy = DonchianLWTIBreakoutStrategy(donchian_length=96, lwti_period=25, lwti_smoothing=20,
                                                 volume_ma_length=30, risk_reward=2.0, **params)
        all_trades = []
        total_days = 0.0
        for label, df5 in raw_data.items():
            df_ind = strategy.calculate_indicators(df5)
            train_df, _ = split_train_test(df_ind)
            trades = simulate(train_df, strategy)
            all_trades.extend(trades)
            total_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400
        s = summarize(all_trades, total_days / len(raw_data))
        s['params'] = params
        results.append(s)

    valid = [r for r in results if r.get('n_trades', 0) >= 20]
    print(f"Combinazioni con >= 20 trade su train: {len(valid)}/{len(results)}")
    if not valid:
        print("⚠️  Nessuna combinazione con >= 20 trade su train (campione dati troppo piccolo): "
              "fallback sulle combinazioni con almeno 1 trade, interpretare con cautela.")
        valid = [r for r in results if r.get('n_trades', 0) > 0]
    if not valid:
        print("❌ Nessuna combinazione ha generato trade su train: dataset troppo piccolo, impossibile procedere.")
        raise SystemExit(1)
    valid.sort(key=lambda r: r['expectancy_pct_per_trade'], reverse=True)

    print("\nTop 10 per expectancy (train):")
    for r in valid[:10]:
        p = r['params']
        print(f"   close_breakout={p['require_close_breakout']} lwti_min={p['lwti_min_level']} "
              f"vol_ratio>={p['volume_ratio_min']} trend_filter={p['use_trend_filter']} "
              f"-> trade={r['n_trades']} ({r['trades_per_day']:.2f}/g) win={r['win_rate_pct']:.1f}% "
              f"exp={r['expectancy_pct_per_trade']:+.3f}% pf={r['profit_factor']:.2f}")

    best_params = valid[0]['params']
    print(f"\n✅ Migliore su train: {best_params}")

    print("\n" + "=" * 80)
    print("VALIDAZIONE OUT-OF-SAMPLE (ultimi 30% mai visti)")
    print("=" * 80)

    strategy = DonchianLWTIBreakoutStrategy(donchian_length=96, lwti_period=25, lwti_smoothing=20,
                                             volume_ma_length=30, risk_reward=2.0, **best_params)
    train_trades, test_trades = [], []
    train_days = test_days = 0.0
    per_symbol_test = {}
    for label, df5 in raw_data.items():
        df_ind = strategy.calculate_indicators(df5)
        train_df, test_df = split_train_test(df_ind)
        train_trades.extend(simulate(train_df, strategy))
        t_trades = simulate(test_df, strategy)
        test_trades.extend(t_trades)
        train_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400
        test_days += (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).total_seconds() / 86400
        per_symbol_test[label] = summarize(t_trades, (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).total_seconds() / 86400)

    print("\n--- TRAIN ---")
    print(summarize(train_trades, train_days / len(raw_data)))
    print("\n--- TEST (OUT-OF-SAMPLE) ---")
    print(summarize(test_trades, test_days / len(raw_data)))

    print("\n--- Per simbolo (TEST) ---")
    for label, s in per_symbol_test.items():
        if s.get('n_trades', 0) == 0:
            print(f"   {label}: nessun trade")
        else:
            print(f"   {label}: trades={s['n_trades']} win={s['win_rate_pct']:.1f}% "
                  f"exp={s['expectancy_pct_per_trade']:+.3f}% pf={s['profit_factor']:.2f}")

    # Confronto con l'originale (nessun filtro extra) sullo stesso test set
    print("\n--- Per confronto: ORIGINALE (nessun filtro extra) sullo stesso TEST ---")
    strategy_orig = DonchianLWTIBreakoutStrategy(donchian_length=96, lwti_period=25, lwti_smoothing=20,
                                                  volume_ma_length=30, risk_reward=2.0)
    orig_test_trades = []
    for label, df5 in raw_data.items():
        df_ind = strategy_orig.calculate_indicators(df5)
        _, test_df = split_train_test(df_ind)
        orig_test_trades.extend(simulate(test_df, strategy_orig))
    print(summarize(orig_test_trades, test_days / len(raw_data)))
