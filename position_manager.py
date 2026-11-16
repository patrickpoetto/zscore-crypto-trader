"""Gestione posizioni multiple per diverse coppie."""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from config import Config

class PositionManager:
    """Gestisce posizioni per multiple coppie."""

    def __init__(self, symbols, state_file='positions_state.json'):
        self.symbols = symbols
        self.state_file = Path(state_file)
        self.positions: Dict[str, Optional[str]] = {symbol: None for symbol in symbols}
        self.entry_prices: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        self.entry_quantities: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        self.entry_eth_prices: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}  # Prezzo ETH all'entry
        self.entry_fees: Dict[str, float] = {symbol: 0.0 for symbol in symbols}  # Fee pagate all'entry (BUY) per questa posizione
        self.total_fees_paid: Dict[str, float] = {symbol: 0.0 for symbol in symbols}  # Fee totali accumulate (per statistiche)

        # Risk management per-posizione (usato da strategie con TP/SL/time-exit espliciti, es. scalping)
        self.entry_times: Dict[str, Optional[str]] = {symbol: None for symbol in symbols}  # ISO timestamp apertura
        self.stop_loss_prices: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        self.take_profit_prices: Dict[str, Optional[float]] = {symbol: None for symbol in symbols}
        self.max_holding_seconds: Dict[str, Optional[int]] = {symbol: None for symbol in symbols}

        # Carica stato salvato se esiste
        self.load_state()
    
    def get_position(self, symbol: str) -> Optional[str]:
        """Ottiene posizione corrente per una coppia."""
        return self.positions.get(symbol)
    
    def set_position(self, symbol: str, side: Optional[str], entry_price: Optional[float] = None,
                     quantity: Optional[float] = None, fee: float = 0.0, entry_eth_price: Optional[float] = None,
                     accumulate: bool = False, stop_loss_price: Optional[float] = None,
                     take_profit_price: Optional[float] = None, max_holding_seconds: Optional[int] = None):
        """
        Imposta posizione per una coppia.

        Args:
            accumulate: Se True, aggiunge quantity alla quantità esistente invece di sostituirla
            stop_loss_price/take_profit_price/max_holding_seconds: parametri di risk management
                espliciti usati dalle strategie con uscita a soglia fissa (es. scalping).
        """
        if side is None:
            # Chiudere posizione: resetta tutto
            self.positions[symbol] = None
            self.entry_prices[symbol] = None
            self.entry_quantities[symbol] = 0.0
            self.entry_eth_prices[symbol] = None
            self.entry_fees[symbol] = 0.0
            self.entry_times[symbol] = None
            self.stop_loss_prices[symbol] = None
            self.take_profit_prices[symbol] = None
            self.max_holding_seconds[symbol] = None
        else:
            self.positions[symbol] = side
            if not accumulate or not self.entry_times.get(symbol):
                self.entry_times[symbol] = datetime.now().isoformat()
            if stop_loss_price is not None:
                self.stop_loss_prices[symbol] = stop_loss_price
            if take_profit_price is not None:
                self.take_profit_prices[symbol] = take_profit_price
            if max_holding_seconds is not None:
                self.max_holding_seconds[symbol] = max_holding_seconds
            if entry_price:
                if accumulate and self.entry_prices.get(symbol):
                    # Calcola prezzo medio ponderato per accumulo
                    old_qty = self.get_quantity(symbol)  # Usa metodo helper
                    old_price = self.entry_prices.get(symbol)
                    if old_qty > 0 and old_price:
                        total_value = (old_qty * old_price) + (quantity * entry_price) if quantity else (old_qty * old_price)
                        total_qty = old_qty + (quantity if quantity else 0)
                        if total_qty > 0:
                            self.entry_prices[symbol] = total_value / total_qty
                    else:
                        self.entry_prices[symbol] = entry_price
                else:
                    self.entry_prices[symbol] = entry_price
            
            if quantity:
                if accumulate:
                    # Accumula quantità
                    current_qty = self.get_quantity(symbol)  # Usa metodo helper
                    self.entry_quantities[symbol] = current_qty + quantity
                else:
                    # Sostituisce quantità
                    self.entry_quantities[symbol] = quantity
            
            if entry_eth_price:
                if accumulate and self.entry_eth_prices.get(symbol):
                    # Calcola prezzo ETH medio ponderato per accumulo
                    old_qty = self.get_quantity(symbol)  # Usa metodo helper
                    old_eth_price = self.entry_eth_prices.get(symbol)
                    if old_qty > 0 and old_eth_price:
                        total_value = (old_qty * old_eth_price) + (quantity * entry_eth_price) if quantity else (old_qty * old_eth_price)
                        total_qty = old_qty + (quantity if quantity else 0)
                        if total_qty > 0:
                            self.entry_eth_prices[symbol] = total_value / total_qty
                    else:
                        self.entry_eth_prices[symbol] = entry_eth_price
                else:
                    self.entry_eth_prices[symbol] = entry_eth_price
            
            if fee > 0:
                self.total_fees_paid[symbol] += fee
                # Se stiamo aprendo/accumulando una posizione (BUY), accumula anche le fee
                if side == 'LONG':
                    if accumulate:
                        self.entry_fees[symbol] = self.entry_fees.get(symbol, 0.0) + fee
                    else:
                        self.entry_fees[symbol] = fee
    
    def get_quantity(self, symbol: str) -> float:
        """
        Ottiene la quantità per un simbolo, garantendo sempre un valore valido.
        
        Returns:
            float: Quantità >= 0.0, mai None
        """
        qty = self.entry_quantities.get(symbol, 0.0)
        return qty if qty is not None and qty >= 0 else 0.0
    
    def get_entry_price(self, symbol: str) -> float:
        """
        Ottiene l'entry price per un simbolo.
        
        Returns:
            float: Entry price o None se non disponibile
        """
        return self.entry_prices.get(symbol)
    
    def can_buy(self, symbol: str, max_position_value_usd: float = None, current_price: float = None, balance_usdt: float = None, min_buy_amount: float = 10.0) -> bool:
        """
        Verifica se può comprare.
        
        Args:
            max_position_value_usd: Valore massimo della posizione in USD (per cap %)
            current_price: Prezzo corrente per calcolare valore posizione attuale
            balance_usdt: Balance USDT disponibile (CRITICAL: verifica liquidità!)
            min_buy_amount: Importo minimo per acquisto (default $10 per Binance)
        """
        # CRITICAL FIX: Verifica SEMPRE che ci sia abbastanza balance USDT
        if balance_usdt is not None and balance_usdt < min_buy_amount:
            return False  # Non abbastanza liquidità per comprare
        
        if Config.USE_POSITION_ACCUMULATION and max_position_value_usd and current_price:
            # In modalità accumulo, può comprare se non ha raggiunto il cap
            current_qty = self.get_quantity(symbol)  # Usa metodo helper
            if current_qty > 0:
                current_value = current_qty * current_price
                return current_value < max_position_value_usd
            else:
                return True  # Nessuna posizione, può comprare
        else:
            # Modalità quantità fissa: può comprare solo se non ha posizione aperta
            return self.positions.get(symbol) != 'LONG'
    
    def can_sell(self, symbol: str) -> bool:
        """Verifica se può vendere."""
        return self.positions.get(symbol) == 'LONG'
    
    def reduce_position(self, symbol: str, sell_percent: float):
        """
        Riduce la posizione di una percentuale (vendita parziale).
        
        Args:
            symbol: Simbolo della coppia
            sell_percent: Percentuale da vendere (es. 50.0 = 50%)
        
        Returns:
            Quantità venduta (in base asset)
        """
        if self.positions.get(symbol) != 'LONG':
            return 0.0
        
        current_qty = self.get_quantity(symbol)  # Usa metodo helper
        if current_qty <= 0:
            return 0.0
        
        # Calcola quantità da vendere
        sell_qty = current_qty * (sell_percent / 100.0)
        
        # Riduci quantità rimanente
        remaining_qty = current_qty - sell_qty
        
        if remaining_qty <= 0:
            # Se vendiamo tutto, chiudi posizione
            self.set_position(symbol, None, None)
            return current_qty
        else:
            # Aggiorna quantità rimanente
            # Il prezzo di entry rimane lo stesso (prezzo medio ponderato già calcolato)
            self.entry_quantities[symbol] = remaining_qty
            
            # Riduci proporzionalmente anche le fee di entry
            entry_fee = self.entry_fees.get(symbol, 0.0)
            remaining_fee = entry_fee * (remaining_qty / current_qty)
            self.entry_fees[symbol] = remaining_fee
            
            return sell_qty
    
    def get_pnl(self, symbol: str, current_price: float, include_fees: bool = True, 
                current_eth_price: float = None, quantity_override: float = None) -> Optional[Tuple[float, float]]:
        """
        Calcola PnL per una posizione.
        
        Args:
            symbol: Simbolo della coppia
            current_price: Prezzo corrente del token (USD)
            include_fees: Se includere le fee nel calcolo
            current_eth_price: Prezzo ETH corrente in USD (per calcolare valore corrente)
            quantity_override: Se fornito, usa questa quantità invece di quella salvata in positions_state
                               CRITICAL: Usa questo per passare la quantità REALE dall'API!
        
        Returns: (pnl_percent, pnl_usd) o None
        
        Note: quantity è in ETH. Usa entry_eth_price per valore entry e current_eth_price per valore corrente.
        """
        entry_price = self.entry_prices.get(symbol)
        # CRITICAL FIX: Usa quantity dall'API se fornita, altrimenti fallback a positions_state
        quantity = quantity_override if quantity_override is not None else self.get_quantity(symbol)
        entry_eth_price = self.entry_eth_prices.get(symbol)
        
        if entry_price and self.positions.get(symbol) == 'LONG' and quantity > 0:
            # Determina se è ETHUSDT o altro token
            is_eth_pair = 'ETH' in symbol.upper() and ('USDT' in symbol.upper() or 'USD' in symbol.upper())
            
            if entry_eth_price:
                # Modalità DEX: quantity è sempre in ETH, entry_eth_price è il prezzo ETH all'entry
                entry_value_usd = quantity * entry_eth_price
                
                if is_eth_pair:
                    # ETHUSDT: current_price è già il prezzo ETH corrente, usalo direttamente
                    # Non serve current_eth_price perché current_price è già ETH price
                    current_value_usd = quantity * current_price
                else:
                    # Altro token (es. BTCUSDT): calcola quanti token abbiamo comprato
                    # entry_value_usd è in USD, entry_price è prezzo del token all'entry
                    token_amount = entry_value_usd / entry_price
                    # Per altri token, se abbiamo current_eth_price, usalo per convertire il valore
                    # altrimenti usa direttamente current_price
                    if current_eth_price:
                        # Converte il valore dei token in USD usando il prezzo ETH corrente
                        # Ma in realtà, current_price è già in USD, quindi non serve conversione
                        current_value_usd = token_amount * current_price
                    else:
                        current_value_usd = token_amount * current_price
            else:
                # Modalità CEX o fallback: quantity è già in token amount
                entry_value_usd = entry_price * quantity
                current_value_usd = current_price * quantity
            
            # PnL in USD (prima delle fee)
            pnl_usd_before_fees = current_value_usd - entry_value_usd
            
            # Sottrai fee se richiesto
            # Per posizioni aperte, usa solo la fee di entry (BUY), non le fee future (SELL)
            pnl_usd = pnl_usd_before_fees
            if include_fees:
                # Usa entry_fee (fee del BUY) invece di total_fees_paid (che include anche fee di trade precedenti)
                entry_fee = self.entry_fees.get(symbol, 0.0)
                pnl_usd -= entry_fee
            
            # PnL percentuale: calcola basandosi sul valore entry e includendo fee se richiesto
            # Se include_fees=True, il PnL percentuale riflette il profitto reale (dopo fee di entry)
            if include_fees:
                entry_fee = self.entry_fees.get(symbol, 0.0)
                if entry_fee > 0:
                    # PnL percentuale reale = (valore_finale - valore_entry - fee_entry) / valore_entry
                    pnl_percent = ((pnl_usd) / entry_value_usd) * 100
                else:
                    # Se non ci sono fee di entry, calcola solo sul prezzo
                    pnl_percent = ((current_price - entry_price) / entry_price) * 100
            else:
                # PnL percentuale basato solo sul prezzo (senza fee)
                pnl_percent = ((current_price - entry_price) / entry_price) * 100
            
            return (pnl_percent, pnl_usd)
        return None
    
    def get_holding_seconds(self, symbol: str) -> Optional[float]:
        """Secondi trascorsi dall'apertura della posizione (None se non tracciato)."""
        entry_time = self.entry_times.get(symbol)
        if not entry_time:
            return None
        try:
            return (datetime.now() - datetime.fromisoformat(entry_time)).total_seconds()
        except ValueError:
            return None

    def check_exit_conditions(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Verifica se una posizione LONG deve essere chiusa per stop-loss, take-profit o timeout.
        Usato dalle strategie con soglie di uscita esplicite (es. scalping a breve termine).

        Returns:
            'STOP_LOSS' | 'TAKE_PROFIT' | 'TIME_EXIT' | None
        """
        if self.positions.get(symbol) != 'LONG':
            return None

        stop_loss = self.stop_loss_prices.get(symbol)
        if stop_loss is not None and current_price <= stop_loss:
            return 'STOP_LOSS'

        take_profit = self.take_profit_prices.get(symbol)
        if take_profit is not None and current_price >= take_profit:
            return 'TAKE_PROFIT'

        max_holding = self.max_holding_seconds.get(symbol)
        if max_holding is not None:
            held = self.get_holding_seconds(symbol)
            if held is not None and held >= max_holding:
                return 'TIME_EXIT'

        return None

    def get_status(self) -> Dict[str, Dict]:
        """Ottiene stato di tutte le posizioni."""
        status = {}
        for symbol in self.symbols:
            status[symbol] = {
                'position': self.positions.get(symbol),
                'entry_price': self.entry_prices.get(symbol),
                'quantity': self.get_quantity(symbol),  # Usa metodo helper
                'entry_eth_price': self.entry_eth_prices.get(symbol),
                'total_fees': self.total_fees_paid.get(symbol, 0.0)
            }
        return status
    
    def save_state(self):
        """Salva lo stato delle posizioni su file."""
        try:
            state = {
                'positions': self.positions,
                'entry_prices': {k: v for k, v in self.entry_prices.items() if v is not None},
                'entry_quantities': {k: v for k, v in self.entry_quantities.items() if v is not None},
                'entry_eth_prices': {k: v for k, v in self.entry_eth_prices.items() if v is not None},
                'entry_fees': {k: v for k, v in self.entry_fees.items() if v > 0},
                'total_fees_paid': self.total_fees_paid,
                'entry_times': {k: v for k, v in self.entry_times.items() if v is not None},
                'stop_loss_prices': {k: v for k, v in self.stop_loss_prices.items() if v is not None},
                'take_profit_prices': {k: v for k, v in self.take_profit_prices.items() if v is not None},
                'max_holding_seconds': {k: v for k, v in self.max_holding_seconds.items() if v is not None}
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"⚠️  Errore salvataggio stato posizioni: {e}")
    
    def load_state(self):
        """Carica lo stato delle posizioni da file."""
        if not self.state_file.exists():
            return
        
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            
            # Ripristina solo le posizioni per i simboli configurati
            for symbol in self.symbols:
                if symbol in state.get('positions', {}):
                    self.positions[symbol] = state['positions'][symbol]
                if symbol in state.get('entry_prices', {}):
                    self.entry_prices[symbol] = state['entry_prices'][symbol]
                if symbol in state.get('entry_quantities', {}):
                    self.entry_quantities[symbol] = state['entry_quantities'][symbol]
                if symbol in state.get('entry_eth_prices', {}):
                    self.entry_eth_prices[symbol] = state['entry_eth_prices'][symbol]
                if symbol in state.get('entry_fees', {}):
                    self.entry_fees[symbol] = state['entry_fees'][symbol]
                if symbol in state.get('total_fees_paid', {}):
                    self.total_fees_paid[symbol] = state['total_fees_paid'][symbol]
                if symbol in state.get('entry_times', {}):
                    self.entry_times[symbol] = state['entry_times'][symbol]
                if symbol in state.get('stop_loss_prices', {}):
                    self.stop_loss_prices[symbol] = state['stop_loss_prices'][symbol]
                if symbol in state.get('take_profit_prices', {}):
                    self.take_profit_prices[symbol] = state['take_profit_prices'][symbol]
                if symbol in state.get('max_holding_seconds', {}):
                    self.max_holding_seconds[symbol] = state['max_holding_seconds'][symbol]
            
            # Valida e pulisci posizioni corrotte (posizioni senza quantità)
            for symbol in self.symbols:
                if self.positions.get(symbol) == 'LONG':
                    qty = self.entry_quantities.get(symbol)
                    # Se la posizione non ha quantità valida, resettala
                    if qty is None or qty <= 0:
                        print(f"⚠️  Posizione corrotta per {symbol} (quantità mancante), reset...")
                        self.positions[symbol] = None
                        self.entry_prices.pop(symbol, None)
                        self.entry_quantities.pop(symbol, None)
                        self.entry_eth_prices.pop(symbol, None)
                        self.entry_fees.pop(symbol, None)
            
            # Verifica se ci sono posizioni ripristinate
            active = [s for s in self.symbols if self.positions.get(s) == 'LONG']
            if active:
                print(f"✅ Ripristinate {len(active)} posizioni da stato salvato: {', '.join(active)}")
        except Exception as e:
            print(f"⚠️  Errore caricamento stato posizioni: {e}")
    
    def clear_state(self):
        """Rimuove il file di stato (usato per reset)."""
        if self.state_file.exists():
            self.state_file.unlink()

