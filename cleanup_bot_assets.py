#!/usr/bin/env python3
"""
Script per vendere SOLO le crypto gestite dal bot e convertirle in USDT
"""

import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import APIClient
from config import Config

def main(confirm=False):
    print("=" * 70)
    print("🔥 CLEANUP CRYPTO DEL BOT → USDT")
    print("=" * 70)
    
    # Inizializza API
    api = APIClient()
    
    testnet_status = "🧪 TESTNET" if Config.USE_TESTNET else "🔴 LIVE"
    print(f"\n{testnet_status}")
    
    if not Config.USE_TESTNET:
        print("\n❌ ERRORE: Questo script funziona SOLO su testnet per sicurezza!")
        return
    
    # Estrai le crypto base dai simboli del bot (rimuove la quote asset configurata)
    quote_asset = Config.QUOTE_ASSET
    bot_assets = []
    for symbol in Config.SYMBOLS:
        if symbol.endswith(quote_asset):
            asset = symbol[:-len(quote_asset)]
            bot_assets.append(asset)
    
    print(f"\n📊 Crypto da convertire: {', '.join(bot_assets)}")
    print("-" * 70)
    
    if not confirm:
        print("\n❌ ERRORE: Devi confermare l'operazione con --confirm")
        print("   Uso: python cleanup_bot_assets.py --confirm")
        return
    
    print("\n" + "=" * 70)
    print("🔄 FASE 1: Cancellazione ordini aperti")
    print("=" * 70)
    
    # Cancella ordini aperti
    try:
        open_orders = api.client.get_open_orders()
        if open_orders:
            print(f"   Trovati {len(open_orders)} ordini aperti")
            for order in open_orders:
                try:
                    api.client.cancel_order(symbol=order['symbol'], orderId=order['orderId'])
                    print(f"   ✅ Cancellato {order['symbol']}")
                except Exception as e:
                    print(f"   ⚠️  Errore: {e}")
        else:
            print("   ✅ Nessun ordine aperto")
    except Exception as e:
        print(f"   ⚠️  Errore: {e}")
    
    time.sleep(2)  # Attendi aggiornamento balance
    
    print("\n" + "=" * 70)
    print("💱 FASE 2: Vendita crypto")
    print("=" * 70)
    
    # Ottieni balance attuale
    try:
        account_info = api.client.get_account()
    except Exception as e:
        print(f"❌ Errore: {e}")
        return
    
    balances = {b['asset']: float(b['free']) + float(b['locked']) 
                for b in account_info.get('balances', [])}
    
    successful = 0
    failed = 0
    total_usdt = 0.0
    
    for i, asset in enumerate(bot_assets, 1):
        quantity = balances.get(asset, 0.0)
        
        print(f"\n[{i}/{len(bot_assets)}] {asset}:")
        print(f"   Balance: {quantity:.8f} {asset}")
        
        if quantity <= 0:
            print(f"   ⏭️  Skip (nessun balance)")
            continue
        
        symbol = f"{asset}{quote_asset}"
        
        try:
            # Ottieni info simbolo
            symbol_info = api.client.get_symbol_info(symbol)
            if not symbol_info:
                print(f"   ❌ Simbolo {symbol} non trovato")
                failed += 1
                continue
            
            # Ottieni prezzo corrente
            ticker = api.client.get_symbol_ticker(symbol=symbol)
            price = float(ticker['price'])
            estimated_value = quantity * price
            
            print(f"   Prezzo: ${price:,.2f}")
            print(f"   Valore: ${estimated_value:,.2f}")
            
            # Aggiusta quantità ai filtri
            filters = {f['filterType']: f for f in symbol_info.get('filters', [])}
            
            if 'LOT_SIZE' in filters:
                step_size = float(filters['LOT_SIZE']['stepSize'])
                min_qty = float(filters['LOT_SIZE']['minQty'])
                
                # Arrotonda al step_size
                if step_size < 1:
                    decimals = len(str(step_size).rstrip('0').split('.')[-1])
                    adjusted_qty = round(quantity - (quantity % step_size), decimals)
                else:
                    adjusted_qty = quantity - (quantity % step_size)
                
                if adjusted_qty < min_qty:
                    print(f"   ⚠️  Quantità {adjusted_qty} < minima {min_qty}")
                    failed += 1
                    continue
                
                quantity = adjusted_qty
                estimated_value = quantity * price
            
            # Check notional minimo
            if 'NOTIONAL' in filters:
                min_notional = float(filters['NOTIONAL']['minNotional'])
                if estimated_value < min_notional:
                    print(f"   ⚠️  Valore ${estimated_value:.2f} < minimo ${min_notional:.2f}")
                    failed += 1
                    continue
            elif estimated_value < 5.0:
                print(f"   ⚠️  Valore ${estimated_value:.2f} troppo basso")
                failed += 1
                continue
            
            # VENDI!
            print(f"   📤 Vendita di {quantity:.8f} {asset}...")
            
            order = api.client.order_market_sell(
                symbol=symbol,
                quantity=quantity
            )
            
            usdt_received = float(order.get('cummulativeQuoteQty', 0))
            
            print(f"   ✅ VENDUTO! Ricavati {usdt_received:,.2f} {quote_asset}")
            successful += 1
            total_usdt += usdt_received

        except Exception as e:
            print(f"   ❌ Errore: {e}")
            failed += 1

        time.sleep(0.2)  # Pausa tra ordini

    # Riepilogo
    print("\n" + "=" * 70)
    print("📊 RIEPILOGO")
    print("=" * 70)
    print(f"   ✅ Vendite riuscite: {successful}/{len(bot_assets)}")
    print(f"   ❌ Vendite fallite: {failed}/{len(bot_assets)}")
    print(f"   💰 {quote_asset} totali ricavati: {total_usdt:,.2f}")

    # Balance finale quote asset
    try:
        time.sleep(1)
        final_account = api.client.get_account()
        usdt_balance = 0.0
        for b in final_account.get('balances', []):
            if b['asset'] == quote_asset:
                usdt_balance = float(b['free']) + float(b['locked'])
                break
        print(f"   💵 Balance {quote_asset} finale: {usdt_balance:,.2f}")
    except Exception as e:
        print(f"   ⚠️  Errore: {e}")
    
    print("\n" + "=" * 70)
    print("✅ CLEANUP COMPLETATO!")
    print("=" * 70)
    print("\n💡 Prossimi passi:")
    print("   1. Elimina positions_state.json")
    print("   2. Riavvia il bot\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Vende le crypto del bot')
    parser.add_argument('--confirm', action='store_true', help='Conferma operazione')
    args = parser.parse_args()
    
    try:
        main(confirm=args.confirm)
    except KeyboardInterrupt:
        print("\n\n❌ Operazione annullata")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Errore: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

