"""Backtest onesto della strategia Relative Value Divergence (pairs), stessa metodologia
walk-forward (train 70% / test 30% mai visto) e stesse assunzioni di fee/slippage di backtest.py."""
import itertools
import numpy as np
import pandas as pd

from backtest import load_data, split_train_test, summarize, FEE_PERCENT, SLIPPAGE_PERCENT
from strategy_pairs import PairsRelativeValueStrategy

PAIRS = [
    ('ETHUSDT', 'BTCUSDT'),
    ('SOLUSDT', 'ETHUSDT'),
    ('SOLUSDT', 'BTCUSDT'),
    ('BNBUSDT', 'BTCUSDT'),
    ('AVAXUSDT', 'ETHUSDT'),
]


def simulate_pairs(merged: pd.DataFrame, params: dict) -> list:
    strategy = PairsRelativeValueStrategy(**params)
    max_holding_bars = int(round(strategy.max_holding_minutes))
    n = len(merged)
    closes, opens, highs, lows = merged['close'].values, merged['open'].values, merged['high'].values, merged['low'].values
    timestamps = merged['timestamp'].values

    signal_mask = strategy.compute_signal_mask(merged).values
    candidate_idx = np.where(signal_mask)[0]
    candidate_idx = candidate_idx[candidate_idx < n - 1]

    trades = []
    blocked_until = -1
    for i in candidate_idx:
        if i <= blocked_until:
            continue
        entry_idx = i + 1
        entry_price = opens[entry_idx] * (1 + SLIPPAGE_PERCENT / 100.0)
        stop_loss_price, take_profit_price = strategy.get_entry_levels(entry_price)

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
            'exit_reason': exit_reason, 'pnl_percent': net_pnl_percent,
        })
        blocked_until = exit_idx

    return trades


def eval_pair_train(asset_a, asset_b, params):
    df_a, df_b = load_data(asset_a), load_data(asset_b)
    strategy = PairsRelativeValueStrategy(**params)
    merged = strategy.calculate_spread(df_a, df_b)
    train_merged, _ = split_train_test(merged)
    trades = simulate_pairs(train_merged, params)
    days = (train_merged['timestamp'].iloc[-1] - train_merged['timestamp'].iloc[0]).total_seconds() / 86400
    return summarize(trades, days)


if __name__ == '__main__':
    print("=" * 70)
    print("BACKTEST — Relative Value Divergence (pairs, long-only)")
    print("=" * 70)

    grid = {
        'beta_lookback': [360, 720, 1440],
        'zscore_lookback': [60, 120, 240],
        'entry_zscore_threshold': [1.5, 2.0, 2.5],
        'stop_loss_percent': [0.45, 0.6],
        'take_profit_percent': [0.9, 1.2],
        'max_holding_minutes': [60, 120],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    print(f"Combinazioni per pair: {len(combos)}  |  Pair testate: {len(PAIRS)}")

    all_results = []
    for asset_a, asset_b in PAIRS:
        df_a, df_b = load_data(asset_a), load_data(asset_b)
        best_for_pair = []
        for combo in combos:
            params = dict(zip(keys, combo))
            strategy = PairsRelativeValueStrategy(**params)
            merged = strategy.calculate_spread(df_a, df_b)
            train_merged, _ = split_train_test(merged)
            trades = simulate_pairs(train_merged, params)
            days = (train_merged['timestamp'].iloc[-1] - train_merged['timestamp'].iloc[0]).total_seconds() / 86400
            s = summarize(trades, days)
            s['params'] = params
            s['pair'] = f"{asset_a}/{asset_b}"
            best_for_pair.append(s)

        valid = [r for r in best_for_pair if r.get('n_trades', 0) >= 30]
        if not valid:
            valid = best_for_pair
        valid.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)
        all_results.append(valid[0])
        top = valid[0]
        print(f"\n{asset_a}/{asset_b} — miglior config TRAIN (>=30 trade se disponibile):")
        print(f"   {top['params']}")
        if top.get('n_trades', 0) == 0:
            print("   nessun trade")
        else:
            print(f"   trades={top['n_trades']} ({top['trades_per_day']:.2f}/g) win={top['win_rate_pct']:.1f}% "
                  f"exp={top['expectancy_pct_per_trade']:+.4f}% pf={top['profit_factor']:.2f}")

    all_results.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)
    best = all_results[0]
    asset_a, asset_b = best['pair'].split('/')
    best_params = best['params']

    print("\n" + "=" * 70)
    print(f"Pair migliore su TRAIN: {best['pair']} — validazione OUT-OF-SAMPLE")
    print("=" * 70)

    df_a, df_b = load_data(asset_a), load_data(asset_b)
    strategy = PairsRelativeValueStrategy(**best_params)
    merged = strategy.calculate_spread(df_a, df_b)
    train_merged, test_merged = split_train_test(merged)

    train_trades = simulate_pairs(train_merged, best_params)
    test_trades = simulate_pairs(test_merged, best_params)
    train_days = (train_merged['timestamp'].iloc[-1] - train_merged['timestamp'].iloc[0]).total_seconds() / 86400
    test_days = (test_merged['timestamp'].iloc[-1] - test_merged['timestamp'].iloc[0]).total_seconds() / 86400

    from backtest import print_summary
    print_summary(f"TRAIN {best['pair']}", summarize(train_trades, train_days))
    print_summary(f"TEST (OUT-OF-SAMPLE) {best['pair']}", summarize(test_trades, test_days))
    print(f"\nParametri: {best_params}")
