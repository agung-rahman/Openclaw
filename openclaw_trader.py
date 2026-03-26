"""
openclaw_trader.py - Integrasi lengkap: Scanner → AI Analysis → Auto Trade
Sambungkan ke degen_hunter.py yang udah ada

Usage:
    python3 openclaw_trader.py

Environment variables yang dibutuhkan:
    TELEGRAM_BOT_TOKEN   - Token bot Telegram untuk notifikasi
    TELEGRAM_CHAT_ID     - Chat ID lo (dapatkan dari @userinfobot)
    OPENROUTER_API_KEY   - API key OpenRouter
    HELIUS_API_KEY       - API key Helius (sudah ada dari degen_hunter)
"""

import asyncio
import aiohttp
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

from wallet_manager import get_keypair, get_public_key, WALLET_FILE
from trade_executor import TradeExecutor, TRADE_AMOUNT_USD
from position_monitor import PositionMonitor, MAX_OPEN_POSITIONS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/root/openclaw_trader.log"),
    ]
)
logger = logging.getLogger("openclaw_trader")

# ── Config ────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
HELIUS_RPC_URL     = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"

# AI scoring threshold — token harus dapat skor >= ini untuk dibeli
MIN_AI_SCORE = 6  # skala 1–10

# Max open positions
MAX_OPEN_POSITIONS = 3

# ── Telegram ──────────────────────────────────────────────────────────────────
async def send_telegram(message: str):
    """Kirim notifikasi ke Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping notification")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.error(f"Telegram error: {await resp.text()}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")


# ── AI Analysis ───────────────────────────────────────────────────────────────
async def analyze_token_with_ai(token_data: dict) -> Optional[dict]:
    if not OPENROUTER_API_KEY:
        return None

    from narrative_manager import get_full_narrative_context
    try:
        narrative_context = await get_full_narrative_context(
            token_data.get("symbol", ""),
            token_data.get("symbol", ""),
            token_data.get("mint", "")
        )
    except Exception as e:
        logger.warning(f"Narrative context failed: {e}")
        narrative_context = "NARRATIVE: Context unavailable"

    age_days = token_data.get("age_days", 999)
    is_new_pair = age_days < 0.5  # Token < 12 jam

    if is_new_pair:
        prompt = f"""You are an aggressive degen Solana trader AI for NEW token launches.
Token age: {age_days*24:.1f} hours. Use NEW PAIR momentum scoring.

TOKEN DATA:
{json.dumps(token_data, indent=2)}

NEW PAIR RULES - Ignore narrative, focus on momentum:
- Spike > 5x + buy ratio > 60% + price not dumping = score 8-10
- Spike > 3x + buy ratio > 55% = score 6-7
- Spike > 1.5x but price unclear = score 4-5
- Dumping hard or spike < 1.5x = score 1-3

INSTANT REJECT: Price 1h < -30%, buy ratio < 40%, bundle > 30%

Respond ONLY valid JSON:
{{"score": <1-10>, "verdict": "<BUY or NO_BUY>", "should_buy": <true/false>, "reasoning": "<focus on momentum>", "risk_level": "<LOW|MEDIUM|HIGH>", "narrative_fit": "NEW_PAIR"}}"""
    else:
            prompt = f"""You are a degen Solana trader AI. Analyze this token signal and give a BUY/NO BUY verdict.

TOKEN DATA:
{json.dumps(token_data, indent=2)}

NARRATIVE CONTEXT:
{narrative_context}

Analyze these factors:
1. Volume spike genuine or wash trading?
2. Buy ratio meaningful (>55%)?
3. Price action: dumping or recovering?
4. Market cap under $500k?
5. Rugcheck clean?
6. NARRATIVE FIT: Does token name/theme match hot narratives?
   - Strong narrative match = higher conviction
   - No narrative = need stronger technicals
   - Bearish Twitter = extra caution

STRICT FILTERS (instant reject):
- Rugcheck > 200, Mint/Freeze enabled, Bundle > 30%
- Price 1h < -20%, MC > $1M, Spike < 0.3x
- Bearish Twitter + no narrative = reject

SCORING:
- 8-10: Strong narrative + good technicals
- 6-7: Decent technicals, weak narrative
- 4-5: Weak narrative + mediocre technicals
- 1-3: No narrative, bad technicals

Respond ONLY with valid JSON:
{{
  "score": <1-10>,
  "verdict": "<BUY or NO_BUY>",
  "should_buy": <true or false>,
  "reasoning": "<2-3 sentences, mention narrative fit>",
  "risk_level": "<LOW|MEDIUM|HIGH>",
  "narrative_fit": "<STRONG|WEAK|NONE>"
}}"""

    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "model": "anthropic/claude-3-haiku",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    logger.error(f"OpenRouter error: {await resp.text()}")
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                content = re.sub(r"```json|```", "", content).strip()
                result = json.loads(content)
                return result
    except json.JSONDecodeError as e:
        logger.error(f"AI response parse error: {e}")
        return None
    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        return None

async def check_rugcheck(token_mint: str) -> Optional[dict]:
    """Cek rugcheck score dari rugcheck.xyz API."""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_mint}/report/summary"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        logger.error(f"Rugcheck API error: {e}")
    return None


# ── Main Token Handler ────────────────────────────────────────────────────────
class OpenClawTrader:
    def __init__(self):
        if not WALLET_FILE.exists():
            raise RuntimeError(
                "Wallet belum di-generate!\n"
                "Jalankan dulu: python3 wallet_manager.py --generate"
            )

        self.keypair = get_keypair()
        self.executor = TradeExecutor(self.keypair, rpc_url=HELIUS_RPC_URL)
        self.monitor = PositionMonitor(
            executor=self.executor,
            notify_callback=send_telegram
        )
        self.processed_tokens = set()  # hindari proses token sama 2x


    async def ai_analyze(self, token_data: dict, narrative_context: str = "") -> dict:
        """Public method untuk manual analyze token."""
        return await analyze_token_with_ai(token_data)

    async def handle_token_signal(self, token_data: dict):
        """
        Handler utama saat degen_hunter menemukan token candidate.
        
        token_data expected format:
        {
            "mint": "...",
            "symbol": "TOKEN",
            "dex": "pumpswap",
            "age_days": 2.0,
            "liquidity": 32504,
            "market_cap": 142280,
            "volume_spike": 0.67,
            "price_1h": -14.11,
            "price_6h": 1.97,
            "price_24h": 12.24,
            "buy_ratio": 59.7,
            "txns_1h_buys": 37,
            "txns_1h_sells": 25,
            "rugcheck_score": 1,
            "mint_enabled": False,
            "freeze_enabled": False,
            "bundle_pct": 0,
        }
        """
        token_mint = token_data.get("mint")
        symbol = token_data.get("symbol", "UNKNOWN")

        # Skip kalau udah diproses
        if token_mint in self.processed_tokens:
            return
        self.processed_tokens.add(token_mint)

        # Skip kalau udah max positions
        if self.monitor.get_open_count() >= MAX_OPEN_POSITIONS:
            logger.info(f"⛔ Max positions reached ({MAX_OPEN_POSITIONS}), skipping {symbol}")
            return

        logger.info(f"\n{'='*50}")
        logger.info(f"🔍 Analyzing {symbol} ({token_mint})")

        # ── Hard filters dulu (tanpa AI, hemat biaya) ──
        if not self._pass_hard_filters(token_data, symbol):
            return

        # ── AI Analysis ──
        logger.info(f"🤖 Running AI analysis for {symbol}...")
        ai_result = await analyze_token_with_ai(token_data)

        if not ai_result:
            logger.warning(f"AI analysis failed for {symbol}, skipping")
            return

        score = ai_result.get("score", 0)
        should_buy = ai_result.get("should_buy", False)
        verdict = ai_result.get("verdict", "NO_BUY")
        reasoning = ai_result.get("reasoning", "")
        risk = ai_result.get("risk_level", "HIGH")

        logger.info(f"   AI Score: {score}/10 | Verdict: {verdict} | Risk: {risk}")
        logger.info(f"   Reasoning: {reasoning}")

        # Kirim analisis ke Telegram (info, bukan aksi)
        emoji = "🟡" if score >= MIN_AI_SCORE else "⚪"
        await send_telegram(
            f"{emoji} **AI SIGNAL: {symbol}**\n"
            f"Score: {score}/10 | {verdict} | Risk: {risk}\n"
            f"MC: ${token_data.get('market_cap', 0):,.0f} | "
            f"Spike: {token_data.get('volume_spike', 0):.2f}x | "
            f"Buy ratio: {token_data.get('buy_ratio', 0):.0f}%\n"
            f"Price 1h: {token_data.get('price_1h', 0):+.1f}% | "
            f"6h: {token_data.get('price_6h', 0):+.1f}%\n"
            f"💭 {reasoning}"
        )

        # ── Execute buy kalau lolos ──
        if should_buy and score >= MIN_AI_SCORE:
            logger.info(f"✅ {symbol} APPROVED for trading (score: {score})")
            await self._execute_buy(token_data, ai_result)
        else:
            logger.info(f"❌ {symbol} rejected (score: {score}, verdict: {verdict})")
        from token_blacklist import add_to_blacklist
        add_to_blacklist(token_mint, f"AI reject score={score}")

    def _pass_hard_filters(self, token_data: dict, symbol: str) -> bool:
        """Hard filters — instant reject tanpa AI."""
        reasons = []

        if token_data.get("mint_enabled", True):
            reasons.append("Mint enabled")
        if token_data.get("freeze_enabled", True):
            reasons.append("Freeze enabled")
        if token_data.get("rugcheck_score", 9999) > 600:
            reasons.append(f"High rugcheck: {token_data.get('rugcheck_score')}")
        if token_data.get("bundle_pct", 100) > 30:
            reasons.append(f"High bundle: {token_data.get('bundle_pct')}%")
        if token_data.get("price_1h", -99) < -20:
            reasons.append(f"Heavy dump 1h: {token_data.get('price_1h')}%")
        if token_data.get("market_cap", 9_999_999) > 1_000_000:
            reasons.append(f"MC too high: ${token_data.get('market_cap'):,}")
        if token_data.get("volume_spike", 0) < 0.3:
            reasons.append(f"Low spike: {token_data.get('volume_spike')}x")
        if token_data.get("liquidity", 0) < 5_000:
            reasons.append(f"Low liquidity: ${token_data.get('liquidity'):,}")

        if reasons:
            logger.info(f"⛔ {symbol} failed hard filters: {', '.join(reasons)}")
            return False

        logger.info(f"✅ {symbol} passed hard filters")
        return True

    async def _execute_buy(self, token_data: dict, ai_result: dict):
        """Eksekusi buy dan tambah ke position monitor."""
        symbol = token_data["symbol"]
        mint = token_data["mint"]

        try:
            position = await self.executor.buy_token(mint, symbol)
            if position:
                await self.monitor.add_position(position)
                logger.info(f"🎉 Successfully bought {symbol}!")
            else:
                logger.error(f"Buy execution failed for {symbol}")
                await send_telegram(f"❌ **BUY FAILED**: {symbol}\nCheck logs for details")
        except Exception as e:
            logger.error(f"Buy error for {symbol}: {e}", exc_info=True)
            await send_telegram(f"❌ **BUY ERROR**: {symbol}\n{str(e)[:100]}")

    async def start(self):
        """Start trader + monitor."""
        logger.info("🚀 OpenClaw Trader starting...")
        logger.info(f"   Wallet: {get_public_key()}")
        logger.info(f"   Trade size: ${TRADE_AMOUNT_USD}")
        logger.info(f"   Max positions: {MAX_OPEN_POSITIONS}")
        logger.info(f"   Min AI score: {MIN_AI_SCORE}/10")

        await send_telegram(
            f"🚀 **OpenClaw Trader STARTED**\n"
            f"Wallet: `{get_public_key()[:8]}...{get_public_key()[-8:]}`\n"
            f"Trade size: ${TRADE_AMOUNT_USD} per token\n"
            f"Max positions: {MAX_OPEN_POSITIONS}\n"
            f"TP1: 2x (sell 50%) | TP2: 3x (sell rest)\n"
            f"SL: -30%"
        )

        # Start position monitor di background
        monitor_task = asyncio.create_task(self.monitor.run())

        return monitor_task


# ── Integration hook untuk degen_hunter.py ───────────────────────────────────
# Tambahkan ini di degen_hunter.py:
#
# from openclaw_trader import OpenClawTrader
# trader = OpenClawTrader()
# await trader.start()
#
# Lalu di dalam fungsi yang handle token alerts:
# await trader.handle_token_signal(token_data)
#
# Format token_data harus sesuai docstring di handle_token_signal()

async def main():
    """Test mode - jalankan standalone."""
    trader = OpenClawTrader()
    monitor_task = await trader.start()

    # Simulasi token signal untuk testing
    test_token = {
        "mint": "ExampleMintAddress123",
        "symbol": "TEST",
        "dex": "pumpswap",
        "age_days": 2.0,
        "liquidity": 35000,
        "market_cap": 150000,
        "volume_spike": 1.5,
        "price_1h": -5.0,
        "price_6h": 8.0,
        "price_24h": 25.0,
        "buy_ratio": 65.0,
        "txns_1h_buys": 45,
        "txns_1h_sells": 20,
        "rugcheck_score": 5,
        "mint_enabled": False,
        "freeze_enabled": False,
        "bundle_pct": 0,
    }

    logger.info("Running test signal analysis (no real buy)...")
    # Dalam test mode, kita hanya analyze tanpa execute
    passed = trader._pass_hard_filters(test_token, "TEST")
    if passed:
        result = await analyze_token_with_ai(test_token)
        logger.info(f"AI Result: {json.dumps(result, indent=2)}")

    await monitor_task


if __name__ == "__main__":
    asyncio.run(main())
