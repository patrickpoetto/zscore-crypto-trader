"""
Backtest onesto della strategia Exhaustion Reversal su dati storici reali (Binance mainnet,
klines pubblici 1m). Nessun lookahead: il segnale è calcolato con dati fino alla barra t
(compresa), l'esecuzione avviene all'OPEN della barra t+1. Dentro la posizione, TP/SL sono
valutati su high/low di ogni barra successiva (SL ha precedenza se nella stessa barra
toccherebbe entrambi, ipotesi conservativa). Include fee (round-trip) e uno slippage stimato.

Split walk-forward: primi 70% dei giorni per il grid-search dei parametri, ultimi 30%
(mai visti durante il tuning) per la validazione out-of-sample onesta.
"""
import os
import itertools
import numpy as np
import pandas as pd

from config import Config
from strategy_scalping import ExhaustionReversalStrategy

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'ADAUSDT', 'AVAXUSDT', 'INJUSDT']

FEE_PERCENT = Config.TRADING_FEE_PERCENT  # 0.1% per lato, come Binance spot
SLIPPAGE_PERCENT = 0.02  # stima prudente per lato su pair liquide con size moderata


def load_data(symbol):
    path = os.path.join(DATA_DIR, f"{symbol}_1m.csv")
    df = pd.read_csv(path, parse_dates=['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def simulate(df: pd.DataFrame, params: dict) -> list:
    """Simula la strategia su un intero DataFrame (già con indicatori). Ritorna lista di trade dict.
    Ottimizzato: calcola la maschera segnale in modo vettoriale e scansiona in dettaglio
    (per l'uscita TP/SL/time) solo le barre candidate, non ogni barra della serie."""
    strategy = ExhaustionReversalStrategy(**params)
    max_holding_bars = int(round(strategy.max_holding_minutes))  # barre = minuti (timeframe 1m)

    n = len(df)
    closes = df['close'].values
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    timestamps = df['timestamp'].values
    confidences = df['sell_ratio_window'].values  # usato solo per approx, non critico

    signal_mask = strategy.compute_signal_mask(df).values
    candidate_idx = np.where(signal_mask)[0]
    candidate_idx = candidate_idx[candidate_idx < n - 1]

    trades = []
    blocked_until = -1
    for i in candidate_idx:
        if i <= blocked_until:
            continue  # già in posizione da un trade precedente

        entry_idx = i + 1  # esegue all'open della barra successiva (no lookahead)
        entry_price = opens[entry_idx] * (1 + SLIPPAGE_PERCENT / 100.0)  # slippage sfavorevole in ingresso
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

        exit_price_after_slippage = exit_price * (1 - SLIPPAGE_PERCENT / 100.0)
        gross_pnl_percent = (exit_price_after_slippage / entry_price - 1) * 100
        net_pnl_percent = gross_pnl_percent - (2 * FEE_PERCENT)  # fee round-trip

        trades.append({
            'entry_time': timestamps[entry_idx],
            'exit_time': timestamps[exit_idx],
            'entry_price': entry_price,
            'exit_price': exit_price_after_slippage,
            'exit_reason': exit_reason,
            'holding_bars': exit_idx - entry_idx,
            'pnl_percent': net_pnl_percent,
        })

        blocked_until = exit_idx

    return trades


def summarize(trades: list, n_days: float) -> dict:
    if not trades:
        return {'n_trades': 0}
    pnl = np.array([t['pnl_percent'] for t in trades])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    equity = np.cumsum(pnl)
    running_max = np.maximum.accumulate(equity) if len(equity) else np.array([0])
    drawdown = equity - running_max
    max_drawdown = drawdown.min() if len(drawdown) else 0.0

    reasons = pd.Series([t['exit_reason'] for t in trades]).value_counts().to_dict()

    return {
        'n_trades': len(trades),
        'trades_per_day': len(trades) / n_days if n_days > 0 else 0.0,
        'win_rate_pct': 100 * len(wins) / len(trades),
        'avg_win_pct': wins.mean() if len(wins) else 0.0,
        'avg_loss_pct': losses.mean() if len(losses) else 0.0,
        'expectancy_pct_per_trade': pnl.mean(),
        'total_pnl_pct_sum': pnl.sum(),
        'max_drawdown_pct': max_drawdown,
        'profit_factor': (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf'),
        'exit_reasons': reasons,
    }


def print_summary(label, summary):
    print(f"\n--- {label} ---")
    if summary.get('n_trades', 0) == 0:
        print("   Nessun trade generato.")
        return
    print(f"   Trade totali: {summary['n_trades']}  |  Trade/giorno: {summary['trades_per_day']:.2f}")
    print(f"   Win rate: {summary['win_rate_pct']:.1f}%")
    print(f"   Avg win: {summary['avg_win_pct']:+.3f}%  |  Avg loss: {summary['avg_loss_pct']:+.3f}%")
    print(f"   Expectancy/trade: {summary['expectancy_pct_per_trade']:+.4f}%  |  Somma PnL: {summary['total_pnl_pct_sum']:+.2f}%")
    print(f"   Max drawdown (equity in % cumulata): {summary['max_drawdown_pct']:.2f}%")
    print(f"   Profit factor: {summary['profit_factor']:.2f}")
    print(f"   Uscite per motivo: {summary['exit_reasons']}")


def prepare_all(symbols):
    """Carica e calcola indicatori una sola volta per simbolo (i parametri di soglia sul
    segnale non cambiano le colonne di indicatori tranne lookback; per la grid search sui
    lookback ricalcoliamo, per le sole soglie riusiamo lo stesso df."""
    data = {}
    for symbol in symbols:
        df = load_data(symbol)
        data[symbol] = df
    return data


def split_train_test(df, train_frac=0.7):
    split_idx = int(len(df) * train_frac)
    return df.iloc[:split_idx].reset_index(drop=True), df.iloc[split_idx:].reset_index(drop=True)


def run_grid_search(data, param_grid, base_strategy_kwargs):
    """Grid search sui parametri chiave, valutato sulla parte TRAIN di tutti i simboli aggregata."""
    keys = list(param_grid.keys())
    combos = list(itertools.product(*param_grid.values()))
    results = []

    for combo in combos:
        params = dict(base_strategy_kwargs)
        params.update(dict(zip(keys, combo)))

        strategy_calc = ExhaustionReversalStrategy(**params)
        all_trades = []
        total_train_days = 0.0
        for symbol, df in data.items():
            train_df, _ = split_train_test(df)
            df_ind = strategy_calc.calculate_indicators(train_df)
            if df_ind is None:
                continue
            trades = simulate(df_ind, params)
            all_trades.extend(trades)
            total_train_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400

        summary = summarize(all_trades, total_train_days)
        summary['params'] = params
        results.append(summary)

    # Filtra combinazioni con troppo pochi trade (non statisticamente significative)
    valid = [r for r in results if r.get('n_trades', 0) >= 30]
    if not valid:
        valid = results
    valid.sort(key=lambda r: r.get('expectancy_pct_per_trade', -999), reverse=True)
    return valid


if __name__ == '__main__':
    print("=" * 70)
    print("BACKTEST — Exhaustion Reversal Scalping Strategy")
    print("=" * 70)

    data = prepare_all(SYMBOLS)

    # Grid search modesta sui parametri più sensibili, tuning SOLO su train (70%)
    param_grid = {
        'impulse_z_threshold': [2.0, 2.5, 3.0],
        'sell_imbalance_threshold': [0.55, 0.60, 0.65],
        'stop_loss_percent': [0.35, 0.45, 0.6],
    }
    base_kwargs = {}

    print("\n🔍 Grid search sui parametri (solo su dati TRAIN, 70% iniziale)...")
    results = run_grid_search(data, param_grid, base_kwargs)

    print("\nTop 5 combinazioni (train, ordinate per expectancy/trade):")
    for r in results[:5]:
        p = r['params']
        print(f"   z={p['impulse_z_threshold']} sell_imb={p['sell_imbalance_threshold']} "
              f"SL={p['stop_loss_percent']}% -> trades={r['n_trades']} "
              f"({r['trades_per_day']:.2f}/g) win={r['win_rate_pct']:.1f}% "
              f"exp={r['expectancy_pct_per_trade']:+.4f}%")

    best_params = results[0]['params']
    print(f"\n✅ Parametri selezionati (migliore expectancy su train, con >=30 trade): {best_params}")

    # Validazione OUT-OF-SAMPLE (ultimi 30%, mai usati nel tuning)
    strategy_calc = ExhaustionReversalStrategy(**best_params)
    train_all_trades, test_all_trades = [], []
    train_days_total, test_days_total = 0.0, 0.0
    per_symbol_test = {}

    for symbol, df in data.items():
        train_df, test_df = split_train_test(df)

        train_ind = strategy_calc.calculate_indicators(train_df)
        if train_ind is not None:
            t = simulate(train_ind, best_params)
            train_all_trades.extend(t)
            train_days_total += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400

        test_ind = strategy_calc.calculate_indicators(test_df)
        if test_ind is not None:
            t = simulate(test_ind, best_params)
            test_all_trades.extend(t)
            test_days_total += (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).total_seconds() / 86400
            per_symbol_test[symbol] = summarize(t, (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).total_seconds() / 86400)

    print_summary("TRAIN (in-sample, usato per il tuning)", summarize(train_all_trades, train_days_total))
    print_summary("TEST (OUT-OF-SAMPLE, mai visto nel tuning)", summarize(test_all_trades, test_days_total))

    print("\n--- Dettaglio per simbolo (OUT-OF-SAMPLE) ---")
    for symbol, s in per_symbol_test.items():
        if s.get('n_trades', 0) == 0:
            print(f"   {symbol}: nessun trade")
        else:
            print(f"   {symbol}: {s['n_trades']} trade ({s['trades_per_day']:.2f}/g) "
                  f"win={s['win_rate_pct']:.1f}% exp={s['expectancy_pct_per_trade']:+.4f}%")

    print("\n" + "=" * 70)
    print(f"Parametri finali proposti: {best_params}")
    print("=" * 70)
