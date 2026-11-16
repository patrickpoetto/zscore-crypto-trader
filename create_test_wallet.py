"""Script per creare un wallet di test (testnet)."""
from eth_account import Account
import secrets

def create_test_wallet():
    """Crea un nuovo wallet Ethereum per testnet."""
    # Genera chiave privata random
    private_key = secrets.token_hex(32)
    
    # Crea account dalla chiave privata
    account = Account.from_key(private_key)
    
    print("=" * 60)
    print("🧪 WALLET DI TEST CREATO (per testnet)")
    print("=" * 60)
    print(f"\n📝 PRIVATE_KEY={private_key}")
    print(f"\n📍 WALLET_ADDRESS={account.address}")
    print("\n" + "=" * 60)
    print("ℹ️  INFO TESTNET:")
    print("   - Usa Sepolia testnet: https://sepoliafaucet.com/")
    print("   - Ottieni ETH gratuiti per test")
    print("   - Questo wallet è SOLO per test!")
    print("=" * 60)
    print("⚠️  IMPORTANTE:")
    print("   - NON usare questo wallet per fondi reali")
    print("   - Salva la chiave solo per test")
    print("=" * 60)
    
    # Salva in file (opzionale)
    save = input("\nSalvare le credenziali in test_wallet.txt? (s/n): ").lower()
    if save == 's':
        with open('test_wallet.txt', 'w') as f:
            f.write(f"# Wallet di test - NON usare per fondi reali!\n")
            f.write(f"PRIVATE_KEY={private_key}\n")
            f.write(f"WALLET_ADDRESS={account.address}\n")
            f.write(f"\n# Configurazione per .env:\n")
            f.write(f"NETWORK=sepolia\n")
            f.write(f"USE_TESTNET=true\n")
        print("✅ Salvato in test_wallet.txt")
        print("⚠️  Copia i valori nel .env per testare")
    
    return private_key, account.address

if __name__ == '__main__':
    create_test_wallet()

