"""
Backtest di una strategia trend-following SEMPLICE: long quando il prezzo di chiusura
giornaliero è sopra la sua media mobile di lungo periodo, fuori (cash) quando è sotto.

Base scientifica: è probabilmente la strategia sistematica più replicata e robusta in
letteratura (Faber 2007 "A Quantitative Approach to Tactical Asset Allocation"; Moskowitz,
Ooi & Pedersen 2012 "Time Series Momentum"). Nessun filtro aggiuntivo, nessun order-flow,
nessuna z-score: un solo parametro (il periodo della media mobile). Poche operazioni
(giorni/settimane di holding), quindi le fee contano poco rispetto ai movimenti catturati -
esattamente l'opposto strutturale delle 6 ipotesi ad alta frequenza già respinte.

Walk-forward: si sceglie il periodo MA migliore SOLO sul 70% iniziale (train), si valida
UNA volta sul 30% finale (test) mai visto.
"""
import numpy as np
import pandas as pd

SYMBOLS = ['BTCEUR', 'ETHEUR', 'BNBEUR', 'SOLEUR', 'ADAEUR', 'AVAXEUR']
FEE_PERCENT = 0.1
SLIPPAGE_PERCENT = 0.05  # per lato, prudente per ordini giornalieri su queste coppie


def load_daily(symbol):
    df = pd.read_csv(f'data/{symbol}_1d.csv', parse_dates=['timestamp'])
    return df.sort_values('timestamp').reset_index(drop=True)


def simulate_trend(df: pd.DataFrame, ma_period: int) -> list:
    """Long quando close > MA, esce quando close < MA. Esecuzione al prossimo open (no lookahead)."""
    df = df.copy()
    df['ma'] = df['close'].rolling(window=ma_period).mean()

    n = len(df)
    closes = df['close'].values
    opens = df['open'].values
    ma = df['ma'].values

    trades = []
    in_position = False
    entry_price = None
    entry_idx = None

    for i in range(1, n):
        if pd.isna(ma[i]) or pd.isna(ma[i - 1]):
            continue

        above = closes[i] > ma[i]
        above_prev = closes[i - 1] > ma[i - 1]

        if not in_position and above and not above_prev and i + 1 < n:
            in_position = True
            entry_idx = i + 1
            entry_price = opens[entry_idx] * (1 + SLIPPAGE_PERCENT / 100.0)
        elif in_position and not above and above_prev and i + 1 < n:
            exit_idx = i + 1
            exit_price = opens[exit_idx] * (1 - SLIPPAGE_PERCENT / 100.0)
            pnl = (exit_price / entry_price - 1) * 100 - 2 * FEE_PERCENT
            trades.append({
                'entry_time': df['timestamp'].iloc[entry_idx], 'exit_time': df['timestamp'].iloc[exit_idx],
                'holding_days': exit_idx - entry_idx, 'pnl_percent': pnl,
            })
            in_position = False

    # Chiudi posizione ancora aperta a fine periodo (mark-to-market) per non ignorare il trade in corso
    if in_position:
        exit_price = closes[-1] * (1 - SLIPPAGE_PERCENT / 100.0)
        pnl = (exit_price / entry_price - 1) * 100 - 2 * FEE_PERCENT
        trades.append({
            'entry_time': df['timestamp'].iloc[entry_idx], 'exit_time': df['timestamp'].iloc[-1],
            'holding_days': (n - 1) - entry_idx, 'pnl_percent': pnl, 'open_at_end': True,
        })

    return trades


def summarize(trades, n_years):
    if not trades:
        return {'n_trades': 0}
    pnl = np.array([t['pnl_percent'] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    holding = np.array([t['holding_days'] for t in trades])
    return {
        'n_trades': len(trades),
        'trades_per_year': len(trades) / n_years if n_years > 0 else 0,
        'win_rate_pct': 100 * len(wins) / len(trades),
        'avg_holding_days': holding.mean(),
        'expectancy_pct_per_trade': pnl.mean(),
        'total_pnl_pct_sum': pnl.sum(),
        'profit_factor': (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf'),
        'max_win': pnl.max(), 'max_loss': pnl.min(),
    }


def split_train_test(df, train_frac=0.7):
    idx = int(len(df) * train_frac)
    return df.iloc[:idx].reset_index(drop=True), df.iloc[idx:].reset_index(drop=True)


if __name__ == '__main__':
    print("=" * 70)
    print("BACKTEST — Trend Following semplice (prezzo vs media mobile)")
    print("=" * 70)

    data = {s: load_daily(s) for s in SYMBOLS}

    # Griglia volutamente piccola: pochi parametri, niente overfitting
    ma_periods = [20, 50, 100, 150, 200]

    print(f"\nSelezione periodo MA (solo su TRAIN, 70% iniziale, {len(ma_periods)} valori testati)...")
    results = []
    for ma_period in ma_periods:
        all_trades = []
        total_years = 0.0
        for symbol, df in data.items():
            train_df, _ = split_train_test(df)
            trades = simulate_trend(train_df, ma_period)
            all_trades.extend(trades)
            total_years += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).days / 365.25
        s = summarize(all_trades, total_years)
        s['ma_period'] = ma_period
        results.append(s)
        if s['n_trades'] > 0:
            print(f"   MA={ma_period:3d}: trades={s['n_trades']:3d} ({s['trades_per_year']:.1f}/anno) "
                  f"win={s['win_rate_pct']:.1f}% exp={s['expectancy_pct_per_trade']:+.2f}% "
                  f"pf={s['profit_factor']:.2f} hold_medio={s['avg_holding_days']:.0f}gg")
        else:
            print(f"   MA={ma_period:3d}: nessun trade")

    valid = [r for r in results if r.get('n_trades', 0) >= 10]
    pool = valid if valid else results
    pool.sort(key=lambda r: r['expectancy_pct_per_trade'], reverse=True)
    best_ma = pool[0]['ma_period']
    print(f"\n✅ Periodo MA selezionato: {best_ma}")

    print("\n" + "=" * 70)
    print(f"VALIDAZIONE OUT-OF-SAMPLE (MA={best_ma}, ultimi 30% mai visti)")
    print("=" * 70)

    train_all, test_all = [], []
    train_years = test_years = 0.0
    per_symbol_test = {}
    for symbol, df in data.items():
        train_df, test_df = split_train_test(df)
        train_trades = simulate_trend(train_df, best_ma)
        test_trades = simulate_trend(test_df, best_ma)
        train_all.extend(train_trades)
        test_all.extend(test_trades)
        train_years += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).days / 365.25
        test_years += (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).days / 365.25
        per_symbol_test[symbol] = summarize(test_trades, (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).days / 365.25)

    print("\n--- TRAIN ---")
    print(summarize(train_all, train_years))
    print("\n--- TEST (OUT-OF-SAMPLE) ---")
    test_summary = summarize(test_all, test_years)
    print(test_summary)

    print("\n--- Per simbolo (TEST) ---")
    for symbol, s in per_symbol_test.items():
        if s.get('n_trades', 0) == 0:
            print(f"   {symbol}: nessun trade")
        else:
            print(f"   {symbol}: trades={s['n_trades']} win={s['win_rate_pct']:.1f}% "
                  f"exp={s['expectancy_pct_per_trade']:+.2f}% pf={s['profit_factor']:.2f}")

    # Confronto con semplice buy&hold sullo stesso periodo di test
    print("\n--- Confronto Buy & Hold (stesso periodo test, media sui 6 simboli) ---")
    bh_returns = []
    for symbol, df in data.items():
        _, test_df = split_train_test(df)
        bh_ret = (test_df['close'].iloc[-1] / test_df['close'].iloc[0] - 1) * 100
        bh_returns.append(bh_ret)
        print(f"   {symbol}: {bh_ret:+.1f}%")
    print(f"   Media Buy&Hold: {np.mean(bh_returns):+.1f}%")
