"""
Client per Hyperliquid (perpetual futures DEX), usato SOLO per la gamba "short perpetual"
del cash-and-carry: lo spot (gamba "long") resta su Binance (api_client.py), dove abbiamo
già le coppie EUR. Hyperliquid non sostituisce Binance, lo affianca.

Perché questa architettura:
- Su Hyperliquid lo spot esiste solo per pochi asset (wrapped: UBTC, UETH, USOL), non per
  BNB/AVAX. Il perpetual invece copre tutti gli asset che ci interessano.
- Tenendo lo spot su Binance (dove è già tutto costruito) e aprendo solo lo short-perp su
  Hyperliquid, il cash-and-carry funziona per tutte le 5 coin (BTC, ETH, BNB, SOL, AVAX),
  non solo le 3 con spot nativo su Hyperliquid.

Leva bassa di default (2x): la posizione è pensata come COPERTURA (delta-neutral rispetto
allo spot detenuto su Binance), non come scommessa a leva. Una leva più alta userebbe meno
margine ma aumenta il rischio di liquidazione se spot e perp divergono temporaneamente.
"""
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from eth_account import Account
from config import Config

DEFAULT_LEVERAGE = 2


class HyperliquidClient:
    """Client per la gamba perpetual (short) del cash-and-carry su Hyperliquid."""

    def __init__(self):
        if not Config.HYPERLIQUID_PRIVATE_KEY or not Config.HYPERLIQUID_WALLET_ADDRESS:
            raise ValueError("HYPERLIQUID_PRIVATE_KEY e HYPERLIQUID_WALLET_ADDRESS richiesti nel .env")

        self.base_url = constants.TESTNET_API_URL if Config.HYPERLIQUID_USE_TESTNET else constants.MAINNET_API_URL
        self.address = Config.HYPERLIQUID_WALLET_ADDRESS
        self.account = Account.from_key(Config.HYPERLIQUID_PRIVATE_KEY)

        self.info = Info(self.base_url, skip_ws=True)
        self.exchange = Exchange(self.account, self.base_url, account_address=self.address)

    def get_account_value(self) -> float:
        """Valore totale del conto perpetual (margine + PnL non realizzato), in USDC."""
        state = self.info.user_state(self.address)
        return float(state['marginSummary']['accountValue'])

    def get_withdrawable(self) -> float:
        """USDC libero (non usato come margine)."""
        state = self.info.user_state(self.address)
        return float(state['withdrawable'])

    def get_mark_price(self, coin: str) -> float:
        """Prezzo mark corrente del perpetual."""
        ctxs = self.info.meta_and_asset_ctxs()
        universe, asset_ctxs = ctxs[0]['universe'], ctxs[1]
        for i, a in enumerate(universe):
            if a['name'] == coin:
                return float(asset_ctxs[i]['markPx'])
        raise ValueError(f"Coin {coin} non trovato tra i perpetual Hyperliquid")

    def get_funding_rate(self, coin: str) -> float:
        """Funding rate corrente (orario, frazionale es. 0.0001 = 0.01%)."""
        ctxs = self.info.meta_and_asset_ctxs()
        universe, asset_ctxs = ctxs[0]['universe'], ctxs[1]
        for i, a in enumerate(universe):
            if a['name'] == coin:
                return float(asset_ctxs[i]['funding'])
        raise ValueError(f"Coin {coin} non trovato tra i perpetual Hyperliquid")

    def get_position(self, coin: str):
        """Posizione perpetual corrente per una coin, o None se non aperta."""
        state = self.info.user_state(self.address)
        for pos in state.get('assetPositions', []):
            if pos['position']['coin'] == coin:
                return pos['position']
        return None

    def set_leverage(self, coin: str, leverage: int = DEFAULT_LEVERAGE):
        """Imposta la leva (cross margin) per una coin, prima di aprire la posizione."""
        return self.exchange.update_leverage(leverage, coin, is_cross=True)

    def open_short(self, coin: str, usd_notional: float, leverage: int = DEFAULT_LEVERAGE):
        """
        Apre una posizione SHORT sul perpetual, dimensionata in USD nozionali (deve
        corrispondere al valore della posizione spot long tenuta su Binance, per essere
        delta-neutral).
        """
        self.set_leverage(coin, leverage)
        mark_price = self.get_mark_price(coin)
        size = round(usd_notional / mark_price, 5)
        return self.exchange.market_open(coin, is_buy=False, sz=size)

    def close_position(self, coin: str):
        """Chiude (buy back) la posizione short sul perpetual."""
        return self.exchange.market_close(coin)

    def estimate_funding_pnl(self, coin: str, usd_notional: float, hours: float) -> float:
        """Stima il PnL da funding (USD) per una posizione short di data size, su N ore,
        assumendo il funding rate corrente costante (solo stima, non garanzia)."""
        rate = self.get_funding_rate(coin)
        return usd_notional * rate * hours
