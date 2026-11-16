"""Configurazione del bot."""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Gestione configurazione."""
    
    # Modalità trading: 'DEX' o 'CEX' (Binance)
    TRADING_MODE = os.getenv('TRADING_MODE', 'DEX').upper()
    
    # API Keys (CEX - Binance, opzionale)
    BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
    BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET', '')
    
    # Alchemy (DEX - obbligatorio per wallet privato)
    ALCHEMY_API_KEY = os.getenv('ALCHEMY_API_KEY', '')
    
    # Wallet privato (DEX)
    PRIVATE_KEY = os.getenv('PRIVATE_KEY', '').replace('0x', '')
    WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '')
    
    # Network
    NETWORK = os.getenv('NETWORK', 'mainnet')  # mainnet, sepolia, etc.
    USE_TESTNET = os.getenv('USE_TESTNET', 'false').lower() == 'true'

    # Hyperliquid (DEX perpetual/spot separato da Binance, per cash-and-carry funding)
    HYPERLIQUID_USE_TESTNET = os.getenv('HYPERLIQUID_USE_TESTNET', 'true').lower() == 'true'
    HYPERLIQUID_PRIVATE_KEY = os.getenv('HYPERLIQUID_PRIVATE_KEY', '')
    HYPERLIQUID_WALLET_ADDRESS = os.getenv('HYPERLIQUID_WALLET_ADDRESS', '')
    
    # Valuta di quotazione fissa per tutte le coppie CEX (es. 'USDT' o 'EUR').
    # Tutte le coppie in SYMBOLS devono usare questa stessa quote asset.
    QUOTE_ASSET = os.getenv('QUOTE_ASSET', 'USDT').upper()

    # Trading - Supporto multi-coppia
    SYMBOL = os.getenv('SYMBOL', 'WETH/USDC')  # Singola coppia (legacy)
    SYMBOLS = os.getenv('SYMBOLS', '').split(',') if os.getenv('SYMBOLS') else []  # Lista coppie
    # Se SYMBOLS è vuoto, usa SYMBOL come lista
    if not SYMBOLS or SYMBOLS == ['']:
        SYMBOLS = [SYMBOL] if SYMBOL else []
    
    # TIMEFRAME: Intervallo candele OHLC (Binance supporta: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M)
    TIMEFRAME = os.getenv('TIMEFRAME', '5m')
    VALID_TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d', '3d', '1w', '1M']
    
    # Modalità accumulo: cap massimo in % del capitale per coppia
    # Se configurato, il bot accumula posizioni fino a raggiungere questo cap
    # Esempio: MAX_POSITION_PERCENT=20.0 significa max 20% del capitale per coppia
    MAX_POSITION_PERCENT = float(os.getenv('MAX_POSITION_PERCENT', '0'))  # 0 = disabilitato (usa quantità fissa)
    USE_POSITION_ACCUMULATION = MAX_POSITION_PERCENT > 0
    
    # Quantità incrementale per accumulo (quanto comprare ad ogni segnale BUY)
    # Può essere in % del capitale o valore fisso in USDT
    ACCUMULATION_AMOUNT_USD = float(os.getenv('ACCUMULATION_AMOUNT_USD', '0'))  # Valore fisso in USDT (0 = usa %)
    ACCUMULATION_PERCENT = float(os.getenv('ACCUMULATION_PERCENT', '2.0'))  # % del capitale per ogni accumulo (default 2%)
    
    # Take Profit Parziale
    # Se abilitato, vende una % della posizione quando raggiunge un profitto target
    ENABLE_PARTIAL_TAKE_PROFIT = os.getenv('ENABLE_PARTIAL_TAKE_PROFIT', 'false').lower() == 'true'
    TAKE_PROFIT_PERCENT = float(os.getenv('TAKE_PROFIT_PERCENT', '5.0'))  # % di profitto per triggerare TP (es. 5.0 = +5%)
    PARTIAL_SELL_PERCENT = float(os.getenv('PARTIAL_SELL_PERCENT', '50.0'))  # % della posizione da vendere quando TP raggiunto (es. 50.0 = 50%)
    
    # CAPITAL_LIMIT rimosso - causava troppa complessità e bug
    
    # Intervallo tra cicli (in secondi)
    CYCLE_INTERVAL = int(os.getenv('CYCLE_INTERVAL', '30'))
    
    # Reportistica
    REPORT_INTERVAL = int(os.getenv('REPORT_INTERVAL', '10'))  # Report ogni N cicli
    
    # Fee Trading (in percentuale)
    TRADING_FEE_PERCENT = float(os.getenv('TRADING_FEE_PERCENT', '0.1'))  # 0.1% default (Binance)
    # NOTA: Gas fee su Ethereum mainnet è ~0.004-0.006 ETH per swap (~$12-18 con ETH a $3000)
    # Questo è PROIBITIVO per trade piccoli! Usa CEX per trade <$1000, o aumenta ACCUMULATION_PERCENT
    # Per simulazione/test, puoi ridurre questo valore, ma in produzione sarà quello reale
    GAS_FEE_ESTIMATE = float(os.getenv('GAS_FEE_ESTIMATE', '0.0045'))  # ETH per transazione (DEX - realistico per mainnet)
    
    # Strategia - Parametri Base
    Z_SCORE_THRESHOLD = float(os.getenv('Z_SCORE_THRESHOLD', '2.0'))
    LOOKBACK_PERIOD = int(os.getenv('LOOKBACK_PERIOD', '20'))
    MA_PERIOD = int(os.getenv('MA_PERIOD', '10'))
    
    # Strategia - Filtri e Controlli (Configurabili per Test)
    USE_PREV_ZSCORE_FILTER = os.getenv('USE_PREV_ZSCORE_FILTER', 'true').lower() == 'true'
    USE_MOMENTUM_FILTER = os.getenv('USE_MOMENTUM_FILTER', 'true').lower() == 'true'
    USE_MA_FILTER = os.getenv('USE_MA_FILTER', 'true').lower() == 'true'
    MIN_CONFIDENCE = float(os.getenv('MIN_CONFIDENCE', '0.5'))  # Confidence minima per eseguire ordine
    
    @classmethod
    def validate(cls):
        """Valida configurazione."""
        # Valida TIMEFRAME
        if cls.TIMEFRAME not in cls.VALID_TIMEFRAMES:
            raise ValueError(
                f"TIMEFRAME '{cls.TIMEFRAME}' non valido. "
                f"Valori supportati: {', '.join(cls.VALID_TIMEFRAMES)}"
            )
        
        # Valida modalità trading
        if cls.TRADING_MODE == 'CEX':
            if not cls.BINANCE_API_KEY or not cls.BINANCE_API_SECRET:
                raise ValueError("Modalità CEX: API keys Binance mancanti.")
        elif cls.TRADING_MODE == 'DEX':
            if not cls.ALCHEMY_API_KEY:
                raise ValueError("Modalità DEX: ALCHEMY_API_KEY mancante.")
            if not cls.PRIVATE_KEY:
                raise ValueError("Modalità DEX: PRIVATE_KEY mancante.")
            if not cls.WALLET_ADDRESS:
                raise ValueError("Modalità DEX: WALLET_ADDRESS mancante.")
        
        # Avviso se usa SYMBOL invece di SYMBOLS
        if cls.SYMBOL and not os.getenv('SYMBOLS'):
            print("⚠️  Usando SYMBOL (singola coppia). Per multi-coppia, usa SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT")

