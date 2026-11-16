# Setup Binance (CEX) - Guida Rapida

## 1. Crea API Key su Binance

1. Vai su [Binance](https://www.binance.com/)
2. Accedi al tuo account
3. Vai a **Account** → **API Management**
4. Clicca **Create API**
5. **IMPORTANTE**: 
   - ✅ Abilita solo **"Enable Spot & Margin Trading"**
   - ❌ NON abilitare "Enable Withdrawals" (per sicurezza)
   - ✅ Salva la **API Key** e **Secret Key** (la secret si mostra solo una volta!)

## 2. Configura `.env`

Aggiungi/modifica queste righe nel tuo `.env`:

```env
# Modalità CEX (Binance)
TRADING_MODE=CEX

# API Keys Binance
BINANCE_API_KEY=la_tua_api_key_qui
BINANCE_API_SECRET=la_tua_secret_key_qui

# Testnet (opzionale, per test senza soldi reali)
USE_TESTNET=false

# Coppie da tradare (formato Binance: BTCUSDT, ETHUSDT, etc.)
SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT

# Quantità per coppia (in base asset, es. 0.001 BTC)
QUANTITY_PER_PAIR=0.001,0.001,0.001

# Timeframe candele (5m = 5 minuti)
TIMEFRAME=5m

# Intervallo tra cicli (secondi)
CYCLE_INTERVAL=30
```

## 3. Testnet (Consigliato per Test)

Per testare senza soldi reali:

**⚠️ IMPORTANTE**: Il testnet di Binance Spot è diverso dal testnet Futures!

**Per Spot Trading (quello che usiamo):**
1. Vai su: **https://testnet.binance.vision/**
2. Clicca su **"Connect with GitHub"** o registrati
3. Vai a **API Management**
4. Crea API Key testnet
5. Nel `.env`:
   ```env
   USE_TESTNET=true
   BINANCE_API_KEY=tua_testnet_api_key
   BINANCE_API_SECRET=tua_testnet_secret_key
   ```

**⚠️ NOTA**: Il testnet Spot di Binance può essere instabile o non sempre disponibile. Se non riesci ad accedere:
- Puoi testare direttamente su mainnet con **quantità molto piccole** (es. $10-20)
- O usare la modalità simulazione: `python bot.py --simulate`

## 4. Formato Simboli

**Binance usa formato senza slash:**
- ✅ `BTCUSDT` (corretto)
- ✅ `ETHUSDT` (corretto)
- ❌ `BTC/USDT` (verrà convertito automaticamente)
- ❌ `BTC-USDT` (verrà convertito automaticamente)

Il bot normalizza automaticamente i simboli, ma usa sempre `BTCUSDT` per chiarezza.

## 5. Quantità Minime

Binance ha quantità minime per ogni coppia:
- **BTCUSDT**: Min ~$10 USDT
- **ETHUSDT**: Min ~$10 USDT
- **BNBUSDT**: Min ~$10 USDT

**Suggerimento**: Usa almeno `QUANTITY` che risulti in ~$10-20 USDT per trade.

Esempio:
- BTC a $100,000 → `QUANTITY=0.0001` BTC = $10 ✅
- ETH a $3,000 → `QUANTITY=0.003` ETH = $9 ✅

## 6. Fee Binance

- **Spot Trading**: 0.1% (maker/taker)
- **Esempio**: Trade di $100 → Fee = $0.10 ✅

Molto più convenienti delle fee DEX!

## 7. Avvia il Bot

```bash
python bot.py
```

## 8. Verifica

Il bot mostrerà:
```
🤖 Bot avviato - Modalità: CEX
   📊 Coppie: 3 - BTCUSDT, ETHUSDT, BNBUSDT
   💰 Balance USDT: $100.00
```

Se vedi errori:
- ✅ Verifica API keys
- ✅ Verifica formato simboli
- ✅ Verifica quantità minime
- ✅ Verifica balance sufficiente

## 9. Sicurezza - CRITICO! 🔒

### ⚠️ Restrizioni IP (OBBLIGATORIO per sicurezza)

**Binance sconsiglia VIVAMENTE di usare chiavi API senza restrizioni IP con permessi di trading!**

**Cosa fare:**

1. **Quando crei la API Key:**
   - ✅ **Abilita "IP Access Restriction"** (Restrizione Accesso IP)
   - ✅ **Aggiungi il tuo IP pubblico** (o range di IP se usi VPN/VPS)
   - ❌ **NON lasciare "Unrestricted IP Access"** se abiliti trading!

2. **Come trovare il tuo IP:**
   - Vai su https://whatismyipaddress.com/
   - Copia il tuo **IPv4 Address**
   - Aggiungilo nella whitelist IP di Binance

3. **Se usi VPS/Server:**
   - Aggiungi l'IP del server nella whitelist
   - Se l'IP cambia, devi aggiornare la whitelist

4. **Se usi rete dinamica (IP cambia):**
   - Considera di usare un VPS con IP statico
   - Oppure usa solo testnet (meno critico)

### ⚠️ Controlli di Sicurezza Predefiniti

**Se abiliti "Controlli di sicurezza predefiniti":**
- Le chiavi API **Unrestricted-IP-Access** (senza restrizioni IP) **NON possono avere permessi di trading**
- Binance le revocherà periodicamente o immediatamente

**Raccomandazione:**
- ✅ **Abilita i controlli predefiniti** (più sicuro)
- ✅ **MA configura sempre restrizioni IP** per le tue API keys
- ✅ Così hai massima sicurezza

### ✅ Checklist Sicurezza

- ✅ **IP Whitelist configurato** (non "Unrestricted")
- ✅ **Solo "Enable Spot & Margin Trading"** abilitato
- ✅ **"Enable Withdrawals" DISABILITATO** (non serve per trading)
- ✅ **"Enable Futures" DISABILITATO** (se non usi futures)
- ✅ **API keys salvate in `.env`** (non in codice)
- ✅ **`.env` nel `.gitignore`** (non committare mai!)
- ✅ **Testa sempre su testnet** prima del mainnet

### 🔐 Protezione Account

- ✅ Non condividere mai le tue API keys
- ✅ Non committare `.env` su Git
- ✅ Usa password forte per account Binance
- ✅ Abilita 2FA (Two-Factor Authentication)
- ✅ Monitora attività account regolarmente

