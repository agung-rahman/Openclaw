"""
daily_briefing.py - Kirim daily briefing jam 12 WIB (05:00 UTC)
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

BRIEFING_HOUR_UTC = 5  # 12 WIB = 05:00 UTC


async def get_sol_price() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.dexscreener.com/latest/dex/search?q=SOL+USDC",
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                data = await resp.json()
                pairs = data.get("pairs", [])
                for p in pairs:
                    if p.get("baseToken", {}).get("symbol") == "SOL":
                        return float(p.get("priceUsd", 0))
    except:
        pass
    return 0.0


async def get_market_sentiment() -> str:
    """Ambil top trending tokens buat gauge market."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://public-api.birdeye.so/defi/token_trending?sort_by=rank&sort_type=asc&limit=5&chain=solana",
                headers={"X-API-KEY": os.getenv("BIRDEYE_API_KEY", ""), "X-Chain": "solana"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                data = await resp.json()
                tokens = data.get("data", {}).get("tokens", [])
                trending = []
                for t in tokens[:5]:
                    change = t.get("price24hChangePercent", 0)
                    trending.append(f"{t.get('symbol')} {change:+.1f}%")
                return ", ".join(trending)
    except:
        return "Data tidak tersedia"


async def generate_briefing(positions: dict, pnl: dict, sol_price: float, trending: str) -> str:
    """Generate briefing pake AI."""
    try:
        context = f"""
Buat daily briefing singkat untuk trader crypto Solana. 
Data hari ini:
- SOL price: ${sol_price:.2f}
- Open positions: {len(positions)} posisi
- PnL 7 hari: ${pnl['pnl_usd']:.2f} ({pnl['pnl_pct']:.1f}%)
- Win rate: {pnl['win_rate']:.0f}% ({pnl['wins']}W/{pnl['losses']}L)
- Trending tokens: {trending}

Buat briefing dalam bahasa Indonesia yang casual, singkat (max 150 kata), dan helpful. 
Include: kondisi market, performa bot, dan 1-2 tips hari ini.
"""
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": "google/gemini-2.0-flash-exp:free",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": context}]
            }
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Briefing error: {e}"


async def send_daily_briefing():
    """Generate dan kirim daily briefing."""
    from ai_assistant import get_pnl_summary, load_positions
    from risk_manager import get_risk_status
    
    positions = load_positions()
    pnl = get_pnl_summary(7)
    sol_price = await get_sol_price()
    trending = await get_market_sentiment()
    
    ai_briefing = await generate_briefing(positions, pnl, sol_price, trending)
    
    # Format positions
    pos_text = ""
    if positions:
        for mint, pos in list(positions.items())[:3]:
            sym = pos.get("token_symbol", "?")
            invested = pos.get("amount_invested_usd", 0)
            pos_text += f"  • {sym}: ${invested:.2f}\n"
    else:
        pos_text = "  Tidak ada posisi open\n"
    
    msg = (
        f"☀️ Daily Briefing - {datetime.now().strftime('%d %b %Y')}\n\n"
        f"💰 SOL: ${sol_price:.2f}\n\n"
        f"📊 Open Positions:\n{pos_text}\n"
        f"📈 PnL 7 hari: {'+' if pnl['pnl_usd'] >= 0 else ''}${pnl['pnl_usd']:.2f} ({pnl['pnl_pct']:+.1f}%)\n"
        f"🎯 Win rate: {pnl['win_rate']:.0f}% ({pnl['wins']}W/{pnl['losses']}L)\n\n"
        f"🤖 AI Briefing:\n{ai_briefing}"
    )
    
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": True}
        )
    
    logger.info("Daily briefing sent!")


async def briefing_scheduler():
    """Loop yang jalanin briefing tiap hari jam 12 WIB."""
    logger.info(f"Daily briefing scheduler started (jam 12 WIB)")
    last_sent_date = None
    
    while True:
        now = datetime.utcnow()
        if now.hour == BRIEFING_HOUR_UTC and now.date() != last_sent_date:
            logger.info("Sending daily briefing...")
            try:
                await send_daily_briefing()
                last_sent_date = now.date()
            except Exception as e:
                logger.error(f"Briefing error: {e}")
        
        await asyncio.sleep(60)  # Cek tiap menit
