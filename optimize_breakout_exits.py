"""
Ottimizzazione di SL/TP per la strategia Donchian+LWTI+Volume, cercando di ridurre gli stop
colpiti e aumentare i take-profit colpiti — SENZA perdere di vista che questo è un vero
trade-off (allargare SL / stringere TP alza meccanicamente il win rate ma riduce il payout
per trade). Selezione parametri SOLO su train (70%), validazione onesta su test (30% mai
visto), stessa metodologia di tutto il resto del progetto.

Varianti di SL testate:
  - 'donchian': banda centrale Donchian (originale, come da specifica utente)
  - 'fraction': una frazione della distanza fino alla banda centrale (es 0.5 = SL a metà
    strada tra entry e banda centrale = SL più STRETTO del originale)
  - 'wide': un multiplo della distanza fino alla banda centrale (es 1.5 = SL oltre la banda
    centrale = SL più LARGO del originale)

Varianti di TP testate: rapporto rischio/rendimento da 1:1 a 4:1.
"""
import itertools
import numpy as np
import pandas as pd

from strategy_breakout import DonchianLWTIBreakoutStrategy
from backtest_breakout import SYMBOLS, load_and_resample_5m, FEE_PERCENT, SLIPPAGE_PERCENT


def simulate_variant(df, strategy, sl_multiplier, risk_reward, max_holding_bars=576):
    """sl_multiplier: moltiplica la distanza (entry - donchian_middle) originale.
    1.0 = originale (SL sulla banda centrale), <1 = SL più stretto, >1 = SL più largo."""
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

        base_risk = entry_price - donchian_middle[i]
        if base_risk <= 0:
            continue
        risk = base_risk * sl_multiplier
        stop_loss_price = entry_price - risk
        take_profit_price = entry_price + risk * risk_reward

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

        trades.append({'exit_reason': exit_reason, 'pnl_percent': net_pnl_percent})
        blocked_until = exit_idx

    return trades


def summarize(trades, n_days):
    if not trades:
        return {'n_trades': 0}
    pnl = np.array([t['pnl_percent'] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    reasons = pd.Series([t['exit_reason'] for t in trades]).value_counts()
    n = len(trades)
    return {
        'n_trades': n,
        'trades_per_day': n / n_days if n_days > 0 else 0,
        'win_rate_pct': 100 * len(wins) / n,
        'sl_hit_pct': 100 * reasons.get('STOP_LOSS', 0) / n,
        'tp_hit_pct': 100 * reasons.get('TAKE_PROFIT', 0) / n,
        'expectancy_pct_per_trade': pnl.mean(),
        'profit_factor': (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float('inf'),
    }


def split_train_test(df, train_frac=0.7):
    idx = int(len(df) * train_frac)
    return df.iloc[:idx].reset_index(drop=True), df.iloc[idx:].reset_index(drop=True)


if __name__ == '__main__':
    strategy = DonchianLWTIBreakoutStrategy(donchian_length=96, lwti_period=25,
                                             lwti_smoothing=20, volume_ma_length=30)

    data = {}
    for label, binance_symbol in SYMBOLS.items():
        df5 = load_and_resample_5m(binance_symbol)
        df_ind = strategy.calculate_indicators(df5)
        data[label] = df_ind

    sl_multipliers = [0.4, 0.5, 0.6, 0.75, 1.0, 1.25, 1.5]  # 1.0 = originale (banda centrale)
    risk_rewards = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]

    print("=" * 80)
    print(f"GRID SEARCH su TRAIN (70% iniziale) — {len(sl_multipliers)*len(risk_rewards)} combinazioni")
    print("=" * 80)

    results = []
    for sl_mult, rr in itertools.product(sl_multipliers, risk_rewards):
        all_trades = []
        total_days = 0.0
        for label, df in data.items():
            train_df, _ = split_train_test(df)
            trades = simulate_variant(train_df, strategy, sl_mult, rr)
            all_trades.extend(trades)
            total_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400
        s = summarize(all_trades, total_days / len(data))
        s['sl_mult'] = sl_mult
        s['rr'] = rr
        results.append(s)

    valid = [r for r in results if r.get('n_trades', 0) >= 50]
    if not valid:
        print("\n⚠️  Nessuna combinazione con >= 50 trade su train (campione dati troppo piccolo): "
              "fallback sulle combinazioni con almeno 1 trade, interpretare con cautela.")
        valid = [r for r in results if r.get('n_trades', 0) > 0]
    if not valid:
        print("\n❌ Nessuna combinazione ha generato trade su train: dataset troppo piccolo, impossibile procedere.")
        raise SystemExit(1)
    valid.sort(key=lambda r: r['expectancy_pct_per_trade'], reverse=True)

    print("\nTop 10 per expectancy (train, >= 50 trade):")
    print(f"{'SL mult':>8} {'RR':>5} {'trade':>6} {'win%':>6} {'SLhit%':>7} {'TPhit%':>7} {'exp%':>8} {'pf':>6}")
    for r in valid[:10]:
        print(f"{r['sl_mult']:>8.2f} {r['rr']:>5.1f} {r['n_trades']:>6d} {r['win_rate_pct']:>6.1f} "
              f"{r['sl_hit_pct']:>7.1f} {r['tp_hit_pct']:>7.1f} {r['expectancy_pct_per_trade']:>+8.3f} {r['profit_factor']:>6.2f}")

    # Mostra anche la combinazione con MENO stop-loss in assoluto (tra quelle valide), per rispondere
    # direttamente alla richiesta "meno SL possibili", anche se non fosse la migliore per expectancy
    least_sl = min(valid, key=lambda r: r['sl_hit_pct'])
    print(f"\nCombinazione con meno SL colpiti (train): SL_mult={least_sl['sl_mult']} RR={least_sl['rr']} "
          f"-> SLhit={least_sl['sl_hit_pct']:.1f}% TPhit={least_sl['tp_hit_pct']:.1f}% exp={least_sl['expectancy_pct_per_trade']:+.3f}%")

    best = valid[0]
    print(f"\n✅ Migliore per expectancy su train: SL_mult={best['sl_mult']} RR={best['rr']}")

    print("\n" + "=" * 80)
    print(f"VALIDAZIONE OUT-OF-SAMPLE (SL_mult={best['sl_mult']}, RR={best['rr']}, ultimi 30% mai visti)")
    print("=" * 80)

    train_trades, test_trades = [], []
    train_days = test_days = 0.0
    for label, df in data.items():
        train_df, test_df = split_train_test(df)
        train_trades.extend(simulate_variant(train_df, strategy, best['sl_mult'], best['rr']))
        test_trades.extend(simulate_variant(test_df, strategy, best['sl_mult'], best['rr']))
        train_days += (train_df['timestamp'].iloc[-1] - train_df['timestamp'].iloc[0]).total_seconds() / 86400
        test_days += (test_df['timestamp'].iloc[-1] - test_df['timestamp'].iloc[0]).total_seconds() / 86400

    print("\n--- TRAIN ---")
    print(summarize(train_trades, train_days / len(data)))
    print("\n--- TEST (OUT-OF-SAMPLE) ---")
    print(summarize(test_trades, test_days / len(data)))

    # Confronto con l'originale (SL su banda centrale, RR 2:1) sullo stesso periodo di test
    print("\n--- Per confronto: ORIGINALE (SL_mult=1.0, RR=2.0) sullo stesso TEST ---")
    orig_test_trades = []
    for label, df in data.items():
        _, test_df = split_train_test(df)
        orig_test_trades.extend(simulate_variant(test_df, strategy, 1.0, 2.0))
    print(summarize(orig_test_trades, test_days / len(data)))
