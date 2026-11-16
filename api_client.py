"""Client API per Binance, Alchemy e DEX."""
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd
import requests
from web3 import Web3
from eth_account import Account
from config import Config

class APIClient:
    """Client per interagire con Binance API (CEX)."""
    
    def __init__(self):
        if Config.TRADING_MODE != 'CEX':
            raise ValueError("APIClient richiede TRADING_MODE=CEX")
        
        if Config.USE_TESTNET:
            self.client = Client(
                Config.BINANCE_API_KEY,
                Config.BINANCE_API_SECRET,
                testnet=True
            )
        else:
            self.client = Client(
                Config.BINANCE_API_KEY,
                Config.BINANCE_API_SECRET
            )
        
        # Cache per info simboli (min quantity, step size, etc.)
        self.symbol_info_cache = {}
        
        # Contatore chiamate API per monitoring
        self.api_calls = {
            'get_klines': 0,
            'get_ticker': 0,
            'get_balance': 0,
            'place_order': 0,
            'get_account': 0,
            'other': 0
        }
    
    def _normalize_symbol(self, symbol):
        """Normalizza simbolo per Binance (rimuove / se presente)."""
        if symbol:
            return symbol.replace('/', '').replace('-', '').upper()
        return None
    
    def _get_symbol_info(self, symbol):
        """Ottiene informazioni simbolo (min quantity, step size, etc.)."""
        normalized = self._normalize_symbol(symbol)
        if normalized in self.symbol_info_cache:
            return self.symbol_info_cache[normalized]
        
        try:
            info = self.client.get_symbol_info(normalized)
            if info:
                filters = {f['filterType']: f for f in info.get('filters', [])}
                symbol_info = {
                    'symbol': normalized,
                    'baseAsset': info.get('baseAsset'),
                    'quoteAsset': info.get('quoteAsset'),
                    'minQty': float(filters.get('LOT_SIZE', {}).get('minQty', 0)),
                    'stepSize': float(filters.get('LOT_SIZE', {}).get('stepSize', 0)),
                    'minNotional': float(filters.get('MIN_NOTIONAL', {}).get('minNotional', 0)),
                }
                self.symbol_info_cache[normalized] = symbol_info
                return symbol_info
        except Exception as e:
            print(f"⚠️  Errore recupero info simbolo {normalized}: {e}")
        
        return None
    
    def get_klines(self, symbol=None, interval=None, limit=100):
        """Ottiene candlestick data."""
        symbol = symbol or Config.SYMBOL
        symbol = self._normalize_symbol(symbol)
        interval = interval or Config.TIMEFRAME
        
        try:
            self.api_calls['get_klines'] += 1
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            df['close'] = df['close'].astype(float)
            df['high'] = df['high'].astype(float)
            df['low'] = df['low'].astype(float)
            df['open'] = df['open'].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['quote_volume'] = df['quote_volume'].astype(float)
            df['trades'] = df['trades'].astype(int)
            df['taker_buy_base'] = df['taker_buy_base'].astype(float)
            # Volume "sell" stimato = volume totale - volume acquistato da taker (proxy order-flow, da klines pubblici)
            df['taker_sell_base'] = df['volume'] - df['taker_buy_base']

            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume',
                       'quote_volume', 'trades', 'taker_buy_base', 'taker_sell_base']]

        except BinanceAPIException as e:
            print(f"❌ Errore API Binance per {symbol}: {e}")
            return None
    
    def get_account_balance(self, asset=None):
        """Ottiene balance dell'account (default: quote asset configurata, es. EUR/USDT)."""
        asset = asset or Config.QUOTE_ASSET
        try:
            self.api_calls['get_balance'] += 1
            balance = self.client.get_asset_balance(asset=asset)
            return float(balance['free']) if balance else 0.0
        except BinanceAPIException as e:
            print(f"Errore recupero balance: {e}")
            return 0.0
    
    def get_portfolio_value_from_api(self, symbols=None):
        """
        Ottiene il valore REALE del portafoglio direttamente dall'API Binance.
        Calcola il valore nella quote asset configurata (Config.QUOTE_ASSET) di TUTTE
        le crypto specificate + il balance della quote asset stessa.

        Args:
            symbols: Lista di simboli trading (es. ['BTCEUR', 'ETHEUR', ...])
                     Se None, usa Config.SYMBOLS

        Returns:
            dict con:
                'total_value_usdt': valore totale nella quote asset (nome storico, vale per qualunque quote)
                'usdt_balance': balance della quote asset (nome storico)
                'crypto_values': dict {asset: {'quantity': float, 'price': float, 'value_usd': float}}
        """
        symbols = symbols or Config.SYMBOLS
        quote_asset = Config.QUOTE_ASSET

        try:
            # Ottieni tutti i balance dall'account
            self.api_calls['get_account'] += 1
            account_info = self.client.get_account()
            balances = {b['asset']: float(b['free']) + float(b['locked'])
                       for b in account_info.get('balances', [])}

            # Estrai gli asset base dalle coppie (rimuove la quote asset)
            crypto_assets = set()
            for symbol in symbols:
                if symbol.endswith(quote_asset):
                    asset = symbol[:-len(quote_asset)]
                    crypto_assets.add(asset)

            # Calcola valore per ogni crypto
            crypto_values = {}
            total_value_quote = 0.0

            # Balance della quote asset (es. EUR o USDT)
            quote_balance = balances.get(quote_asset, 0.0)
            total_value_quote += quote_balance
            crypto_values[quote_asset] = {
                'quantity': quote_balance,
                'price': 1.0,
                'value_usd': quote_balance
            }

            # Altre crypto
            for asset in sorted(crypto_assets):
                quantity = balances.get(asset, 0.0)

                if quantity > 0:
                    try:
                        symbol = f"{asset}{quote_asset}"
                        self.api_calls['get_ticker'] += 1
                        ticker = self.client.get_symbol_ticker(symbol=symbol)
                        price = float(ticker['price'])
                        value_usd = quantity * price

                        crypto_values[asset] = {
                            'quantity': quantity,
                            'price': price,
                            'value_usd': value_usd
                        }
                        total_value_quote += value_usd
                    except Exception as e:
                        # Asset non ha pair con la quote asset configurata, o errore
                        crypto_values[asset] = {
                            'quantity': quantity,
                            'price': 0.0,
                            'value_usd': 0.0
                        }
                else:
                    crypto_values[asset] = {
                        'quantity': 0.0,
                        'price': 0.0,
                        'value_usd': 0.0
                    }

            return {
                'total_value_usdt': total_value_quote,
                'usdt_balance': quote_balance,
                'crypto_values': crypto_values
            }
            
        except Exception as e:
            print(f"❌ Errore nel recupero valore portafoglio da API: {e}")
            return None
    
    def place_market_order(self, side, quantity=None, symbol=None, quote_quantity_usdt=None):
        """
        Esegue ordine market.
        
        Args:
            side: 'BUY' o 'SELL'
            quantity: Quantità in base asset (es. BTC)
            symbol: Simbolo (es. BTCUSDT)
            quote_quantity_usdt: Quantità in USDT (usa questo per ordini precisi)
        """
        symbol = symbol or Config.SYMBOL
        symbol = self._normalize_symbol(symbol)
        
        try:
            symbol_info = self._get_symbol_info(symbol)
            
            if quote_quantity_usdt:
                # Ordine con quantità in USDT (più preciso)
                # Binance richiede: quoteOrderQty con max 2 decimali per USDT
                # E valore minimo notional (solitamente ~$10)
                quote_quantity_usdt = round(quote_quantity_usdt, 2)
                
                # Verifica minimo notional
                min_notional = symbol_info.get('minNotional', 0) if symbol_info else 0
                if min_notional > 0 and quote_quantity_usdt < min_notional:
                    # Se troppo basso, usa quantity invece
                    current_price = self.get_current_price(symbol)
                    if current_price:
                        quantity = quote_quantity_usdt / current_price
                        
                        # Arrotonda quantity secondo stepSize se disponibile
                        if symbol_info and symbol_info.get('stepSize', 0) > 0:
                            step_size = symbol_info['stepSize']
                            quantity = (quantity // step_size) * step_size
                        
                        # Arrotonda a 8 decimali
                        quantity = round(quantity, 8)
                        
                        # Verifica quantità minima
                        if symbol_info and symbol_info.get('minQty', 0) > 0:
                            if quantity < symbol_info['minQty']:
                                print(f"⚠️  Valore ordine ${quote_quantity_usdt:.2f} troppo basso per {symbol}. Min: ${min_notional:.2f}")
                                return None
                        # Usa quantity invece di quoteOrderQty
                        if side == 'BUY':
                            order = self.client.order_market_buy(
                                symbol=symbol,
                                quantity=quantity
                            )
                        else:
                            order = self.client.order_market_sell(
                                symbol=symbol,
                                quantity=quantity
                            )
                    else:
                        print(f"❌ Impossibile ottenere prezzo per {symbol}")
                        return None
                else:
                    # Usa quoteOrderQty se valore sufficiente
                    if side == 'BUY':
                        order = self.client.order_market_buy(
                            symbol=symbol,
                            quoteOrderQty=str(quote_quantity_usdt)  # Binance richiede stringa
                        )
                    else:
                        # Per SELL, dobbiamo usare quantity in base asset
                        current_price = self.get_current_price(symbol)
                        if current_price:
                            quantity = quote_quantity_usdt / current_price
                            
                            # Arrotonda quantity secondo stepSize se disponibile
                            if symbol_info and symbol_info.get('stepSize', 0) > 0:
                                step_size = symbol_info['stepSize']
                                quantity = (quantity // step_size) * step_size
                            
                            # Arrotonda a 8 decimali
                            quantity = round(quantity, 8)
                        else:
                            print(f"❌ Impossibile ottenere prezzo per {symbol}")
                            return None
                        order = self.client.order_market_sell(
                            symbol=symbol,
                            quantity=quantity
                        )
            else:
                # Ordine con quantità in base asset
                if not quantity or quantity <= 0:
                    print(f"❌ Quantità non valida per {symbol}: {quantity}")
                    return None
                
                # Arrotonda quantity secondo stepSize se disponibile
                if symbol_info and symbol_info.get('stepSize', 0) > 0:
                    step_size = symbol_info['stepSize']
                    # Arrotonda per difetto al stepSize più vicino
                    quantity = (quantity // step_size) * step_size
                
                # Verifica quantità minima
                if symbol_info and symbol_info.get('minQty', 0) > 0:
                    if quantity < symbol_info['minQty']:
                        print(f"⚠️  Quantità {quantity} troppo bassa per {symbol}. Min: {symbol_info['minQty']}")
                        return None
                
                # Arrotonda a 8 decimali (precisione massima Binance)
                quantity = round(quantity, 8)
                
                if side == 'BUY':
                    self.api_calls['place_order'] += 1
                    order = self.client.order_market_buy(
                        symbol=symbol,
                        quantity=quantity
                    )
                else:
                    self.api_calls['place_order'] += 1
                    order = self.client.order_market_sell(
                        symbol=symbol,
                        quantity=quantity
                    )
            
            return order
        except BinanceAPIException as e:
            print(f"❌ Errore ordine Binance per {symbol}: {e}")
            return None
    
    def get_current_price(self, symbol=None):
        """Ottiene prezzo corrente."""
        symbol = symbol or Config.SYMBOL
        symbol = self._normalize_symbol(symbol)
        try:
            self.api_calls['get_ticker'] += 1
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except BinanceAPIException as e:
            print(f"❌ Errore prezzo Binance per {symbol}: {e}")
            return None


class DEXClient:
    """Client per trading su DEX con wallet privato."""
    
    # Indirizzi Uniswap V3 Router (mainnet)
    UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
    
    def __init__(self):
        if not Config.ALCHEMY_API_KEY:
            raise ValueError("ALCHEMY_API_KEY richiesta per DEX")
        
        # Setup Web3
        network = "sepolia" if Config.USE_TESTNET else Config.NETWORK
        if network == "mainnet":
            self.rpc_url = f"https://eth-mainnet.g.alchemy.com/v2/{Config.ALCHEMY_API_KEY}"
        else:
            self.rpc_url = f"https://eth-{network}.g.alchemy.com/v2/{Config.ALCHEMY_API_KEY}"
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        if not self.w3.is_connected():
            raise ConnectionError("Impossibile connettersi alla blockchain")
        
        # Setup wallet
        if Config.PRIVATE_KEY:
            self.account = Account.from_key(Config.PRIVATE_KEY)
            self.address = self.account.address
        else:
            raise ValueError("PRIVATE_KEY richiesta per DEX")
    
    def get_balance(self, token_address=None):
        """Ottiene balance ETH o token."""
        if not token_address:
            # Balance ETH
            balance_wei = self.w3.eth.get_balance(self.address)
            return self.w3.from_wei(balance_wei, 'ether')
        else:
            # Balance token ERC20 (da implementare)
            return 0.0
    
    def get_current_price(self, token_pair=None):
        """Ottiene prezzo corrente da DEX (placeholder - usa Uniswap quote)."""
        # Per ora usa CoinGecko o simile
        # In produzione: usa Uniswap Router per quote
        try:
            # Esempio: ETH/USD
            response = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "ethereum", "vs_currencies": "usd"},
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                return float(data.get('ethereum', {}).get('usd', 0))
        except Exception as e:
            print(f"Errore prezzo: {e}")
        return None
    
    def get_gas_price(self):
        """Ottiene gas price corrente."""
        try:
            gas_price = self.w3.eth.gas_price
            return self.w3.from_wei(gas_price, 'gwei')
        except Exception as e:
            print(f"Errore gas price: {e}")
            return None
    
    def place_swap_order(self, side, amount_in=None):
        """Esegue swap su Uniswap (semplificato - placeholder)."""
        # NOTA: Implementazione completa richiede:
        # - ABI di Uniswap Router
        # - Calcolo amountOutMin con slippage
        # - Costruzione e invio transazione
        
        print(f"⚠️  Swap DEX: {side} - {amount_in} ETH")
        print("   Implementazione completa richiede setup Uniswap Router")
        print("   Per ora: funzione placeholder")
        
        gas_price = self.get_gas_price()
        balance = self.get_balance()
        
        print(f"   Balance: {balance:.6f} ETH")
        print(f"   Gas price: {gas_price:.2f} Gwei")
        
        return {"status": "placeholder", "tx_hash": None}


class AlchemyClient:
    """Client per API Alchemy (dati on-chain)."""
    
    def __init__(self):
        self.api_key = Config.ALCHEMY_API_KEY
        network = "sepolia" if Config.USE_TESTNET else Config.NETWORK
        if network == "mainnet":
            self.base_url = f"https://eth-mainnet.g.alchemy.com/v2/{self.api_key}"
        else:
            self.base_url = f"https://eth-{network}.g.alchemy.com/v2/{self.api_key}"
        self.network = network
    
    def _make_request(self, method, params=[]):
        """Esegue richiesta JSON-RPC."""
        if not self.api_key:
            return None
        
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": method,
                "params": params
            }
            response = requests.post(self.base_url, json=payload, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'result' in data:
                    return data['result']
            return None
        except Exception as e:
            print(f"Errore Alchemy {method}: {e}")
            return None
    
    def get_gas_price(self):
        """Ottiene gas price corrente in Gwei."""
        result = self._make_request("eth_gasPrice")
        if result:
            return int(result, 16) / 1e9
        return None
    
    def get_block_number(self):
        """Ottiene numero blocco corrente."""
        result = self._make_request("eth_blockNumber")
        if result:
            return int(result, 16)
        return None
    
    def get_block_info(self, block_number="latest"):
        """Ottiene informazioni su un blocco."""
        if isinstance(block_number, int):
            block_number = hex(block_number)
        
        result = self._make_request("eth_getBlockByNumber", [block_number, False])
        if result:
            return {
                'number': int(result.get('number', '0x0'), 16),
                'timestamp': int(result.get('timestamp', '0x0'), 16),
                'gas_used': int(result.get('gasUsed', '0x0'), 16),
                'gas_limit': int(result.get('gasLimit', '0x0'), 16),
                'transaction_count': len(result.get('transactions', []))
            }
        return None
    
    def get_transaction_count(self, address=None):
        """Ottiene numero di transazioni di un indirizzo."""
        if not address:
            return None
        
        result = self._make_request("eth_getTransactionCount", [address, "latest"])
        if result:
            return int(result, 16)
        return None
    
    def get_balance(self, address):
        """Ottiene balance ETH di un indirizzo."""
        if not address:
            return None
        
        result = self._make_request("eth_getBalance", [address, "latest"])
        if result:
            return int(result, 16) / 1e18  # Converti in ETH
        return None
    
    def get_network_activity(self, blocks=10):
        """Ottiene metriche di attività della rete."""
        try:
            current_block = self.get_block_number()
            if not current_block:
                return None
            
            blocks_data = []
            for i in range(blocks):
                block_num = current_block - i
                block_info = self.get_block_info(block_num)
                if block_info:
                    blocks_data.append(block_info)
            
            if not blocks_data:
                return None
            
            # Calcola metriche aggregate
            avg_gas_used = sum(b['gas_used'] for b in blocks_data) / len(blocks_data)
            avg_tx_count = sum(b['transaction_count'] for b in blocks_data) / len(blocks_data)
            gas_utilization = sum(b['gas_used'] / b['gas_limit'] for b in blocks_data) / len(blocks_data)
            
            return {
                'avg_gas_used': avg_gas_used,
                'avg_transaction_count': avg_tx_count,
                'gas_utilization': gas_utilization,
                'blocks_analyzed': len(blocks_data)
            }
        except Exception as e:
            print(f"Errore network activity: {e}")
            return None

