# Crypto Trading Bot

Bot per trading automatico su criptovalute con strategia basata su Z-score, mean reversion e dati on-chain.

## Caratteristiche

- **🔄 Trading Multi-Coppia**: Gestisce 2-3+ coppie simultaneamente per diversificazione
- **📊 Strategia avanzata**: Z-score + mean reversion + integrazione dati on-chain
- **💼 Modalità DEX**: Trading con wallet privato (non serve Binance!)
- **🏦 Modalità CEX**: Trading su Binance (fee molto più basse per trade piccoli!)
- **🔗 Dati on-chain**: Integrazione Alchemy per gas price, network activity
- **🧪 Wallet di Test**: Script per creare wallet testnet per test sicuri
- **⚙️ Configurazione semplice**: File `.env` personalizzabile
- **📝 Struttura pulita**: Codice modulare e non verboso

## ⚠️ IMPORTANTE: Fee DEX vs CEX

**Le fee DEX (Ethereum mainnet) sono FISSE, non percentuali!**
- DEX: ~$12-18 per ogni swap (indipendentemente dal valore)
- CEX: 0.1% del valore del trade

**Per trade piccoli (<$1000), usa CEX!** Vedere [FEE_EXPLANATION.md](FEE_EXPLANATION.md) per dettagli.

## Installazione

1. Crea ambiente virtuale:
```bash
python3 -m venv venv
source venv/bin/activate  # Su Windows: venv\Scripts\activate
```

2. Installa dipendenze:
```bash
pip install -r requirements.txt
```

3. Crea il tuo wallet:

**Per test (testnet):**
```bash
python create_test_wallet.py
```
Ottieni ETH gratuiti su https://sepoliafaucet.com/

**Per produzione (mainnet):**
```bash
python create_wallet.py
```

⚠️ Salva PRIVATE_KEY e WALLET_ADDRESS in un posto sicuro!

4. Configura `.env`:
```bash
cp .env.example .env
# Modifica .env con le tue credenziali
```

## Configurazione

### Modalità DEX (Wallet Privato) - Consigliata

- `TRADING_MODE=DEX`
- `ALCHEMY_API_KEY`: La tua chiave Alchemy (già configurata)
- `PRIVATE_KEY`: La tua chiave privata (senza 0x)
- `WALLET_ADDRESS`: Il tuo indirizzo wallet
- `NETWORK`: mainnet, sepolia, etc.

### Modalità CEX (Binance) - Opzionale

- `TRADING_MODE=CEX`
- `BINANCE_API_KEY`: La tua API key di Binance
- `BINANCE_API_SECRET`: La tua API secret

### Parametri Trading - MULTI-COPPIA 🆕

**Trading su più coppie simultaneamente:**

- **`SYMBOLS`** ⭐ (IMPORTANTE): Liste coppie separate da virgola (es: `BTCUSDT,ETHUSDT,BNBUSDT`)
  - **Usa sempre SYMBOLS per multi-coppia!**
  - `SYMBOL` è solo legacy (singola coppia), usato se SYMBOLS è vuoto
- `QUANTITY_PER_PAIR`: Quantità per ogni coppia, separato da virgola (es: `0.001,0.001,0.001`)
- `QUANTITY`: Quantità di default se `QUANTITY_PER_PAIR` non specificato

**Esempio configurazione 3 coppie:**
```env
SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT
QUANTITY_PER_PAIR=0.001,0.002,0.001
```

**Altri parametri:**
- **`TIMEFRAME`**: Intervallo delle **candele OHLC** (non è l'intervallo tra cicli!)
  - Valori supportati da Binance: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w`, `1M`
  - ⚠️ **NON** puoi usare "10s" o "10h" - solo i valori sopra!
  - `5m` = candele da 5 minuti (il bot analizza candele OHLC ogni 5 minuti)
  - `1h` = candele da 1 ora
  - `1d` = candele giornaliere
- **`CYCLE_INTERVAL`**: Intervallo tra cicli di trading in secondi (default: 30)
  - Questo è quanto il bot attende tra un'analisi e l'altra
  - `30` = il bot analizza ogni 30 secondi
  - `60` = il bot analizza ogni minuto
- `USE_TESTNET`: true/false per usare testnet
- `Z_SCORE_THRESHOLD`: Soglia Z-score per segnali (default: 2.0)
- `LOOKBACK_PERIOD`: Periodo per calcolo statistiche (default: 20)
- `MA_PERIOD`: Periodo media mobile (default: 10)

**Differenza tra TIMEFRAME e CYCLE_INTERVAL:**
- `TIMEFRAME=5m`: Il bot analizza candele OHLC da 5 minuti (dati storici)
- `CYCLE_INTERVAL=30`: Il bot esegue analisi ogni 30 secondi (frequenza esecuzione)

## Strategia

La strategia utilizza:

### Indicatori Tecnici
- **Z-score**: Identifica quando il prezzo devia significativamente dalla media
- **Mean Reversion**: Compra quando oversold, vende quando overbought
- **Momentum filter**: Filtra segnali con momentum negativo

### Dati On-Chain (Alchemy)
- **Gas Price Trend**: Aumento gas = più attività = boost bullish
- **Network Utilization**: Alta utilizzo = alta attività = boost bullish
- **Transaction Activity**: Volume transazioni per blocco

La strategia **combina** indicatori tecnici con dati on-chain per decisioni più informate.

## Uso

### Modalità Normale (Trading Reale)
```bash
python bot.py
```

### Modalità Simulazione (Senza ETH) 🎮
**Perfetta per testare senza wallet o ETH!**
```bash
python bot.py --simulate
```

Oppure:
```bash
python simulation_mode.py
```

**Vantaggi simulazione:**
- ✅ Nessun ETH necessario
- ✅ Test immediato e sicuro
- ✅ Prezzi reali da CoinGecko
- ✅ Simula trading realistico

## Avvertenze

- **Usa sempre testnet prima di operare con soldi reali**
- Configura `USE_TESTNET=true` nel `.env`
- Il bot esegue ordini reali - usa con cautela
- Testa accuratamente prima di usare capitale reale

## Struttura

```
crypto_bot/
├── bot.py           # Bot principale
├── strategy.py      # Logica strategia (con dati on-chain)
├── api_client.py    # Client API (Binance, DEX, Alchemy)
├── config.py        # Gestione configurazione
├── create_wallet.py # Script per creare wallet
├── requirements.txt
├── .env.example
└── README.md
```

## Creare Wallet

### Wallet di Test (Testnet) 🧪

Per testare il bot senza rischi:
```bash
python create_test_wallet.py
```

Poi:
1. Ottieni ETH gratuiti su [Sepolia Faucet](https://sepoliafaucet.com/)
2. Configura `.env` con `NETWORK=sepolia` e `USE_TESTNET=true`

### Wallet di Produzione

Per trading reale:
```bash
python create_wallet.py
```

**⚠️ IMPORTANTE**: 
- Salva la chiave privata in un posto SICURO
- NON condividere mai la chiave privata
- Chiunque abbia la chiave può controllare i fondi
- Testa sempre su testnet prima!

## Trading Multi-Coppia

Il bot ora supporta trading simultaneo su più coppie per diversificazione:

**Vantaggi:**
- 📈 Diversificazione del rischio
- 🔄 Maggiore attività e opportunità
- 📊 Tracking separato per ogni coppia
- 💰 PnL individuale per posizione

**Esempio output:**
```
[16:30:45] 🔄 Ciclo trading per 3 coppie
   [BTCUSDT] $45000.00 | Z: -1.2 | HOLD (45%) | Pos: NONE
   [ETHUSDT] $2800.00 | Z: 2.3 | SELL (78%) | Pos: LONG | 📈 +2.5%
   [BNBUSDT] $320.00 | Z: -2.1 | BUY (85%) | Pos: NONE

   📊 Posizioni attive (1/3):
      ETHUSDT: Entry $2750.00 | Current $2800.00 | 📈 +1.82%
```

## Capire l'Output

Vuoi sapere cosa significano i valori nell'output? Leggi la [Guida Output](OUTPUT_GUIDE.md) per spiegazioni dettagliate!

## 📊 Reportistica

Il bot genera automaticamente reportistica dettagliata:

### Report Periodici (Durante Esecuzione)
- Generati ogni N cicli (configurabile con `REPORT_INTERVAL`)
- Mostra: Balance, posizioni attive, PnL, statistiche sessione
- Visualizzazione chiara del portafoglio corrente

### Report Finale (Fine Sessione)
- Generato quando il bot viene fermato (Ctrl+C)
- Include: Statistiche complete, win rate, PnL totale, ultime operazioni
- Salvato in formato JSON e CSV nella cartella `reports/`

### File Generati
- `reports/session_YYYYMMDD_HHMMSS.json`: Report completo JSON
- `reports/trades_YYYYMMDD_HHMMSS.csv`: Log tutte le operazioni in CSV

**Configurazione:**
```env
REPORT_INTERVAL=10  # Report ogni 10 cicli (default: 10)
```

**Esempio Report Periodico:**
```
======================================================================
📊 REPORT PORTAFOGLIO
======================================================================

💰 Balance Totale: 1.002000 ETH

📈 Posizioni Attive (2/3):
   BTCUSDT      | Entry: $  65000.00 | Current: $  65100.00 | 📈  +0.15%
   ETHUSDT      | Entry: $   2800.00 | Current: $   2750.00 | 📉  -1.79%

   💵 PnL Totale Portafoglio: -1.64%

📈 Statistiche Sessione:
   Totale Trade: 8
   BUY: 4 | SELL: 4
   Win Rate: 50.0% (2W / 2L)
   PnL Totale: +0.5%
======================================================================
```

