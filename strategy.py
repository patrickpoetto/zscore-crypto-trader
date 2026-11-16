"""Strategia di trading basata su Z-score, mean reversion e dati on-chain."""
import pandas as pd
import numpy as np
from config import Config

class Strategy:
    """Strategia statisticamente avanzata ma concettualmente semplice."""
    
    def __init__(self, onchain_client=None):
        self.z_threshold = Config.Z_SCORE_THRESHOLD
        self.lookback = Config.LOOKBACK_PERIOD
        self.ma_period = Config.MA_PERIOD
        self.onchain_client = onchain_client
        self.onchain_history = []  # Storico dati on-chain
    
    def get_onchain_metrics(self):
        """Ottiene metriche on-chain da Alchemy."""
        if not self.onchain_client:
            return None
        
        try:
            gas_price = self.onchain_client.get_gas_price()
            network_activity = self.onchain_client.get_network_activity(blocks=5)
            
            metrics = {
                'gas_price': gas_price,
                'network_activity': network_activity
            }
            
            # Aggiungi allo storico
            self.onchain_history.append(metrics)
            if len(self.onchain_history) > 20:
                self.onchain_history.pop(0)
            
            return metrics
        except Exception as e:
            print(f"Errore recupero metriche on-chain: {e}")
            return None
    
    def calculate_indicators(self, df):
        """Calcola indicatori tecnici."""
        if len(df) < self.lookback:
            return None
        
        # Media mobile
        df['ma'] = df['close'].rolling(window=self.ma_period).mean()
        
        # Z-score basato su deviazione dalla media
        df['mean'] = df['close'].rolling(window=self.lookback).mean()
        df['std'] = df['close'].rolling(window=self.lookback).std()
        df['z_score'] = (df['close'] - df['mean']) / df['std']
        
        # Momentum
        df['momentum'] = df['close'].pct_change(periods=5)
        
        # Metriche on-chain (se disponibili)
        onchain = self.get_onchain_metrics()
        if onchain and len(self.onchain_history) > 1:
            # Gas price trend
            gas_prices = [m['gas_price'] for m in self.onchain_history if m.get('gas_price')]
            if len(gas_prices) >= 2:
                df.loc[df.index[-1], 'gas_price'] = gas_prices[-1]
                df.loc[df.index[-1], 'gas_trend'] = (gas_prices[-1] - gas_prices[-2]) / gas_prices[-2] if gas_prices[-2] > 0 else 0
            
            # Network activity
            if onchain.get('network_activity'):
                activity = onchain['network_activity']
                df.loc[df.index[-1], 'network_utilization'] = activity.get('gas_utilization', 0)
                df.loc[df.index[-1], 'tx_activity'] = activity.get('avg_transaction_count', 0)
        
        return df
    
    def get_signal(self, df):
        """Genera segnale di trading con integrazione on-chain."""
        if df is None or len(df) < 2:
            return 'HOLD'
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Segnale basato su Z-score (mean reversion)
        z_score = last['z_score']
        
        # Filtri on-chain
        onchain_boost = 0  # Bonus/penalità basato su dati on-chain
        
        if pd.notna(last.get('gas_trend')):
            # Gas price in aumento = più attività = possibilmente bullish
            if last['gas_trend'] > 0.1:  # Gas price aumentato >10%
                onchain_boost += 0.1
            elif last['gas_trend'] < -0.1:  # Gas price diminuito >10%
                onchain_boost -= 0.05
        
        if pd.notna(last.get('network_utilization')):
            # Alta utilizzo network = alta attività = bullish
            if last['network_utilization'] > 0.8:  # >80% utilizzo
                onchain_boost += 0.15
            elif last['network_utilization'] < 0.3:  # <30% utilizzo
                onchain_boost -= 0.1
        
        # Aggiusta threshold con boost on-chain
        effective_threshold = self.z_threshold * (1 - onchain_boost)
        
        # Condizioni per BUY (oversold) - Configurabili
        buy_condition = z_score < -effective_threshold
        
        if Config.USE_PREV_ZSCORE_FILTER:
            buy_condition = buy_condition and prev['z_score'] >= -effective_threshold
        
        if Config.USE_MA_FILTER:
            buy_condition = buy_condition and last['close'] > last['ma']
        
        # Condizioni per SELL (overbought) - Configurabili
        sell_condition = z_score > effective_threshold
        
        if Config.USE_PREV_ZSCORE_FILTER:
            sell_condition = sell_condition and prev['z_score'] <= effective_threshold
        
        if Config.USE_MOMENTUM_FILTER:
            sell_condition = sell_condition and last['momentum'] < 0
        
        if buy_condition:
            return 'BUY'
        elif sell_condition:
            return 'SELL'
        
        return 'HOLD'
    
    def get_confidence(self, df):
        """Calcola confidence del segnale (0-1)."""
        if df is None or len(df) < 2:
            return 0.0
        
        last = df.iloc[-1]
        z_score = abs(last['z_score'])
        
        # Confidence aumenta con Z-score estremo
        if z_score > self.z_threshold:
            confidence = min(1.0, (z_score - self.z_threshold) / self.z_threshold)
        else:
            confidence = 0.0
        
        return confidence

