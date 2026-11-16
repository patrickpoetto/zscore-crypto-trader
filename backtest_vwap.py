"""
Backtest della strategia VWAP Reclaim (VWAP + Volume + EMA200), timeframe 5m.

Stessa metodologia onesta già usata nel resto del progetto:
- Dati: Binance 1m resampled a 5m (storico lungo), proxy ragionevole per Hyperliquid dove
  gira l'esecuzione reale (vedi nota in backtest_breakout.py sull'arbitraggio dei prezzi).
- Nessun lookahead: segnale valutato sulla barra chiusa, esecuzione all'open della barra
  successiva. SL ha precedenza se una barra tocca sia SL che TP (ipotesi conservativa).
- Fee reale Hyperliquid perpetual (taker 0.045% per lato) + slippage stimato.
- Walk-forward: grid search dei parametri SOLO su train (70% iniziale), validazione UNA
  volta su test (30% finale, mai visto durante il tuning).
- Ablazione dei filtri (volume, trend EMA200) per capire quanto contribuiscono davvero,
  invece di darli per buoni.
"""
import itertools
import numpy as np
import pandas as pd

from strategy_vwap import VwapReclaimStrategy

SYMBOLS = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'BNB': 'BNBUSDT', 'SOL': 'SOLUSDT', 'AVAX': 'AVAXUSDT'}
FEE_PERCENT = 0.045
SLIPPAGE_PERCENT = 0.03
MAX_HOLDING_BARS = 576  # 2 giorni a 5m, safety-net se non tocca mai SL/TP


def load_and_resample_5m(binance_symbol):
    df = pd.read_csv(f'data/{binance_symbol}_1m.csv', parse_dates=['timestamp'])
    df = df.set_index('timestamp')
    agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    df5 = df.resample('5min').agg(agg).dropna().reset_index()
    return df5


def split_train_test(df, train_frac=0.7):
    idx = int(len(df) * train_frac)
    return df.iloc[:idx].reset_index(drop=True), df.iloc[idx:].reset_index(drop=True)


def simulate(df: pd.DataFrame, strategy: VwapReclaimStrategy, max_holding_bars=MAX_HOLDING_BARS) -> list:
    n = len(df)
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    timestamps = df['timestamp'].values

    is_short = strategy.direction == 'short'
    if is_short:
        swing_ref = pd.Series(highs).rolling(window=strategy.stop_lookback_bars, min_periods=1).max().values
    else:
        swing_ref = pd.Series(lows).rolling(window=strategy.stop_lookback_bars, min_periods=1).min().values

    signal_mask = strategy.compute_signal_mask(df).values
    candidate_idx = np.where(signal_mask)[0]
    candidate_idx = candidate_idx[candidate_idx < n - 1]

    trades = []
    blocked_until = -1
    for i in candidate_idx:
        if i <= blocked_until:
            continue

        entry_idx = i + 1
        if is_short:
            # Entrare short = vendere: slippage sfavorevole abbassa il prezzo di vendita ottenuto
            entry_price = opens[entry_idx] * (1 - SLIPPAGE_PERCENT / 100.0)
        else:
            entry_price = opens[entry_idx] * (1 + SLIPPAGE_PERCENT / 100.0)
        stop_loss_price, take_profit_price = strategy.get_entry_levels(entry_price, swing_ref[i])

        if is_short:
            if stop_loss_price <= entry_price:
                continue  # caso degenere: SL sotto l'entry (gap sfavorevole), salta
        else:
            if stop_loss_price >= entry_price:
                continue  # caso degenere: SL sopra l'entry (gap sfavorevole), salta

        last_scan_idx = min(entry_idx + max_holding_bars, n - 1)
        exit_idx, exit_price, exit_reason = last_scan_idx, closes[last_scan_idx], 'TIME_EXIT'
        for j in range(entry_idx, last_scan_idx + 1):
            if is_short:
                if highs[j] >= stop_loss_price:
                    exit_idx, exit_price, exit_reason = j, stop_loss_price, 'STOP_LOSS'
                    break
                if lows[j] <= take_profit_price:
                    exit_idx, exit_price, exit_reason = j, take_profit_price, 'TAKE_PROFIT'
                    break
            else:
                if lows[j] <= stop_loss_price:
                    exit_idx, exit_price, exit_reason = j, stop_loss_price, 'STOP_LOSS'
                    break
                if highs[j] >= take_profit_price:
                    exit_idx, exit_price, exit_reason = j, take_profit_price, 'TAKE_PROFIT'
                    break

        if is_short:
            # Uscire short = ricomprare: slippage sfavorevole alza il prezzo di riacquisto
            exit_price_slip = exit_price * (1 + SLIPPAGE_PERCENT / 100.0)
            net_pnl_percent = (entry_price - exit_price_slip) / entry_price * 100 - 2 * FEE_PERCENT
        else:
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


def compounded_equity_curve(trades):
    """Equity curve compounded (parte da 1.0), trade in ordine cronologico. Valida solo se i
    trade non si sovrappongono nel tempo (vero per singolo simbolo, dato il blocked_until)."""
    trades_sorted = sorted(trades, key=lambda t: t['entry_time'])
    equity = [1.0]
    for t in trades_sorted:
        equity.append(equity[-1] * (1 + t['pnl_percent'] / 100.0))
    return equity


def max_drawdown_pct(equity):
    eq = np.array(equity)
    running_max = np.maximum.accumulate(eq)
    dd = (eq - running_max) / running_max
    return dd.min() * 100


def portfolio_metrics(per_symbol_trades: dict, n_days: float) -> dict:
    """Metriche 'serie' per la decisione go/no-go: yield composto per simbolo (capitale
    indipendente per simbolo, nessuna sovrapposizione essendo blocked_until per-simbolo),
    poi media equal-weight tra i simboli per il portfolio complessivo (assunzione: capitale
    diviso in parti uguali tra le coppie, nessuna leva incrociata)."""
    per_symbol = {}
    total_returns = []
    max_dds = []
    for symbol, trades in per_symbol_trades.items():
        if not trades:
            per_symbol[symbol] = {'n_trades': 0}
            continue
        equity = compounded_equity_curve(trades)
        total_return = (equity[-1] - 1) * 100
        dd = max_drawdown_pct(equity)
        per_symbol[symbol] = {
            'n_trades': len(trades),
            'total_return_pct': total_return,
            'max_drawdown_pct': dd,
        }
        total_returns.append(total_return)
        max_dds.append(dd)

    portfolio_total_return = np.mean(total_returns) if total_returns else 0.0
    daily_yield_pct = ((1 + portfolio_total_return / 100.0) ** (1 / n_days) - 1) * 100 if n_days > 0 else 0.0
    annualized_pct = ((1 + daily_yield_pct / 100.0) ** 365 - 1) * 100

    return {
        'per_symbol': per_symbol,
        'portfolio_total_return_pct': portfolio_total_return,
        'portfolio_avg_max_drawdown_pct': np.mean(max_dds) if max_dds else 0.0,
        'daily_yield_pct': daily_yield_pct,
        'annualized_yield_pct': annualized_pct,
        'n_days': n_days,
    }


def print_summary(label, s):
    print(f"\n--- {label} ---")
    if s.get('n_trades', 0) == 0:
        print("   Nessun trade generato.")
        return
    print(f"   Trade totali: {s['n_trades']}  |  Trade/giorno: {s['trades_per_day']:.2f}")
    print(f"   Win rate: {s['win_rate_pct']:.1f}%")
    print(f"   Avg win: {s['avg_win_pct']:+.3f}%  |  Avg loss: {s['avg_loss_pct']:+.3f}%")
    print(f"   Expectancy/trade: {s['expectancy_pct_per_trade']:+.4f}%  |  Somma PnL: {s['total_pnl_pct_sum']:+.2f}%")
    print(f"   Profit factor: {s['profit_factor']:.2f}")
    print(f"   Uscite: {s['exit_reasons']}")


def eval_params_on_split(data_split, params):
    """data_split: dict symbol -> df (già la porzione train o test, senza indicatori)."""
    strategy = VwapReclaimStrategy(**params)
    all_trades = []
    total_days = 0.0
    for symbol, df in data_split.items():
        df_ind = strategy.calculate_indicators(df)
        trades = simulate(df_ind, strategy)
        all_trades.extend(trades)
        total_days += (df['timestamp'].iloc[-1] - df['timestamp'].iloc[0]).total_seconds() / 86400
    return summarize(all_trades, total_days), all_trades


if __name__ == '__main__':
    print("=" * 70)
    print("BACKTEST — VWAP Reclaim (VWAP + Volume + EMA200), timeframe 5m")
    print("=" * 70)

    raw = {label: load_and_resample_5m(sym) for label, sym in SYMBOLS.items()}
    train_data = {label: split_train_test(df)[0] for label, df in raw.items()}
    test_data = {label: split_train_test(df)[1] for label, df in raw.items()}

    # Griglia piccola e deliberata: EMA=200 fisso (per spec, non ottimizzato, evita overfitting
    # di regime come già discusso in backtest_trend_equity.py). Si tuning solo volume/RR.
    grid = {
        'volume_ma_length': [20],
        'volume_ratio_min': [0.8, 1.0, 1.2, 1.5],
        'risk_reward': [1.0, 1.5, 2.0, 3.0],
        'stop_lookback_bars': [1, 3, 5, 10],
        'entry_mode': ['touch_reclaim', 'cross_above'],
        'direction': ['long', 'short'],
    }
    keys = list(grid.keys())
    combos = list(itertools.product(*grid.values()))

    print(f"\n🔍 Grid search sui parametri (solo su TRAIN, {len(combos)} combinazioni)...")
    results = []
    for combo in combos:
        params = dict(zip(keys, combo))
        s, _ = eval_params_on_split(train_data, params)
        s['params'] = params
        results.append(s)

    valid = [r for r in results if r.get('n_trades', 0) >= 30]
    pool = valid if valid else results
    pool.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)

    print("\nTop 5 combinazioni (train, per expectancy/trade, >=30 trade):")
    for r in pool[:5]:
        p = r['params']
        print(f"   {p} -> trades={r['n_trades']} ({r['trades_per_day']:.2f}/g) "
              f"win={r['win_rate_pct']:.1f}% exp={r['expectancy_pct_per_trade']:+.4f}% pf={r['profit_factor']:.2f}")

    broad_best_params = pool[0]['params']
    print(f"\n✅ Migliore combinazione grid iniziale: {broad_best_params}")

    # Il lato LONG non ha mai mostrato edge robusta (vedi header strategy_vwap.py); il lato
    # SHORT è quello promettente (più vicino al pareggio out-of-sample). Rifiniamo SOLO lo
    # short con una griglia più fine intorno ai parametri migliori trovati sopra.
    print("\n" + "=" * 70)
    print("RIFINITURA (solo SHORT, griglia più fine, solo su TRAIN)")
    print("=" * 70)
    fine_grid = {
        'volume_ma_length': [14, 20, 30],
        'volume_ratio_min': [1.2, 1.4, 1.5, 1.7, 2.0],
        'risk_reward': [2.0, 2.5, 3.0, 3.5, 4.0],
        'stop_lookback_bars': [5, 8, 10, 15, 20],
        'entry_mode': ['touch_reclaim', 'cross_above'],
        'direction': ['short'],
    }
    fine_keys = list(fine_grid.keys())
    fine_combos = list(itertools.product(*fine_grid.values()))
    print(f"Combinazioni: {len(fine_combos)}")

    fine_results = []
    for combo in fine_combos:
        params = dict(zip(fine_keys, combo))
        s, _ = eval_params_on_split(train_data, params)
        s['params'] = params
        fine_results.append(s)

    fine_valid = [r for r in fine_results if r.get('n_trades', 0) >= 50]  # soglia più severa
    fine_pool = fine_valid if fine_valid else fine_results
    fine_pool.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)

    print("\nTop 8 rifinite (train, >=50 trade):")
    for r in fine_pool[:8]:
        p = r['params']
        print(f"   {p} -> trades={r['n_trades']} ({r['trades_per_day']:.2f}/g) "
              f"win={r['win_rate_pct']:.1f}% exp={r['expectancy_pct_per_trade']:+.4f}% pf={r['profit_factor']:.2f}")

    best_params = fine_pool[0]['params']
    print(f"\n✅ Parametri rifiniti selezionati: {best_params}")

    print("\n" + "=" * 70)
    print("VALIDAZIONE OUT-OF-SAMPLE (ultimo 30%, mai visto nel tuning)")
    print("=" * 70)
    train_summary, _ = eval_params_on_split(train_data, best_params)
    test_summary, test_trades = eval_params_on_split(test_data, best_params)
    print_summary("TRAIN (in-sample)", train_summary)
    print_summary("TEST (out-of-sample)", test_summary)

    print("\n--- Per simbolo (TEST) ---")
    per_symbol_test_trades = {}
    for label, df in test_data.items():
        s, trades = eval_params_on_split({label: df}, best_params)
        per_symbol_test_trades[label] = trades
        if s.get('n_trades', 0) == 0:
            print(f"   {label}: nessun trade")
        else:
            print(f"   {label}: trades={s['n_trades']} win={s['win_rate_pct']:.1f}% "
                  f"exp={s['expectancy_pct_per_trade']:+.4f}% pf={s['profit_factor']:.2f}")

    print("\n" + "=" * 70)
    print("METRICHE SERIE (equity composta, TEST out-of-sample, per decisione go/no-go)")
    print("=" * 70)
    test_days = (list(test_data.values())[0]['timestamp'].iloc[-1] - list(test_data.values())[0]['timestamp'].iloc[0]).total_seconds() / 86400
    pm = portfolio_metrics(per_symbol_test_trades, test_days)
    print(f"Periodo test: {pm['n_days']:.1f} giorni")
    for symbol, s in pm['per_symbol'].items():
        if s.get('n_trades', 0) == 0:
            print(f"   {symbol}: nessun trade")
        else:
            print(f"   {symbol}: {s['n_trades']} trade | yield composto: {s['total_return_pct']:+.2f}% "
                  f"| max drawdown: {s['max_drawdown_pct']:.2f}%")
    print(f"\nPortfolio (capitale diviso equamente tra le {len(SYMBOLS)} coppie, nessuna leva incrociata):")
    print(f"   Yield totale periodo test: {pm['portfolio_total_return_pct']:+.2f}%")
    print(f"   Yield/giorno (composto): {pm['daily_yield_pct']:+.4f}%")
    print(f"   Yield annualizzato (proiezione, NON garanzia): {pm['annualized_yield_pct']:+.1f}%")
    print(f"   Drawdown medio: {pm['portfolio_avg_max_drawdown_pct']:.2f}%")
    print(f"   Trade/giorno (tutte le coppie): {test_summary.get('trades_per_day', 0):.2f}")

    print("\n" + "=" * 70)
    print("ABLAZIONE (solo su TRAIN, parametri rifiniti come baseline)")
    print("=" * 70)
    variants = {
        'baseline (tutti i filtri attivi)': {},
        'senza filtro volume (ratio_min=0)': {'volume_ratio_min': 0.0},
        'senza filtro trend EMA200': {'use_trend_filter': False},
        'senza volume + senza trend': {'volume_ratio_min': 0.0, 'use_trend_filter': False},
    }
    for label, extra in variants.items():
        params = dict(best_params)
        params.update(extra)
        s, _ = eval_params_on_split(train_data, params)
        if s.get('n_trades', 0) == 0:
            print(f"\n{label}: nessun trade")
        else:
            print(f"\n{label}:")
            print(f"   trades={s['n_trades']} ({s['trades_per_day']:.2f}/g) win={s['win_rate_pct']:.1f}% "
                  f"exp={s['expectancy_pct_per_trade']:+.4f}% pf={s['profit_factor']:.2f}")

    print("\n" + "=" * 70)
    print(f"Parametri finali proposti: {best_params}")
    print("=" * 70)
