#!/usr/bin/env python3
"""
Script per verificare lo stato del portafoglio Binance via API
Mostra tutti gli asset e un focus sulle cripto del bot
"""

import os
import sys

# Aggiungi la directory corrente al path per importare i moduli
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import APIClient
from config import Config

def format_currency(value: float) -> str:
    """Formatta un valore in USD."""
    return f"${value:,.2f}"

def main():
    print("=" * 70)
    print("📊 VERIFICA PORTAFOGLIO BINANCE")
    #print("=" * 70)
    
    # Inizializza API
    api = APIClient()
    
    testnet_status = "🧪 TESTNET" if Config.USE_TESTNET else "🔴 LIVE"
    print(f"\n{testnet_status}")
    #print("-" * 70)
    
    # Ottieni account info completo
    try:
        account_info = api.client.get_account()
    except Exception as e:
        print(f"❌ Errore nel recupero dati account: {e}")
        return
    
    # Filtra e organizza gli asset
    balances = account_info.get('balances', [])
    all_assets = []
    
    for balance in balances:
        asset = balance['asset']
        free = float(balance['free'])
        locked = float(balance['locked'])
        total = free + locked
        
        if total > 0:  # Mostra solo asset con balance > 0
            all_assets.append({
                'asset': asset,
                'free': free,
                'locked': locked,
                'total': total
            })
    
    # Ordina per asset name
    all_assets.sort(key=lambda x: x['asset'])
    
    # SEZIONE 1: TUTTI GLI ASSET
    #print("\n📦 TUTTI GLI ASSET NEL PORTAFOGLIO:")
    #print("-" * 70)
    
    if not all_assets:
        print("   ⚠️  Nessun asset trovato (portafoglio vuoto)")
    else:
        #print(f"{'Asset':<10} {'Disponibile':>15} {'Bloccato':>15} {'Totale':>15}")
        print("-" * 70)
        
        for item in all_assets:
            #print(f"{item['asset']:<10} {item['free']:>15.8f} {item['locked']:>15.8f} {item['total']:>15.8f}")
            break
    
    # SEZIONE 2: FOCUS SULLE CRIPTO DEL BOT
    #print("\n" + "=" * 70)
    print("🤖 FOCUS CRYPTO DEL BOT")
    print("=" * 70)
    
    bot_symbols = Config.SYMBOLS
    print(f"\nCoppie configurate: \n{', '.join(bot_symbols)}")
    print("-" * 70)
    
    # Estrai le crypto uniche dalle coppie (es. BTCEUR -> BTC, EUR)
    quote_asset = Config.QUOTE_ASSET
    bot_cryptos = set()
    for symbol in bot_symbols:
        # Rimuovi la quote asset dalla fine per ottenere la crypto base
        if symbol.endswith(quote_asset):
            crypto = symbol[:-len(quote_asset)]
            bot_cryptos.add(crypto)
    bot_cryptos.add(quote_asset)  # Aggiungi sempre la quote asset
    
    bot_cryptos = sorted(bot_cryptos)
    
    # Ottieni prezzi correnti per le crypto del bot
    crypto_data = []
    total_value_usd = 0.0
    
    for crypto in bot_cryptos:
        # Trova il balance per questa crypto
        balance_data = next((b for b in all_assets if b['asset'] == crypto), None)
        
        if balance_data:
            quantity = balance_data['total']
            
            # Ottieni prezzo corrente
            if crypto == quote_asset:
                price = 1.0
                value_usd = quantity
            else:
                try:
                    symbol = f"{crypto}{quote_asset}"
                    ticker = api.client.get_symbol_ticker(symbol=symbol)
                    price = float(ticker['price'])
                    value_usd = quantity * price
                except Exception as e:
                    print(f"   ⚠️  Errore nel recupero prezzo per {crypto}: {e}")
                    price = 0.0
                    value_usd = 0.0
            
            crypto_data.append({
                'crypto': crypto,
                'quantity': quantity,
                'price': price,
                'value_usd': value_usd
            })
            
            total_value_usd += value_usd
        else:
            # Crypto non presente nel portafoglio
            crypto_data.append({
                'crypto': crypto,
                'quantity': 0.0,
                'price': 0.0,
                'value_usd': 0.0
            })
    
    # Stampa i dati delle crypto del bot
    print(f"\n{'Crypto':<8} {'Quantità':>15} {'Prezzo':>15} {'Valore USD':>15} {'% Port.':>10}")
    print("-" * 70)
    
    for item in crypto_data:
        crypto = item['crypto']
        quantity = item['quantity']
        price = item['price']
        value_usd = item['value_usd']
        percent = (value_usd / total_value_usd * 100) if total_value_usd > 0 else 0.0
        
        if quantity > 0:
            print(f"{crypto:<8} {quantity:>15.8f} {format_currency(price):>15} "
                  f"{format_currency(value_usd):>15} {percent:>9.2f}%")
        else:
            print(f"{crypto:<8} {quantity:>15.8f} {'N/A':>15} "
                  f"{format_currency(value_usd):>15} {percent:>9.2f}%")
    
    print("-" * 70)
    print(f"{'TOTALE':<8} {'':>15} {'':>15} {format_currency(total_value_usd):>15} {'100.00%':>10}")
    
    # SEZIONE 3: RIEPILOGO GLOBALE
    print("\n" + "=" * 70)
    print("📈 RIEPILOGO")
    print("=" * 70)
    print(f"   💰 Valore Totale Portafoglio: {format_currency(total_value_usd)}")
    print(f"   📊 Numero Asset Totali: {len(all_assets)}")
    print(f"   🤖 Crypto Bot Attive: {len([c for c in crypto_data if c['quantity'] > 0])}/{len(bot_cryptos)}")
    
    # Calcola quanto è investito in crypto vs quote asset
    usdt_balance = next((c['value_usd'] for c in crypto_data if c['crypto'] == quote_asset), 0.0)
    crypto_invested = total_value_usd - usdt_balance

    if total_value_usd > 0:
        usdt_percent = (usdt_balance / total_value_usd) * 100
        crypto_percent = (crypto_invested / total_value_usd) * 100
        print(f"   💵 {quote_asset} (Liquidità): {format_currency(usdt_balance)} ({usdt_percent:.2f}%)")
        print(f"   🪙 Crypto Investite: {format_currency(crypto_invested)} ({crypto_percent:.2f}%)")
    
    print("\n" + "=" * 70)
    print("✅ Verifica completata!")
    print("=" * 70)

if __name__ == '__main__':
    main()

