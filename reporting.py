"""Sistema di reportistica per il bot."""
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from config import Config

class Reporter:
    """Gestisce reportistica e logging."""
    
    def __init__(self):
        self.reports_dir = Path("reports")
        self.reports_dir.mkdir(exist_ok=True)
        
        # File di log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_file = self.reports_dir / f"session_{timestamp}.json"
        self.csv_file = self.reports_dir / f"trades_{timestamp}.csv"
        
        # Dati sessione
        self.session_data = {
            'start_time': datetime.now().isoformat(),
            'symbols': Config.SYMBOLS,
            'config': {
                'z_score_threshold': Config.Z_SCORE_THRESHOLD,
                'min_confidence': Config.MIN_CONFIDENCE,
                'filters': {
                    'prev_zscore': Config.USE_PREV_ZSCORE_FILTER,
                    'momentum': Config.USE_MOMENTUM_FILTER,
                    'ma': Config.USE_MA_FILTER
                }
            },
            'trades': [],
            'portfolio': {},
            'statistics': {
                'total_trades': 0,
                'buy_trades': 0,
                'sell_trades': 0,
                'total_pnl': 0.0,  # PnL percentuale totale (calcolato correttamente)
                'total_pnl_usd': 0.0,  # PnL totale in USD per trade chiusi
                'total_invested_value': 0.0,  # Valore totale investito in tutti i trade chiusi
                'winning_trades': 0,
                'losing_trades': 0,
                'total_fees_paid_session': 0.0,  # Fee pagate solo in questa sessione
                'total_wins_usd': 0.0,  # Totale vincite in USD
                'total_losses_usd': 0.0,  # Totale perdite in USD (valore assoluto)
                'avg_win_usd': 0.0,  # Media vincite in USD
                'avg_loss_usd': 0.0,  # Media perdite in USD (valore assoluto)
                'risk_reward_ratio': 0.0  # Rapporto rischio/rendimento (avg_loss / avg_win)
            },
            'portfolio_value': {
                'initial_usdt': None,  # Valore iniziale portafoglio
                'initial_positions_value': 0.0,  # Valore posizioni iniziali (se presenti)
                'final_usdt': None,  # Valore finale portafoglio
                'final_positions_value': 0.0  # Valore posizioni finali (se presenti)
            }
        }
        
        # Inizializza CSV
        self._init_csv()
    
    def _init_csv(self):
        """Inizializza file CSV."""
        with open(self.csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp', 'symbol', 'action', 'price', 'quantity',
                'balance', 'pnl_percent', 'pnl_usd', 'fee_usd', 'z_score', 'confidence'
            ])
    
    def log_trade(self, symbol: str, action: str, price: float, quantity: float,
                  balance: float, pnl_percent: Optional[float] = None, 
                  fee_usd: float = 0.0, z_score: float = 0, confidence: float = 0,
                  pnl_usd: Optional[float] = None, entry_value_usd: Optional[float] = None):
        """
        Logga una trade.
        
        Args:
            entry_value_usd: Valore investito nel trade (entry_price * quantity) - usato per calcolare PnL % totale
        """
        trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'action': action,
            'price': price,
            'quantity': quantity,
            'balance': balance,
            'pnl_percent': pnl_percent,
            'pnl_usd': pnl_usd,  # Aggiunto PnL in USD
            'fee_usd': fee_usd,
            'z_score': z_score,
            'confidence': confidence,
            'entry_value_usd': entry_value_usd  # Valore investito
        }
        
        self.session_data['trades'].append(trade)
        
        # Aggiorna fee totali sessione corrente
        if fee_usd > 0:
            self.session_data['statistics']['total_fees_paid_session'] += fee_usd
        
        # Aggiorna statistiche
        if action == 'BUY':
            self.session_data['statistics']['buy_trades'] += 1
        elif action == 'SELL':
            self.session_data['statistics']['sell_trades'] += 1
            if pnl_percent is not None and pnl_usd is not None:
                if pnl_usd > 0:
                    self.session_data['statistics']['winning_trades'] += 1
                    self.session_data['statistics']['total_wins_usd'] += pnl_usd
                else:
                    self.session_data['statistics']['losing_trades'] += 1
                    self.session_data['statistics']['total_losses_usd'] += abs(pnl_usd)  # Valore assoluto
                
                # Aggiungi PnL USD
                self.session_data['statistics']['total_pnl_usd'] += pnl_usd
                
                # Aggiungi valore investito (se disponibile)
                if entry_value_usd is not None:
                    self.session_data['statistics']['total_invested_value'] += entry_value_usd
                
                # Calcola PnL percentuale totale CORRETTO: (PnL totale USD / Valore totale investito) * 100
                total_invested = self.session_data['statistics']['total_invested_value']
                if total_invested > 0:
                    self.session_data['statistics']['total_pnl'] = (
                        self.session_data['statistics']['total_pnl_usd'] / total_invested
                    ) * 100
                
                # Calcola medie e risk/reward ratio
                winning_count = self.session_data['statistics']['winning_trades']
                losing_count = self.session_data['statistics']['losing_trades']
                
                if winning_count > 0:
                    self.session_data['statistics']['avg_win_usd'] = (
                        self.session_data['statistics']['total_wins_usd'] / winning_count
                    )
                if losing_count > 0:
                    self.session_data['statistics']['avg_loss_usd'] = (
                        self.session_data['statistics']['total_losses_usd'] / losing_count
                    )
                
                # Risk/Reward Ratio = Media Perdite / Media Vincite
                avg_win = self.session_data['statistics']['avg_win_usd']
                avg_loss = self.session_data['statistics']['avg_loss_usd']
                if avg_win > 0 and avg_loss > 0:
                    self.session_data['statistics']['risk_reward_ratio'] = avg_loss / avg_win
        
        self.session_data['statistics']['total_trades'] += 1
        
        # Aggiungi a CSV
        with open(self.csv_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                trade['timestamp'],
                symbol,
                action,
                price,
                quantity,
                balance,
                pnl_percent or 0.0,
                pnl_usd or 0.0,  # Aggiunto PnL USD
                fee_usd,
                z_score,
                confidence
            ])
    
    def set_initial_portfolio_value(self, value: float, balance_type: str = None):
        """Imposta valore iniziale del portafoglio."""
        if self.session_data['portfolio_value']['initial_usdt'] is None:
            self.session_data['portfolio_value']['initial_usdt'] = value
            self.session_data['portfolio_value']['balance_type'] = balance_type
    
    def update_portfolio(self, portfolio: Dict):
        """Aggiorna stato portafoglio."""
        self.session_data['portfolio'] = portfolio.copy()
    
    def generate_periodic_report(self, position_manager, last_prices: Dict, balance: float, balance_type: str = 'ETH', api_client=None):
        """
        Genera report periodico.
        CRITICAL FIX: Usa quantità REALI dall'API invece di positions_state.json
        """
        print("\n" + "="*70)
        print("📊 REPORT PORTAFOGLIO")
        print("="*70)
        
        # CRITICAL FIX: Ottieni valore portafoglio REALE dall'API
        use_api_data = False
        portfolio_data = None
        if api_client and balance_type == Config.QUOTE_ASSET and hasattr(api_client, 'get_portfolio_value_from_api'):
            portfolio_data = api_client.get_portfolio_value_from_api()
            if portfolio_data:
                use_api_data = True
                total_portfolio_value = portfolio_data['total_value_usdt']
                balance = portfolio_data['usdt_balance']
        
        # Fallback al vecchio metodo se API non disponibile
        if not use_api_data:
            print(f"\n   ⚠️  Usando dati da positions_state.json (potrebbe essere inaccurato!)")
            total_portfolio_value = balance
            if balance_type == Config.QUOTE_ASSET:
                # Per CEX: aggiungi valore posizioni aperte in USD
                for symbol in Config.SYMBOLS:
                    position = position_manager.get_position(symbol)
                    if position == 'LONG':
                        current_price = last_prices.get(symbol)
                        quantity = position_manager.get_quantity(symbol)
                        if current_price and quantity > 0:
                            position_value = quantity * current_price
                            total_portfolio_value += position_value
            else:
                # Per DEX: converti ETH a USD e aggiungi valore posizioni
                eth_price = 3000.0  # Fallback
                total_portfolio_value_usd = balance * eth_price
                for symbol in Config.SYMBOLS:
                    position = position_manager.get_position(symbol)
                    if position == 'LONG':
                        current_price = last_prices.get(symbol)
                        quantity = position_manager.get_quantity(symbol)
                        if current_price and quantity > 0:
                            position_value = quantity * current_price
                            total_portfolio_value_usd += position_value
                total_portfolio_value = total_portfolio_value_usd
        
        # Calcola fee totali pagate SOLO in questa sessione
        total_fees_paid_session = self.session_data['statistics'].get('total_fees_paid_session', 0.0)
        
        # Valore portafoglio iniziale e finale
        initial_value = self.session_data['portfolio_value'].get('initial_usdt')
        
        print(f"\n💼 VALORE PORTAFOGLIO:")
        if initial_value is not None:
            portfolio_pnl_usd = total_portfolio_value - initial_value
            portfolio_pnl_percent = (portfolio_pnl_usd / initial_value * 100) if initial_value > 0 else 0.0
            pnl_emoji = "📈" if portfolio_pnl_usd >= 0 else "📉"
            
            print(f"   Iniziale:  ${initial_value:>12,.2f}")
            print(f"   Attuale:   ${total_portfolio_value:>12,.2f}")
            print(f"   {pnl_emoji} Variazione: {portfolio_pnl_percent:>+6.2f}% (${portfolio_pnl_usd:>+10,.2f})")
            print(f"   💸 Fee:      ${total_fees_paid_session:>12,.2f}")
        else:
            print(f"   Attuale:   ${total_portfolio_value:>12,.2f}")
            print(f"   💸 Fee:      ${total_fees_paid_session:>12,.2f}")
        
        # Posizioni attive - CRITICAL FIX: Usa dati reali dall'API se disponibili
        active_positions = []
        
        if use_api_data and portfolio_data:
            # Usa quantità REALI dall'API
            crypto_values = portfolio_data['crypto_values']
            for symbol in Config.SYMBOLS:
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                if base_asset in crypto_values and crypto_values[base_asset]['quantity'] > 0:
                    # CRITICAL: Ignora dust (< $10) per evitare confusione
                    if crypto_values[base_asset]['value_usd'] < 10.0:
                        continue
                    
                    real_quantity = crypto_values[base_asset]['quantity']
                    current_price = crypto_values[base_asset]['price']
                    entry_price = position_manager.entry_prices.get(symbol)
                    
                    # CRITICAL FIX: Usa get_pnl() con quantità reale dall'API per calcolo accurato
                    if entry_price and entry_price > 0:
                        pnl_result = position_manager.get_pnl(
                            symbol, 
                            current_price, 
                            include_fees=True,
                            quantity_override=real_quantity  # ← USA QUANTITÀ REALE DALL'API!
                        )
                        if pnl_result:
                            pnl_percent, pnl_usd = pnl_result
                        else:
                            # Fallback: calcolo semplice
                            pnl_usd = (current_price - entry_price) * real_quantity
                            pnl_percent = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl_usd = 0.0
                        pnl_percent = 0.0
                        entry_price = current_price  # Fallback
                    
                    active_positions.append({
                        'symbol': symbol,
                        'entry': entry_price,
                        'current': current_price,
                        'quantity': real_quantity,
                        'pnl_percent': pnl_percent,
                        'pnl_usd': pnl_usd,
                        'source': 'API'
                    })
        else:
            # Fallback: usa position_manager
            for symbol in Config.SYMBOLS:
                position = position_manager.get_position(symbol)
                entry_price = position_manager.entry_prices.get(symbol)
                current_price = last_prices.get(symbol)
                quantity = position_manager.get_quantity(symbol)
                
                if position == 'LONG' and entry_price and current_price and quantity > 0:
                    pnl_result = position_manager.get_pnl(symbol, current_price, include_fees=True)
                    if pnl_result:
                        pnl_percent, pnl_usd = pnl_result
                        active_positions.append({
                            'symbol': symbol,
                            'entry': entry_price,
                            'current': current_price,
                            'quantity': quantity,
                            'pnl_percent': pnl_percent,
                            'pnl_usd': pnl_usd,
                            'source': 'STATE'
                        })
        
        if active_positions:
            print(f"\n📈 POSIZIONI APERTE ({len(active_positions)}/{len(Config.SYMBOLS)}):")
            for pos in active_positions:
                pnl_emoji = "📈" if pos['pnl_usd'] > 0 else "📉"
                value_usd = pos['quantity'] * pos['current']
                print(f"   {pos['symbol']:10} {pnl_emoji} {pos['pnl_percent']:>+6.2f}%  "
                      f"Valore: ${value_usd:>10,.2f}  "
                      f"Entry: ${pos['entry']:>8.2f} → ${pos['current']:>8.2f}")
        else:
            print(f"\n📈 POSIZIONI: Nessuna posizione aperta")
        
        # Statistiche trading semplificate
        stats = self.session_data['statistics']
        print(f"\n📊 OPERAZIONI:")
        print(f"   BUY: {stats['buy_trades']}  |  SELL: {stats['sell_trades']}  |  Totale: {stats['total_trades']}")
        
        # API calls (solo totale)
        if api_client and hasattr(api_client, 'api_calls'):
            total_calls = sum(api_client.api_calls.values())
            if total_calls > 0:
                print(f"   🌐 API Calls: {total_calls:,}")
        
        print("="*70 + "\n")
    
    def generate_final_report(self, position_manager=None, last_prices: Dict = None, final_balance: float = None, balance_type: str = None, api_client=None):
        """
        Genera report finale di sessione.
        CRITICAL FIX: Usa quantità REALI dall'API invece di positions_state.json
        """
        self.session_data['end_time'] = datetime.now().isoformat()
        
        # Calcola durata
        start = datetime.fromisoformat(self.session_data['start_time'])
        end = datetime.fromisoformat(self.session_data['end_time'])
        duration = end - start
        
        # CRITICAL FIX: Ottieni valore finale REALE dall'API
        use_api_data = False
        portfolio_data = None
        if api_client and balance_type == Config.QUOTE_ASSET and hasattr(api_client, 'get_portfolio_value_from_api'):
            portfolio_data = api_client.get_portfolio_value_from_api()
            if portfolio_data:
                use_api_data = True
                final_portfolio_value = portfolio_data['total_value_usdt']
                final_balance = portfolio_data['usdt_balance']
        
        # Fallback al vecchio metodo se API non disponibile
        if not use_api_data:
            final_portfolio_value = None
            if final_balance is not None:
                if balance_type == Config.QUOTE_ASSET:
                    # Calcola valore totale: balance USDT + valore posizioni aperte
                    final_portfolio_value = final_balance
                    
                    # Aggiungi valore delle posizioni aperte
                    if position_manager and last_prices:
                        for symbol in Config.SYMBOLS:
                            position = position_manager.get_position(symbol)
                            if position == 'LONG':
                                current_price = last_prices.get(symbol)
                                quantity = position_manager.get_quantity(symbol)
                                if current_price and quantity > 0:
                                    position_value = quantity * current_price
                                    final_portfolio_value += position_value
                elif balance_type == 'ETH':
                    # Per DEX: converti ETH a USD e aggiungi posizioni (vecchio metodo)
                    eth_price = 3000.0  # Fallback
                    final_portfolio_value = final_balance * eth_price
                    if position_manager and last_prices:
                        for symbol in Config.SYMBOLS:
                            position = position_manager.get_position(symbol)
                            if position == 'LONG':
                                current_price = last_prices.get(symbol)
                                quantity = position_manager.get_quantity(symbol)
                                if current_price and quantity > 0:
                                    position_value = quantity * current_price
                                    final_portfolio_value += position_value
        
        # Salva valore finale
        if final_portfolio_value is not None:
            self.session_data['portfolio_value']['final_usdt'] = final_portfolio_value
        
        # Calcola fee totali pagate SOLO in questa sessione (non da sessioni precedenti)
        total_fees_paid_session = self.session_data['statistics'].get('total_fees_paid_session', 0.0)
        
        print("\n" + "="*70)
        print("📋 REPORT FINALE SESSIONE")
        print("="*70)
        
        print(f"\n⏱️  Durata Sessione: {duration}")
        print(f"📊 Coppie Monitorate: {len(Config.SYMBOLS)} - {', '.join(Config.SYMBOLS)}")
        
        # Valore portafoglio iniziale e finale
        initial_value = self.session_data['portfolio_value'].get('initial_usdt')
        if initial_value is not None and final_portfolio_value is not None:
            # Calcola PnL totale (valore finale - valore iniziale)
            # Questo include già le fee perché le fee sono state pagate e riducono il balance
            portfolio_pnl_usd = final_portfolio_value - initial_value
            portfolio_pnl_percent = (portfolio_pnl_usd / initial_value * 100) if initial_value > 0 else 0.0
            pnl_emoji = "📈" if portfolio_pnl_usd >= 0 else "📉"
            
            # Verifica che il calcolo sia corretto: valore iniziale + PnL = valore finale
            # (con tolleranza per arrotondamenti)
            calculated_final = initial_value + portfolio_pnl_usd
            discrepancy = abs(final_portfolio_value - calculated_final)
            
            source_info = "✅ [DATI REALI DA API]" if use_api_data else "⚠️ [DA STATE - POTENZIALMENTE INACCURATO]"
            print(f"\n💼 VALORE PORTAFOGLIO {source_info}:")
            print(f"   Valore Iniziale: {initial_value:.2f} {Config.QUOTE_ASSET}")
            print(f"   Valore Finale: {final_portfolio_value:.2f} {Config.QUOTE_ASSET}")
            print(f"   {pnl_emoji} Variazione Totale: {portfolio_pnl_percent:+.2f}% (${portfolio_pnl_usd:+.2f})")
            print(f"   💸 Fee Pagate (Questa Sessione): ${total_fees_paid_session:.2f}")
            
            # Verifica: Valore Iniziale + Variazione = Valore Finale
            if discrepancy > 0.01:  # Tolleranza per arrotondamenti
                print(f"   ⚠️  Nota: Discrepanza di ${discrepancy:.2f} (probabilmente dovuta ad arrotondamenti)")
        
        # Posizioni rimaste aperte
        active_positions = []
        if position_manager and last_prices:
            for symbol in Config.SYMBOLS:
                position = position_manager.get_position(symbol)
                entry_price = position_manager.entry_prices.get(symbol)
                current_price = last_prices.get(symbol)
                quantity = position_manager.get_quantity(symbol)  # Usa metodo helper
                
                if position == 'LONG' and entry_price and current_price and quantity > 0:
                    pnl_result = position_manager.get_pnl(symbol, current_price, include_fees=True)
                    if pnl_result:
                        pnl_percent, pnl_usd = pnl_result
                        active_positions.append({
                            'symbol': symbol,
                            'entry': entry_price,
                            'current': current_price,
                            'quantity': quantity,
                            'pnl_percent': pnl_percent,
                            'pnl_usd': pnl_usd
                        })
        
        if active_positions:
            print(f"\n📈 Posizioni Rimanenti Aperte ({len(active_positions)}/{len(Config.SYMBOLS)}):")
            for pos in active_positions:
                pnl_emoji = "📈" if pos['pnl_usd'] > 0 else "📉"
                print(f"   {pos['symbol']:12} | Entry: ${pos['entry']:>10.2f} | "
                      f"Current: ${pos['current']:>10.2f} | "
                      f"Qty: {pos['quantity']:.6f} | "
                      f"{pnl_emoji} {pos['pnl_percent']:>+6.2f}% (${pos['pnl_usd']:>+8.2f})")
        else:
            print("\n   ⚪ Nessuna posizione aperta")
        
        # Statistiche trading
        stats = self.session_data['statistics']
        print(f"\n📊 Statistiche Trading:")
        print(f"   Totale Trade: {stats['total_trades']}")
        print(f"   BUY: {stats['buy_trades']} | SELL: {stats['sell_trades']}")
        
        # Win Rate e statistiche dettagliate
        total_closed_trades = stats['winning_trades'] + stats['losing_trades']
        if total_closed_trades > 0:
            win_rate = (stats['winning_trades'] / total_closed_trades) * 100
            total_invested = stats.get('total_invested_value', 0.0)
            print(f"   ✅ Trade Vincenti: {stats['winning_trades']}")
            print(f"   ❌ Trade Perdenti: {stats['losing_trades']}")
            print(f"   📊 Win Rate: {win_rate:.1f}%")
            
            # Statistiche vincite/perdite (sempre mostrate se ci sono trade chiusi)
            avg_win = stats.get('avg_win_usd', 0.0)
            avg_loss = stats.get('avg_loss_usd', 0.0)
            total_wins = stats.get('total_wins_usd', 0.0)
            total_losses = stats.get('total_losses_usd', 0.0)
            risk_reward = stats.get('risk_reward_ratio', 0.0)
            
            print(f"   📈 Media Vincite: ${avg_win:.2f} | 📉 Media Perdite: ${avg_loss:.2f}")
            print(f"   💵 Totale Vincite: ${total_wins:.2f} | 💸 Totale Perdite: ${total_losses:.2f}")
            
            # Risk/Reward Ratio richiede entrambe le medie > 0
            if avg_win > 0 and avg_loss > 0:
                print(f"   ⚖️  Risk/Reward Ratio: {risk_reward:.2f} (ideale < 1.0)")
                if risk_reward > 1.0:
                    print(f"   ⚠️  ATTENZIONE: Le perdite medie sono {risk_reward:.2f}x le vincite medie!")
                    print(f"   💡 Suggerimento: Considera take-profit più alti o stop-loss più stretti")
            elif avg_win > 0:
                print(f"   ⚖️  Risk/Reward Ratio: N/A (nessuna perdita registrata)")
            elif avg_loss > 0:
                print(f"   ⚖️  Risk/Reward Ratio: N/A (nessuna vincita registrata)")
            
            if total_invested > 0:
                print(f"   💰 PnL Trade Chiusi: {stats['total_pnl']:+.2f}% (${stats['total_pnl_usd']:+.2f}) su ${total_invested:.2f} investiti")
            else:
                print(f"   💰 PnL Trade Chiusi: ${stats['total_pnl_usd']:+.2f} (valore investito non disponibile)")
        else:
            print(f"   📊 Win Rate: N/A (nessun trade completato)")
        
        # Ultime 5 trade
        if self.session_data['trades']:
            print(f"\n📝 Ultime 5 Operazioni:")
            for trade in self.session_data['trades'][-5:]:
                pnl_str = ""
                if trade.get('pnl_percent') is not None:
                    pnl_str = f" | PnL: {trade['pnl_percent']:+.2f}%"
                fee_str = f" | Fee: ${trade.get('fee_usd', 0.0):.2f}" if trade.get('fee_usd', 0.0) > 0 else ""
                print(f"   [{trade['timestamp'][11:19]}] {trade['symbol']:12} | "
                      f"{trade['action']:4} @ ${trade['price']:>10.2f} | "
                      f"Z: {trade.get('z_score', 0):>5.2f} | Conf: {trade.get('confidence', 0):.0%}{pnl_str}{fee_str}")
        
        # Salva report JSON
        with open(self.session_file, 'w') as f:
            json.dump(self.session_data, f, indent=2)
        
        print(f"\n💾 Report salvato in:")
        print(f"   JSON: {self.session_file}")
        print(f"   CSV:  {self.csv_file}")
        print("="*70 + "\n")

