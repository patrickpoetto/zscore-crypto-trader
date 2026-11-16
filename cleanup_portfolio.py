#!/usr/bin/env python3
"""
Script per convertire TUTTI gli asset del portafoglio Binance in USDT
ATTENZIONE: Questo script vende TUTTO tranne USDT!
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
    print("🔥 CLEANUP PORTAFOGLIO BINANCE - CONVERSIONE TOTALE IN USDT")
    print("=" * 70)
    
    # Inizializza API
    api = APIClient()
    
    testnet_status = "🧪 TESTNET" if Config.USE_TESTNET else "🔴 LIVE"
    print(f"\n{testnet_status}")
    
    if not Config.USE_TESTNET:
        print("\n❌ ERRORE: Questo script funziona SOLO su testnet per sicurezza!")
        print("   Se vuoi usarlo su LIVE, modifica il controllo nel codice.")
        return
    
    print("-" * 70)
    print("\n⚠️  ATTENZIONE: Questo script venderà TUTTE le crypto e le convertirà in USDT!")
    print("   Stai per vendere:")
    print("   - Tutti gli asset nel portafoglio")
    print("   - Solo USDT, BUSD, USDC e stablecoin simili saranno preservati")
    print("-" * 70)
    
    if not confirm:
        print("\n❌ ERRORE: Devi confermare l'operazione con --confirm")
        print("   Uso: python cleanup_portfolio.py --confirm")
        return
    
    print("\n" + "=" * 70)
    print("📊 FASE 1: Cancellazione ordini aperti")
    print("=" * 70)
    
    # Prima cancella TUTTI gli ordini aperti per sbloccare i balance
    try:
        print("\n🔄 Recupero ordini aperti...")
        open_orders = api.client.get_open_orders()
        
        if open_orders:
            print(f"   Trovati {len(open_orders)} ordini aperti, cancellazione in corso...")
            for order in open_orders:
                try:
                    api.client.cancel_order(symbol=order['symbol'], orderId=order['orderId'])
                    print(f"   ✅ Cancellato ordine {order['orderId']} su {order['symbol']}")
                except Exception as e:
                    print(f"   ⚠️  Errore cancellazione ordine {order['orderId']}: {e}")
            print(f"\n✅ Cancellati {len(open_orders)} ordini")
        else:
            print("   ✅ Nessun ordine aperto")
    except Exception as e:
        print(f"   ⚠️  Errore nel recupero/cancellazione ordini: {e}")
    
    print("\n" + "=" * 70)
    print("📊 FASE 2: Recupero asset dal portafoglio")
    print("=" * 70)
    
    # Attendi un attimo per permettere al sistema di aggiornare i balance
    time.sleep(2)
    
    # Ottieni account info AGGIORNATO dopo la cancellazione ordini
    try:
        account_info = api.client.get_account()
    except Exception as e:
        print(f"❌ Errore nel recupero dati account: {e}")
        return
    
    balances = account_info.get('balances', [])
    
    # Filtra asset da vendere (esclude stablecoin)
    stablecoins = ['USDT', 'USDC', 'BUSD', 'TUSD', 'USDP', 'DAI', 'FDUSD', 'USDE', 
                   'USD1', 'XUSD', 'BFUSD', 'AEUR', 'EURI', 'EUR']
    
    assets_to_sell = []
    for balance in balances:
        asset = balance['asset']
        free = float(balance['free'])
        locked = float(balance['locked'])
        total = free + locked
        
        if total > 0 and asset not in stablecoins:
            assets_to_sell.append({
                'asset': asset,
                'free': free,
                'locked': locked,
                'total': total
            })
    
    print(f"\n✅ Trovati {len(assets_to_sell)} asset da convertire in USDT")
    print(f"   (Escluse {len(stablecoins)} stablecoin che saranno preservate)")
    
    if not assets_to_sell:
        print("\n✅ Portafoglio già pulito! Solo stablecoin presenti.")
        return
    
    print("\n" + "=" * 70)
    print("💱 FASE 3: Conversione asset in USDT")
    print("=" * 70)
    
    successful_sales = 0
    failed_sales = 0
    total_usdt_gained = 0.0
    
    for i, asset_data in enumerate(assets_to_sell, 1):
        asset = asset_data['asset']
        quantity = asset_data['total']  # Usa il totale (dopo aver cancellato ordini, tutto è "free")
        
        if quantity <= 0:
            print(f"\n[{i}/{len(assets_to_sell)}] ⏭️  {asset}: Saltato (quantità zero)")
            continue
        
        print(f"\n[{i}/{len(assets_to_sell)}] 🔄 Tentativo vendita {asset}...")
        
        # Prova prima con USDT, poi con BUSD, poi con USDC
        trading_pairs = [
            f"{asset}USDT",
            f"{asset}BUSD", 
            f"{asset}USDC"
        ]
        
        sold = False
        for symbol in trading_pairs:
            try:
                # Verifica se il simbolo esiste
                symbol_info = api.client.get_symbol_info(symbol)
                if not symbol_info:
                    continue
                
                # Ottieni filtri per il simbolo
                filters = {f['filterType']: f for f in symbol_info.get('filters', [])}
                
                # Aggiusta quantità in base ai filtri LOT_SIZE
                if 'LOT_SIZE' in filters:
                    step_size = float(filters['LOT_SIZE']['stepSize'])
                    min_qty = float(filters['LOT_SIZE']['minQty'])
                    
                    # Arrotonda quantità al step_size
                    if step_size < 1:
                        decimals = len(str(step_size).rstrip('0').split('.')[-1])
                        adjusted_qty = round(quantity - (quantity % step_size), decimals)
                    else:
                        adjusted_qty = quantity - (quantity % step_size)
                    
                    if adjusted_qty < min_qty:
                        print(f"   ⚠️  {symbol}: Quantità {adjusted_qty} < minima {min_qty}, skip")
                        continue
                    
                    quantity = adjusted_qty
                
                # Ottieni prezzo corrente per stimare il valore
                ticker = api.client.get_symbol_ticker(symbol=symbol)
                price = float(ticker['price'])
                estimated_value = quantity * price
                
                # Verifica valore minimo notional (solitamente $10 su Binance)
                if 'NOTIONAL' in filters:
                    min_notional = float(filters['NOTIONAL']['minNotional'])
                    if estimated_value < min_notional:
                        print(f"   ⚠️  {symbol}: Valore ${estimated_value:.2f} < minimo ${min_notional:.2f}, skip")
                        continue
                elif estimated_value < 10:  # Default $10 se NOTIONAL non specificato
                    print(f"   ⚠️  {symbol}: Valore ${estimated_value:.2f} troppo basso, skip")
                    continue
                
                # Esegui ordine di vendita a mercato
                print(f"   📤 Vendita {quantity} {asset} su {symbol} (~${estimated_value:.2f})...")
                
                order = api.client.order_market_sell(
                    symbol=symbol,
                    quantity=quantity
                )
                
                # Calcola USDT ricavati
                executed_qty = float(order.get('executedQty', 0))
                cummulative_quote_qty = float(order.get('cummulativeQuoteQty', 0))
                
                print(f"   ✅ VENDUTO! Ricavati ~${cummulative_quote_qty:.2f}")
                total_usdt_gained += cummulative_quote_qty
                successful_sales += 1
                sold = True
                break  # Vendita riuscita, esci dal loop dei trading pairs
                
            except Exception as e:
                error_msg = str(e)
                if "Invalid symbol" in error_msg or "does not exist" in error_msg:
                    continue  # Prova il prossimo pair
                else:
                    print(f"   ❌ Errore: {error_msg}")
                    # Continua comunque con il prossimo pair
                    continue
        
        if not sold:
            print(f"   ❌ Impossibile vendere {asset} (nessun trading pair valido)")
            failed_sales += 1
        
        # Pausa breve per non sovraccaricare API
        time.sleep(0.1)
    
    # Riepilogo finale
    print("\n" + "=" * 70)
    print("📊 RIEPILOGO OPERAZIONI")
    print("=" * 70)
    print(f"   ✅ Vendite riuscite: {successful_sales}")
    print(f"   ❌ Vendite fallite: {failed_sales}")
    print(f"   💰 USDT totali ricavati: ~${total_usdt_gained:.2f}")
    
    # Verifica balance finale
    print("\n" + "=" * 70)
    print("💵 BALANCE USDT FINALE")
    print("=" * 70)
    
    try:
        final_account = api.client.get_account()
        usdt_balance = 0.0
        for balance in final_account.get('balances', []):
            if balance['asset'] == 'USDT':
                usdt_balance = float(balance['free']) + float(balance['locked'])
                break
        
        print(f"   💰 Balance USDT: ${usdt_balance:,.2f}")
        
    except Exception as e:
        print(f"   ⚠️  Errore nel recupero balance finale: {e}")
    
    print("\n" + "=" * 70)
    print("✅ CLEANUP COMPLETATO!")
    print("=" * 70)
    print("\n💡 Prossimi passi:")
    print("   1. Elimina il file positions_state.json se esiste")
    print("   2. Riavvia il bot per iniziare con un portafoglio pulito")
    print("\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Converte tutti gli asset in USDT')
    parser.add_argument('--confirm', action='store_true', help='Conferma operazione')
    args = parser.parse_args()
    
    try:
        main(confirm=args.confirm)
    except KeyboardInterrupt:
        print("\n\n❌ Operazione annullata dall'utente")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Errore fatale: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

