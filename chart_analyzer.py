"""
chart_analyzer.py - Analisa chart OHLCV dengan indikator teknikal
Indicators: RSI, Support/Resistance, Volume Profile, Candle Patterns
"""

import asyncio
import aiohttp
import json
import logging
import os
import time
from datetime import datetime

logger = logging.getLogger(__name__)

BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


async def get_ohlcv(mint: str, timeframe: str, limit: int, session: aiohttp.ClientSession) -> list:
    """Fetch OHLCV candles dari GeckoTerminal (gratis, no key)."""
    try:
        # Ambil pool address dari DexScreener
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return []
            pair_addr = pairs[0].get("pairAddress", "")
        
        # Fetch OHLCV dari GeckoTerminal
        tf_map = {"1m": "minute", "5m": "minute", "15m": "minute", "1H": "hour", "4H": "hour"}
        agg_map = {"1m": 1, "5m": 5, "15m": 15, "1H": 1, "4H": 4}
        tf = tf_map.get(timeframe, "minute")
        agg = agg_map.get(timeframe, 1)
        async with session.get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pair_addr}/ohlcv/{tf}",
            params={"aggregate": agg, "limit": limit},
            headers={"Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
            candles = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            if not candles:
                return []
            result = []
            for c in candles:
                result.append({
                    "unixTime": c[0],
                    "o": float(c[1]),
                    "h": float(c[2]),
                    "l": float(c[3]),
                    "c": float(c[4]),
                    "v": float(c[5]),
                })
            return result
        
    except Exception as e:
        logger.error(f"OHLCV fetch error: {e}")
        return []


def _tf_to_seconds(tf: str) -> int:
    mapping = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1H": 3600, "4H": 14400}
    return mapping.get(tf, 60)


def calc_rsi(closes: list, period: int = 14) -> float:
    """Calculate RSI."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def calc_support_resistance(candles: list) -> dict:
    """Hitung support & resistance dari recent candles."""
    if not candles:
        return {}
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    closes = [c["c"] for c in candles]
    
    current = closes[-1]
    resistance = max(highs[-20:]) if len(highs) >= 20 else max(highs)
    support = min(lows[-20:]) if len(lows) >= 20 else min(lows)
    
    # Mid levels
    mid_resistance = (current + resistance) / 2
    mid_support = (current + support) / 2
    
    dist_to_resistance = (resistance - current) / current * 100
    dist_to_support = (current - support) / current * 100
    
    return {
        "resistance": resistance,
        "support": support,
        "mid_resistance": mid_resistance,
        "mid_support": mid_support,
        "dist_to_resistance_pct": round(dist_to_resistance, 1),
        "dist_to_support_pct": round(dist_to_support, 1),
        "current": current,
    }


def calc_volume_profile(candles: list) -> dict:
    """Volume analysis — apakah volume mendukung price action."""
    if len(candles) < 5:
        return {}
    
    volumes = [c["v"] for c in candles]
    avg_vol = sum(volumes) / len(volumes)
    recent_vol = sum(volumes[-5:]) / 5
    vol_trend = "INCREASING" if recent_vol > avg_vol else "DECREASING"
    
    # Volume pada candle naik vs turun
    up_vol = sum(c["v"] for c in candles if c["c"] > c["o"])
    down_vol = sum(c["v"] for c in candles if c["c"] <= c["o"])
    total_vol = up_vol + down_vol
    buy_vol_pct = (up_vol / total_vol * 100) if total_vol > 0 else 50
    
    return {
        "avg_volume": avg_vol,
        "recent_volume": recent_vol,
        "volume_trend": vol_trend,
        "buy_volume_pct": round(buy_vol_pct, 1),
        "volume_ratio": round(recent_vol / avg_vol, 2) if avg_vol > 0 else 1,
    }


def detect_candle_patterns(candles: list) -> list:
    """Detect basic candle patterns dari recent candles."""
    if len(candles) < 3:
        return []
    
    patterns = []
    last = candles[-1]
    prev = candles[-2]
    prev2 = candles[-3]
    
    body = abs(last["c"] - last["o"])
    wick_up = last["h"] - max(last["c"], last["o"])
    wick_down = min(last["c"], last["o"]) - last["l"]
    total_range = last["h"] - last["l"]
    
    if total_range == 0:
        return []
    
    body_pct = body / total_range
    
    # Doji
    if body_pct < 0.1:
        patterns.append("DOJI (indecision)")
    
    # Hammer / Shooting star
    if wick_down > body * 2 and wick_up < body * 0.5:
        patterns.append("HAMMER (bullish reversal)")
    if wick_up > body * 2 and wick_down < body * 0.5:
        patterns.append("SHOOTING STAR (bearish reversal)")
    
    # Engulfing
    if (last["c"] > last["o"] and prev["c"] < prev["o"] and
            last["c"] > prev["o"] and last["o"] < prev["c"]):
        patterns.append("BULLISH ENGULFING")
    if (last["c"] < last["o"] and prev["c"] > prev["o"] and
            last["c"] < prev["o"] and last["o"] > prev["c"]):
        patterns.append("BEARISH ENGULFING")
    
    # Strong momentum
    if last["c"] > last["o"] and body_pct > 0.7:
        patterns.append("STRONG BULLISH CANDLE")
    if last["c"] < last["o"] and body_pct > 0.7:
        patterns.append("STRONG BEARISH CANDLE")
    
    # 3 consecutive
    if all(c["c"] > c["o"] for c in [last, prev, prev2]):
        patterns.append("3 GREEN CANDLES (momentum up)")
    if all(c["c"] < c["o"] for c in [last, prev, prev2]):
        patterns.append("3 RED CANDLES (momentum down)")
    
    return patterns


def analyze_trend(candles: list) -> dict:
    """Analisa trend dari candles."""
    if len(candles) < 10:
        return {"trend": "UNKNOWN", "strength": 0}
    
    closes = [c["c"] for c in candles]
    
    # Simple trend: bandingkan MA pendek vs MA panjang
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else sum(closes) / len(closes)
    
    # Higher highs / lower lows
    recent_high = max(c["h"] for c in candles[-10:])
    recent_low = min(c["l"] for c in candles[-10:])
    prev_high = max(c["h"] for c in candles[-20:-10]) if len(candles) >= 20 else recent_high
    prev_low = min(c["l"] for c in candles[-20:-10]) if len(candles) >= 20 else recent_low
    
    if ma5 > ma20 and recent_high > prev_high:
        trend = "UPTREND"
        strength = min(((ma5 - ma20) / ma20 * 100), 100)
    elif ma5 < ma20 and recent_low < prev_low:
        trend = "DOWNTREND"
        strength = min(((ma20 - ma5) / ma20 * 100), 100)
    else:
        trend = "SIDEWAYS"
        strength = 0
    
    return {
        "trend": trend,
        "strength": round(strength, 1),
        "ma5": ma5,
        "ma20": ma20,
        "price_vs_ma5": round((closes[-1] - ma5) / ma5 * 100, 1),
        "price_vs_ma20": round((closes[-1] - ma20) / ma20 * 100, 1),
    }


async def full_chart_analysis(mint: str, symbol: str = "") -> dict:
    """Full chart analysis semua timeframe."""
    async with aiohttp.ClientSession() as session:
        # Fetch semua timeframe
        candles_1m, candles_5m, candles_1h = await asyncio.gather(
            get_ohlcv(mint, "1m", 60, session),
            get_ohlcv(mint, "5m", 60, session),
            get_ohlcv(mint, "1H", 48, session),
        )
    
    result = {"symbol": symbol, "mint": mint, "timeframes": {}}
    
    for tf, candles in [("1m", candles_1m), ("5m", candles_5m), ("1H", candles_1h)]:
        if not candles:
            continue
        closes = [c["c"] for c in candles]
        result["timeframes"][tf] = {
            "candle_count": len(candles),
            "rsi": calc_rsi(closes),
            "support_resistance": calc_support_resistance(candles),
            "volume_profile": calc_volume_profile(candles),
            "patterns": detect_candle_patterns(candles),
            "trend": analyze_trend(candles),
            "current_price": closes[-1] if closes else 0,
            "price_change_pct": round((closes[-1] - closes[0]) / closes[0] * 100, 2) if closes[0] > 0 else 0,
        }
    
    return result


async def ai_chart_verdict(analysis: dict, context: str = "entry") -> str:
    """Minta AI kasih verdict chart berdasarkan analisa teknikal."""
    
    tf_summaries = []
    for tf, data in analysis.get("timeframes", {}).items():
        sr = data.get("support_resistance", {})
        vp = data.get("volume_profile", {})
        trend = data.get("trend", {})
        tf_summaries.append(f"""
{tf} ({data.get('candle_count')} candles):
- Trend: {trend.get('trend')} (strength: {trend.get('strength')}%)
- RSI: {data.get('rsi')} {'(OVERBOUGHT)' if data.get('rsi', 50) > 70 else '(OVERSOLD)' if data.get('rsi', 50) < 30 else '(NEUTRAL)'}
- Price vs MA5: {trend.get('price_vs_ma5')}% | Price vs MA20: {trend.get('price_vs_ma20')}%
- Support: ${sr.get('support', 0):.8f} ({sr.get('dist_to_support_pct')}% away)
- Resistance: ${sr.get('resistance', 0):.8f} ({sr.get('dist_to_resistance_pct')}% away)
- Volume trend: {vp.get('volume_trend')} | Buy vol: {vp.get('buy_volume_pct')}% | Vol ratio: {vp.get('volume_ratio')}x
- Patterns: {', '.join(data.get('patterns', [])) or 'None detected'}""")
    
    if not tf_summaries:
        return "❌ Tidak cukup data chart untuk analisa."
    
    prompt = f"""Kamu adalah technical analyst expert untuk crypto/meme token Solana.
Analisa chart token {analysis.get('symbol', 'UNKNOWN')} dan berikan trading verdict.

CHART DATA:
{''.join(tf_summaries)}

CONTEXT: User mau {'ENTRY (beli)' if context == 'entry' else 'EXIT (jual)' if context == 'exit' else 'ENTRY & EXIT'}

Berikan analisa teknikal dalam bahasa Indonesia casual, format:

📊 CHART VERDICT: [BUY / SELL / WAIT / HOLD]
🎯 CONFIDENCE: [HIGH/MEDIUM/LOW]

📈 TREND ANALYSIS:
[Analisa trend multi-timeframe, apakah aligned atau conflicting]

⚡ MOMENTUM:
[RSI status, volume analysis, apakah ada divergence]

🎯 KEY LEVELS:
- Support kuat: $X
- Resistance kuat: $X  
- Entry ideal: $X
- Stop loss: $X
- Take profit 1: $X
- Take profit 2: $X

🕯️ CANDLE SIGNALS:
[Pattern yang terdeteksi + interpretasi]

💡 KESIMPULAN:
[Max 3 kalimat, actionable advice]"""

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": "mistralai/mistral-small-3.1-24b-instruct", "max_tokens": 700,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                data = await r.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI verdict error: {e}"


async def chart_report(mint: str, symbol: str = "", context: str = "both") -> str:
    """Full chart report untuk dikirim ke Telegram."""
    analysis = await full_chart_analysis(mint, symbol)
    
    if not analysis.get("timeframes"):
        return f"❌ Tidak ada data chart untuk {symbol or mint[:16]}... (token mungkin terlalu baru)"
    
    verdict = await ai_chart_verdict(analysis, context)
    
    # Summary header
    tf_data = analysis.get("timeframes", {})
    primary_tf = "1m" if "1m" in tf_data else list(tf_data.keys())[0]
    primary = tf_data.get(primary_tf, {})
    
    report = f"""📊 <b>CHART ANALYSIS — {symbol or 'UNKNOWN'}</b>
💰 Price: ${primary.get('current_price', 0):.8f}
📈 Change ({primary_tf}): {primary.get('price_change_pct', 0):+.1f}%

{verdict}

🔗 https://dexscreener.com/solana/{mint}"""
    
    return report


if __name__ == "__main__":
    import sys
    mint = sys.argv[1] if len(sys.argv) > 1 else "9WpkZ5dr6RNJDxaLD4535ssRg6vNcnhZMj2LzAQa8AmP"
    symbol = sys.argv[2] if len(sys.argv) > 2 else "Grokputer"
    
    async def main():
        report = await chart_report(mint, symbol)
        print(report)
    
    asyncio.run(main())
