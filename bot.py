"""Bot principale per trading multi-coppia."""
import time
import os
import pandas as pd
from datetime import datetime
from api_client import APIClient, DEXClient
from strategy import Strategy
from config import Config
from position_manager import PositionManager
from reporting import Reporter

class TradingBot:
    """Bot di trading principale."""
    
    def __init__(self):
        Config.validate()
        
        if Config.TRADING_MODE == 'DEX':
            self.api = DEXClient()
            self.mode = 'DEX'
        else:
            self.api = APIClient()
            self.mode = 'CEX'
        
        # Alchemy DISABILITATO - Non serve per CEX trading
        # I dati on-chain Ethereum sono irrilevanti per Binance CEX
        self.strategy = Strategy(onchain_client=None)
        self.position_manager = PositionManager(Config.SYMBOLS)
        self.last_prices = {symbol: None for symbol in Config.SYMBOLS}
        
        # Salva stato periodicamente (ogni 10 cicli)
        self.save_state_interval = 10
        self.reporter = Reporter()
        self.report_interval = Config.REPORT_INTERVAL
        self.cycle_count = 0
    
    def run(self):
        """Loop principale del bot."""
        print(f"🤖 Bot avviato - Modalità: {self.mode}")
        print(f"   📊 Coppie: {len(Config.SYMBOLS)} - {', '.join(Config.SYMBOLS)}")
        print(f"   ⏱️  Timeframe: {Config.TIMEFRAME}")
        print(f"   📈 Strategia: Z-score threshold={Config.Z_SCORE_THRESHOLD}")
        
        if self.mode == 'DEX':
            balance = self.api.get_balance()
            print(f"   💼 Wallet: {self.api.address}")
            print(f"   💰 Balance: {balance:.6f} ETH")
            # Calcola valore iniziale portafoglio (balance + posizioni già aperte al prezzo CORRENTE)
            # IMPORTANTE: Usa prezzo corrente, non entry_price, per riflettere il valore reale all'avvio
            eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or 3000.0
            initial_portfolio_value = balance * eth_price
            # Aggiungi valore delle posizioni già aperte (se ripristinate da stato salvato)
            for symbol in Config.SYMBOLS:
                position = self.position_manager.get_position(symbol)
                if position == 'LONG':
                    quantity = self.position_manager.get_quantity(symbol)  # Usa metodo helper
                    if quantity > 0:
                        # Ottieni prezzo CORRENTE (non entry_price) per calcolare valore reale all'avvio
                        current_price = self.api.get_current_price(symbol)
                        if current_price:
                            position_value = quantity * current_price
                            initial_portfolio_value += position_value
                            # Salva anche il prezzo corrente per il report
                            self.last_prices[symbol] = current_price
            self.reporter.set_initial_portfolio_value(initial_portfolio_value, balance_type='ETH')
        elif self.mode == 'CEX':
            # Ottieni valore REALE del portafoglio dall'API Binance
            print(f"   🔄 Recupero valore portafoglio da API...")
            portfolio_data = self.api.get_portfolio_value_from_api()
            
            if portfolio_data:
                actual_portfolio_value = portfolio_data['total_value_usdt']
                balance_usdt = portfolio_data['usdt_balance']
                
                print(f"   💰 Balance {Config.QUOTE_ASSET}: {balance_usdt:.2f}")
                print(f"   💼 Valore Totale Portafoglio: ${actual_portfolio_value:,.2f}")
                
                # Stampa dettaglio crypto (solo quelle con balance > 0)
                for asset, data in sorted(portfolio_data['crypto_values'].items()):
                    if data['quantity'] > 0 and asset != Config.QUOTE_ASSET:
                        print(f"      {asset}: {data['quantity']:.8f} (${data['value_usd']:,.2f})")
                
                if Config.USE_TESTNET:
                    print(f"   🧪 Testnet: Attivo")
                
                # Salva i prezzi correnti per il reporting
                for symbol in Config.SYMBOLS:
                    current_price = self.api.get_current_price(symbol)
                    if current_price:
                        self.last_prices[symbol] = current_price
                
                # CRITICAL FIX: Verifica che il valore iniziale includa le posizioni già caricate da positions_state.json
                # Questo risolve il bug dove il bot riavviato con posizioni aperte calcolava il valore iniziale solo dal balance USDT
                print(f"\n   🔍 DEBUG VALORE INIZIALE:")
                print(f"      Balance {Config.QUOTE_ASSET}: {balance_usdt:,.2f}")
                print(f"      Valore da API: ${actual_portfolio_value:,.2f}")
                
                positions_value_from_state = 0.0
                positions_count = 0
                for symbol in Config.SYMBOLS:
                    if self.position_manager.get_position(symbol) == 'LONG':
                        qty = self.position_manager.get_quantity(symbol)
                        entry_price = self.position_manager.get_entry_price(symbol)
                        current_price = self.last_prices.get(symbol)
                        if qty > 0 and current_price and current_price > 0:
                            position_value = qty * current_price
                            positions_value_from_state += position_value
                            positions_count += 1
                            print(f"      {symbol}: {qty:.6f} @ ${current_price:.2f} = ${position_value:,.2f} (entry: ${entry_price:.2f})")
                
                print(f"      Totale Posizioni da State: ${positions_value_from_state:,.2f} ({positions_count} posizioni)")
                
                # Se ci sono posizioni in positions_state.json, usa il MASSIMO tra API e (USDT + posizioni)
                # Questo gestisce il caso in cui positions_state.json ha posizioni ma l'API non le vede
                if positions_value_from_state > 0:
                    calculated_value = balance_usdt + positions_value_from_state
                    print(f"      Valore Calcolato ({Config.QUOTE_ASSET} + State): {calculated_value:,.2f}")
                    
                    # Usa il maggiore dei due valori
                    if calculated_value > actual_portfolio_value:
                        print(f"   ⚠️  DISCREPANZA RILEVATA! Uso valore calcolato.")
                        actual_portfolio_value = calculated_value
                    else:
                        print(f"   ✅ Valori coerenti, uso valore da API.")
                
                # Usa valore totale per il report
                self.reporter.set_initial_portfolio_value(actual_portfolio_value, balance_type=Config.QUOTE_ASSET)
            else:
                # Fallback al vecchio metodo se API fallisce
                balance_usdt = self.api.get_account_balance(Config.QUOTE_ASSET)
                print(f"   ⚠️  Fallback: usando solo balance {Config.QUOTE_ASSET}")
                print(f"   💰 Balance {Config.QUOTE_ASSET}: {balance_usdt:.2f}")
                
                # CRITICAL FIX: Anche nel fallback, includi le posizioni già caricate
                positions_value = 0.0
                for symbol in Config.SYMBOLS:
                    if self.position_manager.get_position(symbol) == 'LONG':
                        # Ottieni prezzo corrente
                        current_price = self.api.get_current_price(symbol)
                        if current_price:
                            self.last_prices[symbol] = current_price
                            qty = self.position_manager.get_quantity(symbol)
                            if qty > 0:
                                positions_value += qty * current_price
                
                initial_value = balance_usdt + positions_value
                if positions_value > 0:
                    print(f"   📊 Valore Posizioni Aperte: ${positions_value:,.2f}")
                    print(f"   💼 Valore Totale Iniziale: ${initial_value:,.2f}")
                
                if Config.USE_TESTNET:
                    print(f"   🧪 Testnet: Attivo")
                self.reporter.set_initial_portfolio_value(initial_value, balance_type=Config.QUOTE_ASSET)
        
        print("\n" + "="*60)
        
        try:
            while True:
                self.execute_cycle()
                time.sleep(Config.CYCLE_INTERVAL)  # Attesa tra cicli (configurabile)
                
        except KeyboardInterrupt:
            print("\n\nBot fermato dall'utente")
            # Salva stato posizioni prima di chiudere
            self.position_manager.save_state()
            self.print_summary()
            # Ottieni balance finale per report con valori REALI dall'API
            if self.mode == 'CEX':
                print("\n🔄 Recupero valore finale portafoglio da API...")
                portfolio_data = self.api.get_portfolio_value_from_api()
                if portfolio_data:
                    actual_final_balance = portfolio_data['total_value_usdt']
                    final_balance = actual_final_balance
                    print(f"   💼 Valore Finale Portafoglio (da API): ${actual_final_balance:,.2f}")
                else:
                    # Fallback
                    actual_final_balance = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else 0.0
                    final_balance = actual_final_balance
                    print(f"   ⚠️  Fallback: usando solo balance {Config.QUOTE_ASSET}: {actual_final_balance:.2f}")
                balance_type = Config.QUOTE_ASSET
            else:
                final_balance = self.api.get_balance() if hasattr(self.api, 'get_balance') else 0.0
                balance_type = 'ETH'
            self.reporter.generate_final_report(self.position_manager, self.last_prices, final_balance, balance_type, api_client=self.api)
        except Exception as e:
            print(f"Errore: {e}")
            # Salva stato anche in caso di errore
            self.position_manager.save_state()
            self.print_summary()
            # Ottieni balance finale per report
            if self.mode == 'CEX':
                final_balance = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else 0.0
                balance_type = Config.QUOTE_ASSET
            else:
                final_balance = self.api.get_balance() if hasattr(self.api, 'get_balance') else 0.0
                balance_type = 'ETH'
            self.reporter.generate_final_report(self.position_manager, self.last_prices, final_balance, balance_type, api_client=self.api)
    
    def execute_cycle(self):
        """Esegue un ciclo di trading per tutte le coppie."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] 🔄 Ciclo trading per {len(Config.SYMBOLS)} coppie")
        
        self.cycle_count += 1
        
        for i, symbol in enumerate(Config.SYMBOLS):
            try:
                self.execute_pair_cycle(symbol)
            except Exception as e:
                print(f"❌ Errore per {symbol}: {e}")
                import traceback
                traceback.print_exc()  # Stampa traceback completo per debug
        
        # Mostra riepilogo posizioni
        self.print_positions_summary()
        
        # Salva stato periodicamente
        if self.cycle_count % self.save_state_interval == 0:
            self.position_manager.save_state()
        
        # Report periodico
        if self.cycle_count % self.report_interval == 0:
            # Ottieni balance corretto in base alla modalità
            if self.mode == 'CEX':
                actual_balance = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else 0.0
                balance = (actual_balance)  # Applica limite capitale
                balance_type = Config.QUOTE_ASSET
            else:
                balance = self.api.get_balance() if hasattr(self.api, 'get_balance') else 0.0
                balance_type = 'ETH'
            self.reporter.generate_periodic_report(
                self.position_manager,
                self.last_prices,
                balance,
                balance_type=balance_type,
                api_client=self.api if self.mode == 'CEX' else None
            )
    
    def execute_pair_cycle(self, symbol: str):
        """Esegue ciclo per una singola coppia."""
        if self.mode == 'CEX':
            # Fetch dati
            df = self.api.get_klines(symbol=symbol, limit=Config.LOOKBACK_PERIOD + 10)
            if df is None or len(df) < Config.LOOKBACK_PERIOD:
                return
            
            # Calcola indicatori
            df = self.strategy.calculate_indicators(df)
            if df is None:
                return
            
            # Ottieni segnale
            signal = self.strategy.get_signal(df)
            confidence = self.strategy.get_confidence(df)
            
            # Prezzo corrente
            current_price = self.api.get_current_price(symbol=symbol)
            if current_price is None:
                return
            
            self.last_prices[symbol] = current_price
            
            # Log stato
            self.log_status(symbol, df, signal, confidence, current_price)
            
            # Ottieni z_score per logging
            last = df.iloc[-1]
            z_score = last['z_score'] if 'z_score' in last else 0.0
            
            # Calcola capitale totale per modalità accumulo
            total_capital = None
            max_position_value = None
            if Config.USE_POSITION_ACCUMULATION:
                # Ottieni balance disponibile
                balance = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else 0.0
                balance = balance if balance is not None else 0.0  # Fix: gestisci None da API
                
                # CRITICAL FIX: Con CAPITAL_LIMIT, il limite è sul TOTALE, non sul balance
                # Calcola il valore delle posizioni già aperte
                positions_value = 0.0
                for sym in Config.SYMBOLS:
                    pos = self.position_manager.get_position(sym)
                    if pos == 'LONG':
                        qty = self.position_manager.get_quantity(sym)
                        price = self.last_prices.get(sym)
                        if qty > 0 and price and price > 0:
                            positions_value += qty * price
                
                # Calcola capitale totale: balance reale + valore posizioni
                total_capital = balance + positions_value
                
                # Assicurati che total_capital non sia None
                if total_capital is None or total_capital < 0:
                    total_capital = 0.0
                
                # Calcola cap massimo per questa coppia
                max_position_value = total_capital * (Config.MAX_POSITION_PERCENT / 100.0)
            
            # Controlla Take Profit Parziale (prima dei segnali normali)
            if Config.ENABLE_PARTIAL_TAKE_PROFIT and self.position_manager.can_sell(symbol):
                # Ottieni prezzo ETH corrente per calcolo PnL (DEX)
                current_eth_price = None
                if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
                    if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                        current_eth_price = current_price
                    else:
                        current_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or 3000.0
                
                pnl_result = self.position_manager.get_pnl(symbol, current_price, include_fees=False, current_eth_price=current_eth_price)
                if pnl_result:
                    pnl_percent, pnl_usd = pnl_result
                    if pnl_percent >= Config.TAKE_PROFIT_PERCENT:
                        # TP raggiunto! Vendi parzialmente
                        self.handle_partial_sell(symbol, current_price, z_score=z_score, confidence=confidence)
                        # Dopo vendita parziale, non eseguire altri segnali in questo ciclo
                        return
            
            # Esegui azione se necessario (usa MIN_CONFIDENCE configurabile)
            if signal == 'BUY' and confidence >= Config.MIN_CONFIDENCE:
                # CRITICAL FIX: Passa balance_usdt a can_buy per verificare la liquidità disponibile
                current_balance = balance if balance is not None else 0.0
                can_buy = self.position_manager.can_buy(
                    symbol, 
                    max_position_value_usd=max_position_value, 
                    current_price=current_price,
                    balance_usdt=current_balance,
                    min_buy_amount=10.0
                )
                if can_buy:
                    self.handle_buy(symbol, current_price, z_score=z_score, confidence=confidence, 
                                  total_capital=total_capital, max_position_value=max_position_value)
            elif signal == 'SELL' and confidence >= Config.MIN_CONFIDENCE and self.position_manager.can_sell(symbol):
                self.handle_sell(symbol, current_price, z_score=z_score, confidence=confidence)
        else:
            # Modalità DEX - semplificata
            current_price = self.api.get_current_price()
            if current_price:
                self.last_prices[symbol] = current_price
                print(f"   {symbol}: ${current_price:.2f}")
    
    def handle_buy(self, symbol: str, price: float, z_score: float = 0.0, confidence: float = 0.0,
                 total_capital: float = None, max_position_value: float = None):
        """
        Gestisce ordine di acquisto per una coppia.
        
        Args:
            total_capital: Capitale totale del portafoglio (per modalità accumulo)
            max_position_value: Valore massimo posizione in USD (per modalità accumulo)
        """
        print(f"\n   [{symbol}] 🟢 BUY SIGNAL @ ${price:.2f}")
        
        balance = self.api.get_account_balance(Config.QUOTE_ASSET) if (self.mode == 'CEX' and hasattr(self.api, 'get_account_balance')) else (self.api.get_balance() if hasattr(self.api, 'get_balance') else 1.0)
        balance = balance if balance is not None else 0.0  # Fix: gestisci None da API
        
        # CRITICAL FIX: Applica CAPITAL_LIMIT anche al balance per gli acquisti
        effective_balance = (balance)
        
        # Inizializza quantity (verrà calcolata in base alla modalità)
        quantity = 0.0
        
        # Calcola quantità da comprare in modalità accumulo
        if Config.USE_POSITION_ACCUMULATION and total_capital and max_position_value:
            # Calcola valore posizione attuale
            current_qty = self.position_manager.get_quantity(symbol)  # Usa metodo helper
            current_position_value = current_qty * price if current_qty > 0 else 0.0
            
            # Calcola quanto spazio rimane fino al cap
            remaining_cap = max_position_value - current_position_value
            
            if remaining_cap <= 0:
                print(f"      ⚠️  Cap raggiunto: posizione attuale ${current_position_value:.2f} >= cap ${max_position_value:.2f}")
                return
            
            # Calcola quanto comprare (incremento)
            if Config.ACCUMULATION_AMOUNT_USD > 0:
                # Usa valore fisso in USDT
                buy_amount_usd = min(Config.ACCUMULATION_AMOUNT_USD, remaining_cap, effective_balance * 0.95)
            else:
                # Usa % del capitale - ORA usa effective_balance invece di balance
                buy_amount_usd = min(total_capital * (Config.ACCUMULATION_PERCENT / 100.0), remaining_cap, effective_balance * 0.95)
            
            # Verifica che l'importo sia >= minimo Binance ($10)
            if buy_amount_usd < 10.0:
                print(f"      ⚠️  Cap quasi raggiunto: posizione ${current_position_value:.2f}/{max_position_value:.2f}")
                print(f"      💡 Spazio rimanente (${remaining_cap:.2f}) troppo basso per comprare (minimo $10)")
                return
            
            # Converti in quantità
            quantity = buy_amount_usd / price if price > 0 else 0.0
            
            print(f"      📊 Modalità Accumulo: Cap ${max_position_value:.2f} | Attuale ${current_position_value:.2f} | Acquisto ${buy_amount_usd:.2f}")
        else:
            print(f"      ⚠️  USE_POSITION_ACCUMULATION non configurato. Impossibile procedere con l'acquisto.")
            return
        
        # Calcola fee
        if self.mode == 'CEX':
            # Per CEX, calcola valore trade in USDT
            trade_value_usd = quantity * price
            
            # Verifica balance sufficiente
            if balance < trade_value_usd:
                print(f"      ⚠️  Balance insufficiente: {balance:.2f} {Config.QUOTE_ASSET} < {trade_value_usd:.2f} {Config.QUOTE_ASSET}")
                return
            
            # Verifica minimo notional (~$10 per Binance)
            if trade_value_usd < 10.0:
                print(f"      ⚠️  Valore ordine ${trade_value_usd:.2f} troppo basso. Minimo raccomandato: $10")
                print(f"      💡 Suggerimento: Aumenta ACCUMULATION_PERCENT o ACCUMULATION_AMOUNT_USD")
                # Usa quantità minima in base asset invece
                trade_value_usd = None  # Forzerà l'uso di quantity
                fee_usd = 0.0  # Fee verrà calcolata dopo l'ordine
            else:
                fee_usd = trade_value_usd * (Config.TRADING_FEE_PERCENT / 100.0)
            fee_info = {'fee_usd': fee_usd, 'fee_type': 'trading_fee'}
        else:
            # Fee DEX: gas fee in ETH - DEVE usare prezzo ETH, non prezzo token!
            # Ottieni prezzo ETH
            eth_price = None
            if hasattr(self.api, 'get_current_price'):
                # Se è ETHUSDT, price è già il prezzo ETH
                if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                    eth_price = price
                else:
                    # Per altri token, ottieni prezzo ETH separatamente
                    eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT')
                    if not eth_price:
                        # Fallback: usa price se è ETH, altrimenti stima
                        eth_price = 3000.0
            else:
                eth_price = 3000.0  # Default
            
            # Fee DEX: gas fee in ETH
            if hasattr(self.api, 'get_gas_price'):
                gas_price_gwei = self.api.get_gas_price()
                if gas_price_gwei:
                    # Stima gas per swap (~150k gas units)
                    gas_estimate = 150000
                    gas_cost_eth = (gas_price_gwei * gas_estimate) / 1e9
                    fee_usd = gas_cost_eth * eth_price  # Usa eth_price, non price!
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': gas_cost_eth, 'fee_type': 'gas_fee'}
                else:
                    # Fallback a stima configurata
                    fee_eth = Config.GAS_FEE_ESTIMATE
                    fee_usd = fee_eth * eth_price  # Usa eth_price, non price!
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
            else:
                # Fallback a stima configurata
                fee_eth = Config.GAS_FEE_ESTIMATE
                fee_usd = fee_eth * eth_price  # Usa eth_price, non price!
                fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
        
        if self.mode == 'CEX':
            # Per CEX, calcola valore trade
            trade_value_usd = quantity * price if quantity and price else None
            
            # Usa quoteOrderQty solo se valore >= $10, altrimenti usa quantity
            if trade_value_usd and trade_value_usd >= 10.0:
                order = self.api.place_market_order('BUY', symbol=symbol, quote_quantity_usdt=trade_value_usd)
                # Calcola fee se non già calcolata
                if fee_usd == 0:
                    fee_usd = trade_value_usd * (Config.TRADING_FEE_PERCENT / 100.0)
            else:
                # Usa quantity in base asset (Binance gestirà meglio)
                order = self.api.place_market_order('BUY', symbol=symbol, quantity=quantity)
                # Calcola fee basata sul valore stimato
                if order and fee_usd == 0:
                    # Stima fee dal valore eseguito
                    executed_qty = float(order.get('executedQty', quantity))
                    executed_value = executed_qty * price
                    fee_usd = executed_value * (Config.TRADING_FEE_PERCENT / 100.0)
            
            if order:
                # Ottieni quantità eseguita dall'ordine
                executed_qty = float(order.get('executedQty', quantity))
                position_value_usd = executed_qty * price
                
                # Determina base asset dal simbolo
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                
                # Formatta quantità in modo leggibile
                if executed_qty >= 1:
                    qty_str = f"{executed_qty:.4f}"
                elif executed_qty >= 0.1:
                    qty_str = f"{executed_qty:.5f}"
                else:
                    qty_str = f"{executed_qty:.6f}"
                
                # Usa accumulate=True se in modalità accumulo
                accumulate = Config.USE_POSITION_ACCUMULATION
                self.position_manager.set_position(symbol, 'LONG', price, quantity=executed_qty, fee=fee_usd, accumulate=accumulate)
                
                # CRITICAL FIX: Salva stato SUBITO dopo ogni acquisto!
                self.position_manager.save_state()
                
                # Calcola valore posizione totale dopo accumulo
                total_qty = self.position_manager.get_quantity(symbol)  # Usa metodo helper
                total_position_value = total_qty * price
                
                print(f"      ✅ Ordine eseguito: {order.get('orderId', 'N/A')}")
                if accumulate:
                    print(f"      📊 Quantità acquistata: {qty_str} {base_asset} @ ${price:.2f}")
                    print(f"      📊 Quantità totale posizione: {total_qty:.6f} {base_asset}")
                    print(f"      💰 Valore Posizione Totale: {total_position_value:.2f} {Config.QUOTE_ASSET}")
                else:
                    print(f"      📊 Quantità: {qty_str} {base_asset} @ ${price:.2f}")
                    print(f"      💰 Valore Posizione: {position_value_usd:.2f} {Config.QUOTE_ASSET}")
                if fee_usd > 0:
                    print(f"      💸 Fee: ${fee_usd:.2f} ({Config.TRADING_FEE_PERCENT}%)")
                balance_after = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else balance
                self.reporter.log_trade(symbol, 'BUY', price, executed_qty, balance_after, 
                                      fee_usd=fee_usd, z_score=z_score, confidence=confidence)
            else:
                print(f"      ❌ Errore nell'esecuzione ordine")
        else:
            # DEX mode
            order = self.api.place_swap_order('BUY', quantity)
            if order:
                # Ottieni eth_price per entry_eth_price
                entry_eth_price = eth_price if 'eth_price' in locals() else (price if 'ETH' in symbol.upper() else 3000.0)
                position_value_usd = quantity * price
                
                # Determina base asset dal simbolo
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                
                # Formatta quantità in modo leggibile
                if quantity >= 1:
                    qty_str = f"{quantity:.4f}"
                elif quantity >= 0.1:
                    qty_str = f"{quantity:.5f}"
                else:
                    qty_str = f"{quantity:.6f}"
                
                # Usa accumulate=True se in modalità accumulo
                accumulate = Config.USE_POSITION_ACCUMULATION
                self.position_manager.set_position(symbol, 'LONG', price, quantity=quantity, fee=fee_usd, entry_eth_price=entry_eth_price, accumulate=accumulate)
                
                # CRITICAL FIX: Salva stato SUBITO dopo ogni acquisto!
                self.position_manager.save_state()
                
                # Calcola valore posizione totale dopo accumulo
                total_qty = self.position_manager.get_quantity(symbol)  # Usa metodo helper
                total_position_value = total_qty * price
                
                print(f"      ✅ Ordine simulato: {order.get('orderId', 'N/A')}")
                if accumulate:
                    print(f"      📊 Quantità acquistata: {qty_str} {base_asset} @ ${price:.2f}")
                    print(f"      📊 Quantità totale posizione: {total_qty:.6f} {base_asset}")
                    print(f"      💰 Valore Posizione Totale: {total_position_value:.2f} {Config.QUOTE_ASSET}")
                else:
                    print(f"      📊 Quantità: {qty_str} {base_asset} @ ${price:.2f}")
                    print(f"      💰 Valore Posizione: {position_value_usd:.2f} {Config.QUOTE_ASSET}")
                if fee_info.get('fee_eth'):
                    print(f"      💸 Fee: ${fee_usd:.2f} ({fee_info['fee_eth']:.6f} ETH)")
                else:
                    print(f"      💸 Fee: ${fee_usd:.2f}")
                balance_after = self.api.get_balance() if hasattr(self.api, 'get_balance') else balance - quantity
                self.reporter.log_trade(symbol, 'BUY', price, quantity, balance_after, 
                                      fee_usd=fee_usd, z_score=z_score, confidence=confidence)
    
    def handle_partial_sell(self, symbol: str, price: float, z_score: float = 0.0, confidence: float = 0.0):
        """
        Gestisce vendita parziale per Take Profit.
        Vende una percentuale della posizione quando il TP viene raggiunto.
        """
        entry_price = self.position_manager.entry_prices.get(symbol)
        entry_quantity_before_reduction = self.position_manager.get_quantity(symbol)  # SALVA quantità PRIMA della riduzione!
        entry_eth_price = self.position_manager.entry_eth_prices.get(symbol)
        total_entry_fees_before_reduction = self.position_manager.entry_fees.get(symbol, 0.0)  # Fee PRIMA della riduzione!
        
        # Calcola PnL prima della vendita
        current_eth_price = None
        if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
            if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                current_eth_price = price
            else:
                current_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or 3000.0
        
        pnl_result = self.position_manager.get_pnl(symbol, price, include_fees=False, current_eth_price=current_eth_price) if entry_price else None
        
        print(f"\n   [{symbol}] 🎯 TAKE PROFIT PARZIALE @ ${price:.2f}")
        if pnl_result:
            pnl_percent, pnl_usd = pnl_result
            print(f"      📈 PnL: {pnl_percent:+.2f}% (${pnl_usd:+.2f}) - Vendita {Config.PARTIAL_SELL_PERCENT}%")
        
        # Calcola quantità da vendere usando reduce_position
        # IMPORTANTE: questo modifica entry_quantities e entry_fees interni!
        sell_qty = self.position_manager.reduce_position(symbol, Config.PARTIAL_SELL_PERCENT)
        
        if sell_qty <= 0:
            print(f"      ⚠️  Nessuna quantità da vendere")
            return
        
        balance = self.api.get_account_balance(Config.QUOTE_ASSET) if (self.mode == 'CEX' and hasattr(self.api, 'get_account_balance')) else (self.api.get_balance() if hasattr(self.api, 'get_balance') else 1.0)
        
        # Calcola fee
        if self.mode == 'CEX':
            trade_value_usd = sell_qty * price
            fee_usd = trade_value_usd * (Config.TRADING_FEE_PERCENT / 100.0)
            fee_info = {'fee_usd': fee_usd, 'fee_type': 'trading_fee'}
        else:
            # Fee DEX: gas fee in ETH
            eth_price = current_eth_price if current_eth_price else (price if 'ETH' in symbol.upper() else 3000.0)
            if hasattr(self.api, 'get_gas_price'):
                gas_price_gwei = self.api.get_gas_price()
                if gas_price_gwei:
                    gas_estimate = 150000
                    gas_cost_eth = (gas_price_gwei * gas_estimate) / 1e9
                    fee_usd = gas_cost_eth * eth_price
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': gas_cost_eth, 'fee_type': 'gas_fee'}
                else:
                    fee_eth = Config.GAS_FEE_ESTIMATE
                    fee_usd = fee_eth * eth_price
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
            else:
                fee_eth = Config.GAS_FEE_ESTIMATE
                fee_usd = fee_eth * eth_price
                fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
        
        # Calcola valore investito per la parte venduta (INCLUSO fee di apertura proporzionali)
        # USA I VALORI SALVATI PRIMA DELLA RIDUZIONE!
        entry_value_usd = None
        entry_fees_proportional = 0.0
        
        if entry_price and entry_quantity_before_reduction > 0:
            # Calcola valore base dell'investimento (usa quantità PRIMA della riduzione)
            if entry_eth_price:
                # entry_value_base = sell_qty * entry_eth_price (semplificato)
                entry_value_base = sell_qty * entry_eth_price
            else:
                # entry_value_base = sell_qty * entry_price (semplificato e CORRETTO!)
                entry_value_base = sell_qty * entry_price
            
            # Calcola fee di apertura proporzionali (usa quantità e fee PRIMA della riduzione)
            entry_fees_proportional = total_entry_fees_before_reduction * (sell_qty / entry_quantity_before_reduction)
            
            # Valore investito totale = valore base + fee pagate all'apertura proporzionali
            entry_value_usd = entry_value_base + entry_fees_proportional
        
        if self.mode == 'CEX':
            # Esegui ordine di vendita parziale
            order = self.api.place_market_order('SELL', quantity=sell_qty, symbol=symbol)
            if order:
                executed_qty = float(order.get('executedQty', sell_qty))
                sell_value_usd = executed_qty * price
                
                # Calcola PnL per la parte venduta
                # PnL = Ricavo - (Costo d'acquisto + Fee apertura proporzionali) - Fee vendita
                if entry_value_usd:
                    partial_pnl_usd = sell_value_usd - entry_value_usd - fee_usd
                    # PnL % calcolato su valore base (senza fee), per coerenza
                    entry_value_base = entry_value_usd - entry_fees_proportional
                    partial_pnl_percent = (partial_pnl_usd / entry_value_base) * 100 if entry_value_base > 0 else 0.0
                else:
                    partial_pnl_usd = pnl_usd * (Config.PARTIAL_SELL_PERCENT / 100.0) if pnl_result else 0.0
                    partial_pnl_percent = pnl_percent if pnl_result else 0.0
                
                # Determina base asset
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                
                # Formatta quantità
                if executed_qty >= 1:
                    qty_str = f"{executed_qty:.4f}"
                elif executed_qty >= 0.1:
                    qty_str = f"{executed_qty:.5f}"
                else:
                    qty_str = f"{executed_qty:.6f}"
                
                remaining_qty = self.position_manager.get_quantity(symbol)  # Usa metodo helper
                
                print(f"      ✅ Vendita parziale eseguita: {order.get('orderId', 'N/A')}")
                print(f"      📊 Quantità venduta: {qty_str} {base_asset} @ ${price:.2f}")
                print(f"      📊 Quantità rimanente: {remaining_qty:.6f} {base_asset}")
                print(f"      💰 Valore venduto: {sell_value_usd:.2f} {Config.QUOTE_ASSET}")
                print(f"      📈 PnL parziale: {partial_pnl_percent:+.2f}% (${partial_pnl_usd:+.2f})")
                if fee_usd > 0:
                    print(f"      💸 Fee: ${fee_usd:.2f} ({Config.TRADING_FEE_PERCENT}%)")
                
                balance_after = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else balance
                self.reporter.log_trade(symbol, 'SELL', price, executed_qty, balance_after,
                                      pnl_percent=partial_pnl_percent, fee_usd=fee_usd, pnl_usd=partial_pnl_usd,
                                      entry_value_usd=entry_value_usd, z_score=z_score, confidence=confidence)
            else:
                print(f"      ❌ Errore nell'esecuzione ordine")
        else:
            # DEX mode
            order = self.api.place_swap_order('SELL', sell_qty)
            if order:
                sell_value_usd = sell_qty * price
                
                # Calcola PnL per la parte venduta
                # PnL = Ricavo - (Costo d'acquisto + Fee apertura proporzionali) - Fee vendita
                if entry_value_usd:
                    partial_pnl_usd = sell_value_usd - entry_value_usd - fee_usd
                    # PnL % calcolato su valore base (senza fee)
                    entry_value_base = entry_value_usd - entry_fees_proportional
                    partial_pnl_percent = (partial_pnl_usd / entry_value_base) * 100 if entry_value_base > 0 else 0.0
                else:
                    partial_pnl_usd = pnl_usd * (Config.PARTIAL_SELL_PERCENT / 100.0) if pnl_result else 0.0
                    partial_pnl_percent = pnl_percent if pnl_result else 0.0
                
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                
                if sell_qty >= 1:
                    qty_str = f"{sell_qty:.4f}"
                elif sell_qty >= 0.1:
                    qty_str = f"{sell_qty:.5f}"
                else:
                    qty_str = f"{sell_qty:.6f}"
                
                remaining_qty = self.position_manager.get_quantity(symbol)  # Usa metodo helper
                
                print(f"      ✅ Vendita parziale simulata")
                print(f"      📊 Quantità venduta: {qty_str} {base_asset} @ ${price:.2f}")
                print(f"      📊 Quantità rimanente: {remaining_qty:.6f} {base_asset}")
                print(f"      💰 Valore venduto: {sell_value_usd:.2f} {Config.QUOTE_ASSET}")
                print(f"      📈 PnL parziale: {partial_pnl_percent:+.2f}% (${partial_pnl_usd:+.2f})")
                if fee_info.get('fee_eth'):
                    print(f"      💸 Fee: ${fee_usd:.2f} ({fee_info['fee_eth']:.6f} ETH)")
                else:
                    print(f"      💸 Fee: ${fee_usd:.2f}")
                
                balance_after = self.api.get_balance() if hasattr(self.api, 'get_balance') else balance + sell_qty
                self.reporter.log_trade(symbol, 'SELL', price, sell_qty, balance_after,
                                      pnl_percent=partial_pnl_percent, fee_usd=fee_usd, pnl_usd=partial_pnl_usd,
                                      entry_value_usd=entry_value_usd, z_score=z_score, confidence=confidence)
            else:
                print(f"      ❌ Errore nell'esecuzione ordine")
    
    def handle_sell(self, symbol: str, price: float, z_score: float = 0.0, confidence: float = 0.0):
        """
        Gestisce ordine di vendita per una coppia.
        
        NOTA: Il bot usa quantità fissa e chiude la posizione LONG quando vende.
        Non fa SHORT (vendita allo scoperto), solo compra e vende (LONG-only).
        """
        # CRITICAL FIX: Ottieni quantità REALE dall'API per evitare errori "insufficient balance"
        real_quantity = None
        if self.mode == 'CEX' and hasattr(self.api, 'get_portfolio_value_from_api'):
            portfolio_data = self.api.get_portfolio_value_from_api()
            if portfolio_data:
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                if base_asset in portfolio_data['crypto_values']:
                    real_quantity = portfolio_data['crypto_values'][base_asset]['quantity']
        
        # Usa quantità reale se disponibile, altrimenti fallback a position_manager
        fallback_quantity = self.position_manager.get_quantity(symbol)
        quantity_to_sell = real_quantity if real_quantity and real_quantity > 0 else fallback_quantity
        
        entry_price = self.position_manager.entry_prices.get(symbol)
        entry_quantity = self.position_manager.get_quantity(symbol)  # Usa metodo helper per calcoli PnL
        entry_eth_price = self.position_manager.entry_eth_prices.get(symbol)
        
        # Calcola valore investito (entry_value_usd) per calcolo PnL % totale
        # INCLUSO le fee di apertura sostenute
        entry_value_usd = None
        if entry_price and entry_quantity > 0:
            if entry_eth_price:
                # Modalità DEX: quantity è in ETH, entry_eth_price è prezzo ETH all'entry
                entry_value_base = entry_quantity * entry_eth_price
            else:
                # Modalità CEX: quantity è in token amount
                entry_value_base = entry_price * entry_quantity
            
            # Aggiungi le fee di apertura sostenute per questa posizione
            entry_fees = self.position_manager.entry_fees.get(symbol, 0.0)
            entry_value_usd = entry_value_base + entry_fees
        
        # Ottieni prezzo ETH corrente per calcolo PnL
        current_eth_price = None
        if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
            if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                current_eth_price = price
            else:
                current_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or 3000.0
        
        pnl_result = self.position_manager.get_pnl(symbol, price, include_fees=False, current_eth_price=current_eth_price) if entry_price else None
        
        print(f"\n   [{symbol}] 🔴 SELL SIGNAL @ ${price:.2f}")
        if pnl_result:
            pnl_percent, pnl_usd = pnl_result
            pnl_emoji = "📈" if pnl_usd > 0 else "📉"
            print(f"      {pnl_emoji} PnL: {pnl_percent:+.2f}% (${pnl_usd:+.2f})")
        
        balance = self.api.get_balance() if hasattr(self.api, 'get_balance') else 1.0
        
        # Calcola fee
        if self.mode == 'CEX':
            trade_value_usd = quantity_to_sell * price
            fee_usd = trade_value_usd * (Config.TRADING_FEE_PERCENT / 100.0)
            fee_info = {'fee_usd': fee_usd, 'fee_type': 'trading_fee'}
        else:
            # Fee DEX: gas fee in ETH - DEVE usare prezzo ETH, non prezzo token!
            # Ottieni prezzo ETH
            eth_price = None
            if hasattr(self.api, 'get_current_price'):
                # Se è ETHUSDT, price è già il prezzo ETH
                if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                    eth_price = price
                else:
                    # Per altri token, ottieni prezzo ETH separatamente
                    eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT')
                    if not eth_price:
                        # Fallback: usa price se è ETH, altrimenti stima
                        eth_price = 3000.0
            else:
                eth_price = 3000.0  # Default
            
            # Fee DEX: gas fee in ETH
            if hasattr(self.api, 'get_gas_price'):
                gas_price_gwei = self.api.get_gas_price()
                if gas_price_gwei:
                    gas_estimate = 150000
                    gas_cost_eth = (gas_price_gwei * gas_estimate) / 1e9
                    fee_usd = gas_cost_eth * eth_price  # Usa eth_price, non price!
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': gas_cost_eth, 'fee_type': 'gas_fee'}
                else:
                    fee_eth = Config.GAS_FEE_ESTIMATE
                    fee_usd = fee_eth * eth_price  # Usa eth_price, non price!
                    fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
            else:
                fee_eth = Config.GAS_FEE_ESTIMATE
                fee_usd = fee_eth * eth_price  # Usa eth_price, non price!
                fee_info = {'fee_usd': fee_usd, 'fee_eth': fee_eth, 'fee_type': 'gas_fee_estimated'}
        
        if self.mode == 'CEX':
            # Per CEX, usa quantità REALE dall'API (es. BTC) per SELL
            print(f"      🔄 Vendita di {quantity_to_sell:.8f} {symbol.replace(Config.QUOTE_ASSET, '')}...")
            try:
                order = self.api.place_market_order('SELL', quantity=quantity_to_sell, symbol=symbol)
                if order:
                    # Ottieni quantità eseguita dall'ordine
                    executed_qty = float(order.get('executedQty', quantity_to_sell))
                    
                    # CRITICAL FIX: Calcola entry_value proporzionale alla quantità VENDUTA, non alla quantità totale!
                    # Se vendi solo parte della posizione, il costo di riferimento deve essere proporzionale
                    if entry_price and entry_quantity and entry_quantity > 0:
                        # Entry value proporzionale alla quantità venduta
                        entry_value_for_sold_qty = entry_price * executed_qty
                        # Fee proporzionali
                        entry_fees_total = self.position_manager.entry_fees.get(symbol, 0.0)
                        entry_fees_proportional = (executed_qty / entry_quantity) * entry_fees_total
                        # Costo totale = valore base + fee pagate per quella porzione
                        proportional_entry_value_usd = entry_value_for_sold_qty + entry_fees_proportional
                    else:
                        proportional_entry_value_usd = 0.0
                        entry_fees_proportional = 0.0
                    
                    # IMPORTANTE: Calcola PnL finale PRIMA di chiudere la posizione!
                    sell_value_usd = executed_qty * price
                    
                    # PnL = Ricavo - Costo proporzionale - Fee vendita
                    final_pnl_usd = sell_value_usd - proportional_entry_value_usd - fee_usd if proportional_entry_value_usd else None
                    # PnL % calcolato sul costo base (entry value senza fee di vendita)
                    final_pnl_percent = (final_pnl_usd / proportional_entry_value_usd) * 100 if proportional_entry_value_usd and proportional_entry_value_usd > 0 and final_pnl_usd is not None else None
                    
                    # Ora chiudi la posizione
                    self.position_manager.total_fees_paid[symbol] += fee_usd
                    self.position_manager.set_position(symbol, None, None)
                    
                    print(f"      ✅ Ordine eseguito: {order.get('orderId', 'N/A')}")
                    print(f"      📊 Quantità: {executed_qty:.6f} @ ${price:.2f}")
                    if fee_usd > 0:
                        print(f"      💸 Fee: ${fee_usd:.2f} ({Config.TRADING_FEE_PERCENT}%)")
                    
                    balance_after = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else balance
                    self.reporter.log_trade(symbol, 'SELL', price, executed_qty, balance_after, 
                                          pnl_percent=final_pnl_percent, fee_usd=fee_usd, pnl_usd=final_pnl_usd,
                                          entry_value_usd=proportional_entry_value_usd, z_score=z_score, confidence=confidence)
                    # Salva stato dopo vendita riuscita
                    self.position_manager.save_state()
                else:
                    print(f"      ❌ Errore nell'esecuzione ordine SELL")
                    print(f"      ⚠️  POSIZIONE NON CHIUSA - crypto rimane sul wallet!")
                    # NON chiudiamo la posizione se la vendita fallisce!
            except Exception as e:
                print(f"      ❌ ECCEZIONE durante vendita {symbol}: {e}")
                print(f"      ⚠️  POSIZIONE NON CHIUSA - controllare wallet manualmente!")
                import traceback
                traceback.print_exc()
                # NON chiudiamo la posizione in caso di eccezione!
        else:
            # DEX mode - usa quantity_to_sell anche qui
            order = self.api.place_swap_order('SELL', quantity_to_sell)
            if order:
                # CRITICAL FIX: Calcola entry_value proporzionale alla quantità VENDUTA, non alla quantità totale!
                if entry_price and entry_quantity and entry_quantity > 0:
                    # Entry value proporzionale alla quantità venduta
                    entry_value_for_sold_qty = entry_price * quantity_to_sell
                    # Fee proporzionali
                    entry_fees_total = self.position_manager.entry_fees.get(symbol, 0.0)
                    entry_fees_proportional = (quantity_to_sell / entry_quantity) * entry_fees_total
                    # Costo totale = valore base + fee pagate per quella porzione
                    proportional_entry_value_usd = entry_value_for_sold_qty + entry_fees_proportional
                else:
                    proportional_entry_value_usd = 0.0
                    entry_fees_proportional = 0.0
                
                # IMPORTANTE: Calcola PnL finale PRIMA di chiudere la posizione!
                sell_value_usd = quantity_to_sell * price
                
                # PnL = Ricavo - Costo proporzionale - Fee vendita
                final_pnl_usd = sell_value_usd - proportional_entry_value_usd - fee_usd if proportional_entry_value_usd else None
                # PnL % calcolato sul costo base (entry value senza fee di vendita)
                final_pnl_percent = (final_pnl_usd / proportional_entry_value_usd) * 100 if proportional_entry_value_usd and proportional_entry_value_usd > 0 and final_pnl_usd is not None else None
                
                # Ora chiudi la posizione
                self.position_manager.total_fees_paid[symbol] += fee_usd
                self.position_manager.set_position(symbol, None, None)
                
                if fee_info.get('fee_eth'):
                    print(f"      ✅ Ordine simulato | Fee: ${fee_usd:.2f} ({fee_info['fee_eth']:.6f} ETH)")
                else:
                    print(f"      ✅ Ordine simulato | Fee: ${fee_usd:.2f}")
                
                balance_after = self.api.get_balance() if hasattr(self.api, 'get_balance') else balance + quantity_to_sell
                self.reporter.log_trade(symbol, 'SELL', price, quantity_to_sell, balance_after, 
                                      pnl_percent=final_pnl_percent, fee_usd=fee_usd, pnl_usd=final_pnl_usd,
                                      entry_value_usd=proportional_entry_value_usd, z_score=z_score, confidence=confidence)
    
    def log_status(self, symbol: str, df, signal, confidence, price):
        """Log stato corrente con metriche on-chain per una coppia."""
        last = df.iloc[-1]
        position = self.position_manager.get_position(symbol)
        
        # Ottieni prezzo ETH corrente per calcolo PnL (solo DEX)
        current_eth_price = None
        if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
            if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                current_eth_price = price
            else:
                current_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or None
        
        pnl_result = self.position_manager.get_pnl(symbol, price, current_eth_price=current_eth_price)
        
        # Base log con quantità e tipo posizione
        log_line = f"   [{symbol}] ${price:.2f} | "
        log_line += f"Z: {last['z_score']:.2f} | "
        log_line += f"{signal} ({confidence:.0%}) | "
        
        # Mostra posizione con quantità e tipo
        if position == 'LONG':
            quantity = self.position_manager.get_quantity(symbol)  # Usa metodo helper
            if quantity > 0:
                # Formatta quantità in modo leggibile
                if quantity >= 1:
                    qty_str = f"{quantity:.4f}"
                elif quantity >= 0.1:
                    qty_str = f"{quantity:.5f}"
                else:
                    qty_str = f"{quantity:.6f}"
                log_line += f"Pos: LONG ({qty_str})"
            else:
                log_line += f"Pos: LONG"
        else:
            log_line += f"Pos: NONE"
        
        if pnl_result:
            pnl_percent, pnl_usd = pnl_result
            pnl_emoji = "📈" if pnl_usd > 0 else "📉"
            log_line += f" | {pnl_emoji} {pnl_percent:+.2f}% (${pnl_usd:+.2f})"
        
        # Metriche on-chain se disponibili (solo per ultima coppia)
        if symbol == Config.SYMBOLS[-1] and pd.notna(last.get('gas_price')):
            log_line += f" | Gas: {last['gas_price']:.1f}Gwei"
        
        print(log_line)
        
        # Aggiorna portfolio nel reporter
        portfolio = {}
        for sym in Config.SYMBOLS:
            pos = self.position_manager.get_position(sym)
            entry = self.position_manager.entry_prices.get(sym)
            current = self.last_prices.get(sym)
            if pos == 'LONG' and entry and current:
                # Ottieni eth_price per questa coppia
                sym_eth_price = None
                if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
                    if 'ETH' in sym.upper() and 'USDT' in sym.upper():
                        sym_eth_price = current
                    else:
                        sym_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or None
                pnl_res = self.position_manager.get_pnl(sym, current, current_eth_price=sym_eth_price)
                if pnl_res:
                    pnl_p, pnl_u = pnl_res
                    portfolio[sym] = {
                        'position': pos,
                        'entry_price': entry,
                        'current_price': current,
                        'pnl_percent': pnl_p,
                        'pnl_usd': pnl_u
                    }
        self.reporter.update_portfolio(portfolio)
    
    def print_positions_summary(self):
        """
        Stampa riepilogo posizioni.
        CRITICAL FIX: Usa quantità REALI dall'API invece di positions_state.json
        """
        # CRITICAL FIX: Ottieni quantità REALI dall'API Binance
        if self.mode == 'CEX' and hasattr(self.api, 'get_portfolio_value_from_api'):
            portfolio_data = self.api.get_portfolio_value_from_api()
            if portfolio_data:
                balance = portfolio_data['usdt_balance']
                total_portfolio_value = portfolio_data['total_value_usdt']
                crypto_values = portfolio_data['crypto_values']
                
                # Trova posizioni con quantità > 0 E valore > $10 (ignora dust)
                active_positions = []
                for symbol in Config.SYMBOLS:
                    base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                    if base_asset in crypto_values and crypto_values[base_asset]['quantity'] > 0:
                        # CRITICAL: Ignora dust (< $10) per evitare confusione nei report
                        if crypto_values[base_asset]['value_usd'] >= 10.0:
                            active_positions.append(symbol)
                
                if active_positions:
                    print(f"\n   📊 Posizioni attive ({len(active_positions)}/{len(Config.SYMBOLS)}) [DATI REALI DA API]:")
                    for symbol in active_positions:
                        base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                        real_quantity = crypto_values[base_asset]['quantity']
                        current_price = crypto_values[base_asset]['price']
                        position_value_usd = crypto_values[base_asset]['value_usd']
                        
                        # Entry price da position_manager (se disponibile)
                        entry_price = self.position_manager.entry_prices.get(symbol)
                        
                        # Verifica discrepanza tra API e position_manager
                        pm_quantity = self.position_manager.get_quantity(symbol)
                        discrepancy = ""
                        if pm_quantity > 0 and abs(real_quantity - pm_quantity) / real_quantity > 0.01:  # >1% diff
                            discrepancy = f" ⚠️ [State: {pm_quantity:.6f}]"
                        
                        # CRITICAL FIX: Calcola PnL usando get_pnl() con quantità reale dall'API
                        # Questo include anche le entry fees nel calcolo!
                        if entry_price and entry_price > 0:
                            # Usa get_pnl() per calcolo accurato che include fees
                            pnl_result = self.position_manager.get_pnl(
                                symbol, 
                                current_price, 
                                include_fees=True,
                                quantity_override=real_quantity  # ← USA QUANTITÀ REALE DALL'API!
                            )
                            if pnl_result:
                                pnl_percent, pnl_usd = pnl_result
                                pnl_emoji = "📈" if pnl_usd > 0 else "📉"
                            else:
                                # Fallback: calcolo semplice senza fees
                                pnl_usd = (current_price - entry_price) * real_quantity
                                pnl_percent = ((current_price - entry_price) / entry_price) * 100
                                pnl_emoji = "📈" if pnl_usd > 0 else "📉"
                        else:
                            # Nessun entry price salvato - posizione non tracciata
                            pnl_usd = 0.0
                            pnl_percent = 0.0
                            pnl_emoji = "❓"
                            entry_price = current_price  # Usa current come fallback per display
                        
                        position_percent = (position_value_usd / total_portfolio_value * 100) if total_portfolio_value > 0 else 0.0
                        
                        # Formatta quantità in modo leggibile
                        if real_quantity >= 1:
                            qty_str = f"{real_quantity:.4f}"
                        elif real_quantity >= 0.1:
                            qty_str = f"{real_quantity:.5f}"
                        else:
                            qty_str = f"{real_quantity:.6f}"
                        
                        print(f"      {symbol}: LONG {qty_str} {base_asset} | "
                              f"Entry ${entry_price:.2f} | Current ${current_price:.2f} | "
                              f"{pnl_emoji} {pnl_percent:+.2f}% (${pnl_usd:+.2f}) | "
                              f"💰 ${position_value_usd:.2f} ({position_percent:.1f}%){discrepancy}")
                return
        
        # Fallback: usa position_manager (vecchio metodo)
        active_positions = [s for s in Config.SYMBOLS if self.position_manager.get_position(s) == 'LONG']
        if active_positions:
            print(f"\n   📊 Posizioni attive ({len(active_positions)}/{len(Config.SYMBOLS)}) [⚠️ DA POSITION_STATE]:")
            # Calcola valore totale portafoglio per %
            if self.mode == 'CEX':
                balance = self.api.get_account_balance(Config.QUOTE_ASSET) if hasattr(self.api, 'get_account_balance') else 0.0
            else:
                eth_price_for_balance = self.last_prices.get('ETHUSDT') or 3000.0
                balance = self.api.get_balance() * eth_price_for_balance if hasattr(self.api, 'get_balance') else 0.0
            
            total_portfolio_value = balance
            for sym in Config.SYMBOLS:
                if self.position_manager.get_position(sym) == 'LONG':
                    qty = self.position_manager.get_quantity(sym)
                    price = self.last_prices.get(sym)
                    if qty > 0 and price:
                        total_portfolio_value += qty * price
            
            for symbol in active_positions:
                entry_price = self.position_manager.entry_prices.get(symbol)
                current_price = self.last_prices.get(symbol)
                if entry_price and current_price:
                    # Ottieni eth_price per calcolo PnL (solo DEX)
                    sym_eth_price = None
                    if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
                        if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                            sym_eth_price = current_price
                        else:
                            sym_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or None
                    
                    pnl_result = self.position_manager.get_pnl(symbol, current_price, current_eth_price=sym_eth_price)
                    if pnl_result:
                        pnl_percent, pnl_usd = pnl_result
                        pnl_emoji = "📈" if pnl_usd > 0 else "📉"
                        
                        # Mostra quantità e tipo posizione
                        quantity = self.position_manager.get_quantity(symbol)
                        position_type = self.position_manager.get_position(symbol)
                        
                        # Calcola valore totale posizione e % del portafoglio
                        position_value_usd = quantity * current_price if quantity > 0 else 0.0
                        position_percent = (position_value_usd / total_portfolio_value * 100) if total_portfolio_value > 0 else 0.0
                        
                        if quantity > 0:
                            # Formatta quantità in modo leggibile
                            if quantity >= 1:
                                qty_str = f"{quantity:.4f}"
                            elif quantity >= 0.1:
                                qty_str = f"{quantity:.5f}"
                            else:
                                qty_str = f"{quantity:.6f}"
                            
                            # Determina base asset dal simbolo
                            base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                            
                            print(f"      {symbol}: {position_type} {qty_str} {base_asset} | "
                                  f"Entry ${entry_price:.2f} | Current ${current_price:.2f} | "
                                  f"{pnl_emoji} {pnl_percent:+.2f}% (${pnl_usd:+.2f}) | "
                                  f"💰 ${position_value_usd:.2f} ({position_percent:.1f}%)")
                        else:
                            print(f"      {symbol}: {position_type} | "
                                  f"Entry ${entry_price:.2f} | Current ${current_price:.2f} | "
                                  f"{pnl_emoji} {pnl_percent:+.2f}% (${pnl_usd:+.2f}) | "
                                  f"💰 ${position_value_usd:.2f} ({position_percent:.1f}%)")
    
    def print_summary(self):
        """Stampa riepilogo finale delle posizioni aperte."""
        print("\n" + "="*60)
        print("📊 STATO POSIZIONI FINALI")
        print("="*60)
        status = self.position_manager.get_status()
        active_positions = []
        
        for symbol, info in status.items():
            position = info['position']
            entry = info['entry_price']
            current = self.last_prices.get(symbol)
            quantity = info.get('quantity', 0.0)
            
            # Mostra solo posizioni aperte
            if position == 'LONG' and quantity > 0 and entry and current:
                # Formatta quantità
                if quantity >= 1:
                    qty_str = f"{quantity:.4f}"
                elif quantity >= 0.1:
                    qty_str = f"{quantity:.5f}"
                else:
                    qty_str = f"{quantity:.6f}"
                base_asset = symbol.replace(Config.QUOTE_ASSET, '').replace('/', '')
                
                # Ottieni eth_price per calcolo PnL (solo DEX)
                sym_eth_price = None
                if self.mode == 'DEX' and hasattr(self.api, 'get_current_price'):
                    if 'ETH' in symbol.upper() and 'USDT' in symbol.upper():
                        sym_eth_price = current
                    else:
                        sym_eth_price = self.api.get_current_price('ETHUSDT') or self.api.get_current_price('ETH/USDT') or None
                pnl_result = self.position_manager.get_pnl(symbol, current, current_eth_price=sym_eth_price)
                
                if pnl_result:
                    pnl_percent, pnl_usd = pnl_result
                    pnl_emoji = "📈" if pnl_usd > 0 else "📉"
                    active_positions.append({
                        'symbol': symbol,
                        'position': position,
                        'qty_str': qty_str,
                        'base_asset': base_asset,
                        'entry': entry,
                        'current': current,
                        'pnl_percent': pnl_percent,
                        'pnl_usd': pnl_usd,
                        'pnl_emoji': pnl_emoji
                    })
        
        if active_positions:
            for pos in active_positions:
                print(f"  {pos['symbol']}: {pos['position']} {pos['qty_str']} {pos['base_asset']} | "
                      f"Entry: ${pos['entry']:.2f} | Current: ${pos['current']:.2f} | "
                      f"{pos['pnl_emoji']} {pos['pnl_percent']:+.2f}% (${pos['pnl_usd']:+.2f})")
        else:
            print("  ⚪ Nessuna posizione aperta")
        print("="*60)

if __name__ == '__main__':
    bot = TradingBot()
    bot.run()

