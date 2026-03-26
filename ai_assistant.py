"""
ai_assistant.py - Natural language AI assistant untuk trading
Handle chat natural, intent detection, dan eksekusi command
"""

import asyncio
import aiohttp
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
POSITIONS_FILE = Path("/root/.openclaw_positions.json")
TRADE_HISTORY_FILE = Path("/root/.trade_history.json")
PENDING_APPROVAL_FILE = Path("/root/.pending_approval.json")

SYSTEM_PROMPT = """You are a crypto trading AI assistant for a Solana degen trader. 
You help manage their trading bot, analyze tokens, and answer questions.

You can understand Indonesian and English naturally.

When user sends a message, detect their INTENT and respond with JSON:
{
  "intent": "<one of: check_positions, check_balance, sell_token, sell_all, buy_token, pause_trading, resume_trading, check_pnl, analyze_token, market_info, general_chat, daily_briefing>",
  "params": {<relevant params>},
  "reply": "<friendly response in same language as user>",
  "needs_confirmation": <true/false>,
  "confirmation_msg": "<if needs_confirmation, what to confirm>"
}

Examples:
- "gimana posisi gw?" → intent: check_positions
- "jual semua" → intent: sell_all, needs_confirmation: true
- "beli PEPE" → intent: buy_token, needs_confirmation: true
- "stop dulu tradingnya" → intent: pause_trading
- "profit gw berapa?" → intent: check_pnl
- "!analyze <addr>" → intent: analyze_token, params: {address: "<addr>"}
- casual chat → intent: general_chat

Always be helpful, direct, and use crypto/degen slang naturally.
Respond ONLY with valid JSON."""


async def detect_intent(message: str, context: str = "") -> dict:
    """Detect user intent dari pesan natural language."""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": "google/gemini-2.0-flash-exp:free",
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Context: {context}\nMessage: {message}"}
                ]
            }
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                # Clean JSON
                content = re.sub(r'```json|```', '', content).strip()
                return json.loads(content)
    except Exception as e:
        logger.error(f"Intent detection error: {e}")
        return {
            "intent": "general_chat",
            "params": {},
            "reply": "Maaf gw ga ngerti, coba lagi?",
            "needs_confirmation": False
        }


def load_positions() -> dict:
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text())
    return {}


def load_trade_history() -> list:
    if TRADE_HISTORY_FILE.exists():
        return json.loads(TRADE_HISTORY_FILE.read_text())
    return []


def save_trade_history(history: list):
    TRADE_HISTORY_FILE.write_text(json.dumps(history, indent=2))


def add_trade_to_history(trade: dict):
    history = load_trade_history()
    history.append({
        **trade,
        "timestamp": datetime.now().isoformat()
    })
    save_trade_history(history)


def get_pnl_summary(days: int = 7) -> dict:
    """Hitung PnL summary."""
    history = load_trade_history()
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    
    total_invested = 0
    total_returned = 0
    wins = 0
    losses = 0
    
    for trade in history:
        try:
            ts = datetime.fromisoformat(trade["timestamp"])
            if ts < cutoff:
                continue
            invested = trade.get("amount_invested_usd", 0)
            returned = trade.get("amount_returned_usd", 0)
            total_invested += invested
            total_returned += returned
            if returned > invested:
                wins += 1
            else:
                losses += 1
        except:
            continue
    
    pnl = total_returned - total_invested
    pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0
    
    return {
        "total_invested": total_invested,
        "total_returned": total_returned,
        "pnl_usd": pnl,
        "pnl_pct": pnl_pct,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    }


def save_pending_approval(action: dict):
    """Simpan action yang menunggu approval."""
    PENDING_APPROVAL_FILE.write_text(json.dumps(action, indent=2))


def load_pending_approval() -> Optional[dict]:
    if PENDING_APPROVAL_FILE.exists():
        data = json.loads(PENDING_APPROVAL_FILE.read_text())
        # Expired setelah 5 menit
        ts = datetime.fromisoformat(data.get("timestamp", "2000-01-01"))
        if (datetime.now() - ts).seconds > 300:
            PENDING_APPROVAL_FILE.unlink()
            return None
        return data
    return None


def clear_pending_approval():
    if PENDING_APPROVAL_FILE.exists():
        PENDING_APPROVAL_FILE.unlink()
