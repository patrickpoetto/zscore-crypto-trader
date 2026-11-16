"""Script per creare un nuovo wallet Ethereum."""
from eth_account import Account
import secrets

def create_wallet():
    """Crea un nuovo wallet Ethereum."""
    # Genera chiave privata random
    private_key = secrets.token_hex(32)
    
    # Crea account dalla chiave privata
    account = Account.from_key(private_key)
    
    print("=" * 60)
    print("🆕 NUOVO WALLET CREATO")
    print("=" * 60)
    print(f"\n📝 PRIVATE_KEY={private_key}")
    print(f"\n📍 WALLET_ADDRESS={account.address}")
    print("\n" + "=" * 60)
    print("⚠️  IMPORTANTE:")
    print("   - Salva la PRIVATE_KEY in un posto SICURO")
    print("   - NON condividere mai la chiave privata")
    print("   - Perde i fondi chiunque abbia la chiave privata")
    print("=" * 60)
    
    # Salva in file (opzionale)
    save = input("\nSalvare le credenziali in wallet.txt? (s/n): ").lower()
    if save == 's':
        with open('wallet.txt', 'w') as f:
            f.write(f"PRIVATE_KEY={private_key}\n")
            f.write(f"WALLET_ADDRESS={account.address}\n")
        print("✅ Salvato in wallet.txt")
        print("⚠️  Elimina wallet.txt dopo aver copiato i dati nel .env")
    
    return private_key, account.address

if __name__ == '__main__':
    create_wallet()

