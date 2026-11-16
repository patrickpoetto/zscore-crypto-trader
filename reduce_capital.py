#!/usr/bin/env python3
"""
Script per bilanciare il capitale operativo del bot a $30k.
- Se USDT > $30k: converte l'eccesso in LTC (non tracciato dal bot)
- Se USDT < $30k: vende LTC per riportare USDT a $30k
"""

import sys
import os
import argparse

# Aggiungi il path della directory corrente
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api_client import APIClient
from config import Config
from binance.exceptions import BinanceAPIException

def main():
    parser = argparse.ArgumentParser(description='Bilancia il capitale operativo a $30k (USDT <-> LTC)')
    parser.add_argument('--confirm', action='store_true', help='Conferma automaticamente senza chiedere')
    args = parser.parse_args()
    print("="*70)
    print("⚖️  BILANCIAMENTO CAPITALE OPERATIVO")
    print("="*70)
    
    # Inizializza API client
    api = APIClient()
    
    # Target capital
    TARGET_CAPITAL = 30000.0
    TARGET_CRYPTO = "LTCUSDT"  # LTC non è tracciato dal bot
    
    print(f"\n🎯 Target Capitale: ${TARGET_CAPITAL:,.2f}")
    print(f"🪙 Crypto Target: {TARGET_CRYPTO}")
    
    # Get current balance
    balance_usdt = api.get_account_balance('USDT')
    print(f"\n💰 Balance USDT Attuale: ${balance_usdt:,.2f}")
    
    # Calcola differenza (positivo = eccesso, negativo = deficit)
    difference = balance_usdt - TARGET_CAPITAL
    
    if abs(difference) < 100:  # Tolleranza $100
        print(f"\n✅ Nessuna azione necessaria. Balance già al target (±$100).")
        return
    
    if difference > 0:
        # Eccesso: converti USDT in LTC
        print(f"📊 Eccesso da convertire: ${difference:,.2f}")
        operation = "BUY_LTC"
    else:
        # Deficit: vendi LTC per ottenere USDT
        deficit = abs(difference)
        print(f"📊 Deficit da compensare: ${deficit:,.2f}")
        operation = "SELL_LTC"
    
    # Conferma utente
    print(f"\n⚠️  ATTENZIONE:")
    if operation == "BUY_LTC":
        print(f"   Questa operazione convertirà ${difference:,.2f} USDT in {TARGET_CRYPTO}")
    else:
        print(f"   Questa operazione venderà LTC per ottenere ${abs(difference):,.2f} USDT")
    print(f"   Il balance USDT finale sarà circa ${TARGET_CAPITAL:,.2f}")
    
    if not args.confirm:
        risposta = input(f"\nConfermi l'operazione? (scrivi 'CONFERMA' per procedere): ")
        if risposta != 'CONFERMA':
            print("\n❌ Operazione annullata dall'utente.")
            return
    else:
        print(f"\n✅ Conferma automatica attivata (--confirm)")

    
    print(f"\n🔄 Operazione in corso...")
    
    try:
        # Get prezzo LTC
        ltc_price = api.get_current_price(TARGET_CRYPTO)
        print(f"   📈 Prezzo {TARGET_CRYPTO}: ${ltc_price:.2f}")
        
        if operation == "BUY_LTC":
            # Compra LTC con l'eccesso di USDT
            print(f"   💵 Acquisto {TARGET_CRYPTO} per ${difference:,.2f}...")
            
            order = api.place_market_order(
                symbol=TARGET_CRYPTO,
                side='BUY',
                quote_quantity_usdt=difference
            )
            
            if order:
                executed_qty = float(order.get('executedQty', 0))
                print(f"\n✅ OPERAZIONE COMPLETATA!")
                print(f"   🪙 LTC Acquistati: {executed_qty:.8f}")
                print(f"   💰 Valore: ${difference:,.2f}")
        
        else:  # SELL_LTC
            # Vendi LTC per ottenere USDT
            deficit = abs(difference)
            
            # Calcola quanti LTC vendere
            ltc_to_sell = deficit / ltc_price
            
            # Verifica balance LTC disponibile
            ltc_balance = api.get_account_balance('LTC')
            if ltc_balance < ltc_to_sell:
                print(f"\n❌ Errore: LTC insufficienti!")
                print(f"   Necessari: {ltc_to_sell:.8f} LTC")
                print(f"   Disponibili: {ltc_balance:.8f} LTC")
                return
            
            print(f"   💵 Vendita {ltc_to_sell:.8f} LTC per ottenere ~${deficit:,.2f}...")
            
            order = api.place_market_order(
                symbol=TARGET_CRYPTO,
                side='SELL',
                quantity=ltc_to_sell
            )
            
            if order:
                executed_qty = float(order.get('executedQty', 0))
                # Calcola USDT ricavati (approssimato)
                usdt_received = executed_qty * ltc_price
                print(f"\n✅ OPERAZIONE COMPLETATA!")
                print(f"   🪙 LTC Venduti: {executed_qty:.8f}")
                print(f"   💰 USDT Ricavati: ~${usdt_received:,.2f}")
        
        if order:
            # Verifica balance finale
            final_balance = api.get_account_balance('USDT')
            print(f"\n📊 Balance USDT Finale: ${final_balance:,.2f}")
            
            if abs(final_balance - TARGET_CAPITAL) < 200:  # Tolleranza $200
                print(f"✅ Capitale bilanciato con successo!")
            else:
                print(f"⚠️  Attenzione: Balance finale diverso dal target")
        else:
            print("\n❌ Errore nell'esecuzione dell'ordine")
            
    except BinanceAPIException as e:
        print(f"\n❌ Errore Binance API: {e}")
    except Exception as e:
        print(f"\n❌ Errore: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

