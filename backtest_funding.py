"""
Backtest della strategia 'Funding Rate Extreme Reversal': quando il funding rate di un
perpetual è anomalamente negativo (posizionamento short crowded, gli short pagano i long),
la letteratura/pratica crypto documenta una tendenza a mean-reversion/short-squeeze nelle
ore-giorni successivi. Qui si usa SOLO come segnale per entrate LONG spot (bot long-only),
senza tradare i futures stessi.

Nota di onestà statistica: il funding stampa ogni 8h -> ~500 osservazioni su 166 giorni per
simbolo. Campione molto più piccolo dei backtest a 1 minuto: le conclusioni qui sono
necessariamente più tentative (minore potenza statistica).
"""
import numpy as np
import pandas as pd

from backtest import FEE_PERCENT, SLIPPAGE_PERCENT

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'AVAXUSDT', 'INJUSDT']
ZSCORE_LOOKBACK = 90  # numero di stampe di funding precedenti (90 * 8h = 30 giorni) per il regime


def load_funding(symbol):
    df = pd.read_csv(f'data/{symbol}_funding.csv', parse_dates=['fundingTime'])
    df = df.sort_values('fundingTime').reset_index(drop=True)
    roll_mean = df['fundingRate'].rolling(ZSCORE_LOOKBACK).mean()
    roll_std = df['fundingRate'].rolling(ZSCORE_LOOKBACK).std()
    df['funding_zscore'] = (df['fundingRate'] - roll_mean) / roll_std.replace(0, np.nan)
    return df


def load_price(symbol):
    df = pd.read_csv(f'data/{symbol}_1h.csv', parse_dates=['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def simulate_funding(funding_df, price_df, entry_zscore_threshold, holding_hours, stop_loss_percent, take_profit_percent):
    price_df = price_df.set_index('timestamp')
    trades = []
    blocked_until = None

    for _, row in funding_df.iterrows():
        if pd.isna(row['funding_zscore']):
            continue
        if row['funding_zscore'] > -entry_zscore_threshold:
            continue
        funding_time = row['fundingTime']
        if blocked_until is not None and funding_time <= blocked_until:
            continue

        # Entra al primo prezzo disponibile dopo il funding print
        future_prices = price_df.loc[price_df.index >= funding_time]
        if len(future_prices) < 2:
            continue
        entry_time = future_prices.index[0]
        entry_price = future_prices.iloc[0]['open'] * (1 + SLIPPAGE_PERCENT / 100.0)
        stop_loss_price = entry_price * (1 - stop_loss_percent / 100.0)
        take_profit_price = entry_price * (1 + take_profit_percent / 100.0)

        window = future_prices.iloc[1:holding_hours + 1]
        if len(window) == 0:
            continue

        exit_time, exit_price, exit_reason = window.index[-1], window.iloc[-1]['close'], 'TIME_EXIT'
        for t, r in window.iterrows():
            if r['low'] <= stop_loss_price:
                exit_time, exit_price, exit_reason = t, stop_loss_price, 'STOP_LOSS'
                break
            if r['high'] >= take_profit_price:
                exit_time, exit_price, exit_reason = t, take_profit_price, 'TAKE_PROFIT'
                break

        exit_price_slip = exit_price * (1 - SLIPPAGE_PERCENT / 100.0)
        net_pnl_percent = (exit_price_slip / entry_price - 1) * 100 - 2 * FEE_PERCENT

        trades.append({
            'symbol': row.get('symbol', ''),
            'funding_time': funding_time, 'entry_time': entry_time, 'exit_time': exit_time,
            'funding_rate': row['fundingRate'], 'funding_zscore': row['funding_zscore'],
            'exit_reason': exit_reason, 'pnl_percent': net_pnl_percent,
        })
        blocked_until = exit_time

    return trades


def summarize(trades, n_days):
    if not trades:
        return {'n_trades': 0}
    pnl = np.array([t['pnl_percent'] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    reasons = pd.Series([t['exit_reason'] for t in trades]).value_counts().to_dict()
    return {
        'n_trades': len(trades),
        'trades_per_week': 7 * len(trades) / n_days if n_days > 0 else 0.0,
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
    print("BACKTEST — Funding Rate Extreme Reversal (entry spot long-only)")
    print("=" * 70)

    all_data = {}
    for symbol in SYMBOLS:
        funding = load_funding(symbol)
        price = load_price(symbol)
        split_idx = int(len(funding) * 0.7)
        all_data[symbol] = {
            'funding_train': funding.iloc[:split_idx].reset_index(drop=True),
            'funding_test': funding.iloc[split_idx:].reset_index(drop=True),
            'price': price,
        }

    configs = []
    for z in [1.5, 2.0, 2.5]:
        for hold in [24, 48, 72]:
            for sl in [1.5, 2.0]:
                for tp in [2.0, 3.0, 4.0]:
                    configs.append({'entry_zscore_threshold': z, 'holding_hours': hold,
                                     'stop_loss_percent': sl, 'take_profit_percent': tp})

    print(f"\nConfigurazioni testate: {len(configs)} (solo su TRAIN, 70% iniziale del funding)")
    results = []
    for cfg in configs:
        all_trades = []
        for symbol, d in all_data.items():
            trades = simulate_funding(d['funding_train'], d['price'], **cfg)
            for t in trades:
                t['symbol'] = symbol
            all_trades.extend(trades)
        train_days = (all_data[SYMBOLS[0]]['funding_train']['fundingTime'].iloc[-1] -
                      all_data[SYMBOLS[0]]['funding_train']['fundingTime'].iloc[0]).days
        s = summarize(all_trades, train_days)
        s['params'] = cfg
        results.append(s)

    valid = [r for r in results if r.get('n_trades', 0) >= 15]
    print(f"Config con >= 15 trade su train: {len(valid)}/{len(results)}")
    pool = valid if valid else results
    pool.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)

    print("\nTop 5 su TRAIN:")
    for r in pool[:5]:
        p = r['params']
        print(f"   {p} -> trades={r['n_trades']} win={r['win_rate_pct']:.1f}% "
              f"exp={r['expectancy_pct_per_trade']:+.3f}% pf={r['profit_factor']:.2f}")

    best_params = pool[0]['params']
    print(f"\n✅ Config selezionata: {best_params}")

    all_train_trades, all_test_trades = [], []
    for symbol, d in all_data.items():
        all_train_trades.extend(simulate_funding(d['funding_train'], d['price'], **best_params))
        test_trades = simulate_funding(d['funding_test'], d['price'], **best_params)
        for t in test_trades:
            t['symbol'] = symbol
        all_test_trades.extend(test_trades)

    train_days = (all_data[SYMBOLS[0]]['funding_train']['fundingTime'].iloc[-1] -
                  all_data[SYMBOLS[0]]['funding_train']['fundingTime'].iloc[0]).days
    test_days = (all_data[SYMBOLS[0]]['funding_test']['fundingTime'].iloc[-1] -
                 all_data[SYMBOLS[0]]['funding_test']['fundingTime'].iloc[0]).days

    print("\n--- TRAIN ---")
    print(summarize(all_train_trades, train_days))
    print("\n--- TEST (OUT-OF-SAMPLE) ---")
    test_summary = summarize(all_test_trades, test_days)
    print(test_summary)

    print("\n--- Dettaglio trade OUT-OF-SAMPLE ---")
    for t in all_test_trades:
        print(f"   {t['symbol']:10} {str(t['funding_time'])[:16]} z={t['funding_zscore']:+.2f} "
              f"-> {t['exit_reason']:12} pnl={t['pnl_percent']:+.3f}%")
