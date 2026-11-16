# 🧪 Guida Testnet Binance

## ⚠️ Problema: Testnet Difficile da Trovare

Il testnet di Binance **Spot Trading** è su un sito diverso da quello principale!

## 🔗 Link Corretti

### Per Spot Trading (quello che usiamo):
**https://testnet.binance.vision/**

### Per Futures Trading:
**https://testnet.binancefuture.com/**

## 📝 Come Accedere al Testnet Spot

1. **Vai su**: https://testnet.binance.vision/
2. **Accedi**:
   - Clicca su **"Connect with GitHub"** (consigliato)
   - Oppure registrati con email
3. **Crea API Key**:
   - Vai a **API Management**
   - Clicca **"Create API Key"**
   - Salva API Key e Secret Key

4. **Configura `.env`**:
   ```env
   USE_TESTNET=true
   BINANCE_API_KEY=tua_testnet_api_key
   BINANCE_API_SECRET=tua_testnet_secret_key
   ```

## ⚠️ Problemi Comuni

### Problema 1: Testnet Non Disponibile

Il testnet Spot di Binance può essere:
- Instabile
- Non sempre disponibile
- Richiede GitHub per accesso

**Soluzioni Alternative:**

1. **Modalità Simulazione** (Consigliato!)
   ```bash
   python bot.py --simulate
   ```
   - ✅ Nessuna API key necessaria
   - ✅ Prezzi reali da CoinGecko
   - ✅ Simula trading realistico
   - ✅ Nessun rischio

2. **Mainnet con Quantità Piccole**
   - Usa quantità minime (~$10-20 per trade)
   - Testa con capitali molto piccoli
   - ⚠️ Sono comunque soldi reali!

### Problema 2: Non Riesco ad Accedere

Se il testnet non funziona:
- Prova con GitHub login
- Verifica che il sito sia raggiungibile
- Considera modalità simulazione

## 🎯 Raccomandazione

**Per testare il bot senza rischi:**
1. ✅ Usa **modalità simulazione**: `python bot.py --simulate`
2. ✅ Testa strategia e logica
3. ✅ Quando sei sicuro, passa a mainnet con quantità piccole

**Per testare con API reali:**
1. Prova testnet: https://testnet.binance.vision/
2. Se non funziona, usa mainnet con quantità minime ($10-20)

## 🔍 Verifica Tipo Chiavi

Per verificare se le tue chiavi sono testnet o mainnet:

```bash
python -c "
from binance.client import Client
from config import Config

# Prova testnet
try:
    client = Client(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET, testnet=True)
    account = client.get_account()
    print('✅ TESTNET')
except:
    # Prova mainnet
    try:
        client = Client(Config.BINANCE_API_KEY, Config.BINANCE_API_SECRET, testnet=False)
        account = client.get_account()
        print('✅ MAINNET (soldi reali!)')
    except Exception as e:
        print(f'❌ Errore: {e}')
"
```

## 📚 Link Utili

- **Testnet Spot**: https://testnet.binance.vision/
- **Testnet Futures**: https://testnet.binancefuture.com/
- **Documentazione**: https://developers.binance.com/docs/binance-spot-api-docs/faqs

