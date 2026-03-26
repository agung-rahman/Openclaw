"""
copy_trader.py - Copy trade dari smart money wallets
Monitor wallet via Helius websocket, ikut buy kalau mereka buy new pairs
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
HELIUS_WS_URL = f"wss://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

WATCHED_WALLETS = {
    "9tY7u1HgEt2RDcxym3RJ9sfvT3aZStiiUwXd44X9RUr8": "@solanadegen",
    "ACTbvbNm5qTLuofNRPxFPMtHAAtdH1CtzhCZatYHy831": "@jason",
}

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MAX_COPY_POSITIONS = 2      # Max posisi dari copy trade
MAX_TOKEN_AGE_HOURS = 24    # Hanya ikut buy token < 24 jam
MIN_BUY_USD = 50            # Min buy smart money biar dianggap serius ($50)
COPY_TRADE_SIZE_USD = 3.0   # Ukuran copy trade kita


class CopyTrader:
    def __init__(self, trader=None, notify_callback=None):
        self.trader = trader
        self.notify = notify_callback
        self.copy_positions = {}  # mint → wallet
        self.recent_copies = set()  # mint yang udah di-copy (hindari double)
        self.running = False

    async def get_token_age_hours(self, mint: str) -> Optional[float]:
        """Cek umur token dari DexScreener."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if not pairs:
                        return None
                    created_at = pairs[0].get("pairCreatedAt", 0)
                    if not created_at:
                        return None
                    age_hours = (datetime.now().timestamp() - created_at / 1000) / 3600
                    return age_hours
        except Exception as e:
            logger.debug(f"Get token age error: {e}")
            return None

    async def parse_transaction(self, tx_sig: str, wallet: str) -> Optional[dict]:
        """Parse transaksi untuk detect buy token."""
        try:
            async with aiohttp.ClientSession() as session:
                # Pake Helius enhanced API untuk parse transaksi
                url = f"https://api.helius.xyz/v0/transactions/?api-key={HELIUS_API_KEY}"
                payload = {"transactions": [tx_sig]}
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if not data:
                        return None

                    tx = data[0]
                    tx_type = tx.get("type", "")
                    
                    # Cari swap events
                    events = tx.get("events", {})
                    swap = events.get("swap", {})
                    
                    if not swap:
                        return None

                    token_inputs = swap.get("tokenInputs", [])
                    token_outputs = swap.get("tokenOutputs", [])
                    native_input = swap.get("nativeInput", {})

                    # Detect: SOL → Token (buy)
                    bought_mint = None
                    buy_amount_usd = 0

                    if native_input and token_outputs:
                        # SOL in, token out = BUY
                        sol_amount = native_input.get("amount", 0) / 1e9
                        # Estimasi USD (pake harga SOL ~$130)
                        buy_amount_usd = sol_amount * 130
                        if token_outputs:
                            bought_mint = token_outputs[0].get("mint", "")

                    elif token_inputs and token_outputs:
                        # USDC in, token out = BUY
                        for inp in token_inputs:
                            if inp.get("mint") == USDC_MINT:
                                buy_amount_usd = inp.get("tokenAmount", 0)
                                if token_outputs:
                                    bought_mint = token_outputs[0].get("mint", "")
                                break

                    if not bought_mint or bought_mint in (SOL_MINT, USDC_MINT):
                        return None

                    if buy_amount_usd < MIN_BUY_USD:
                        logger.debug(f"Copy trade skip: buy too small ${buy_amount_usd:.0f}")
                        return None

                    return {
                        "mint": bought_mint,
                        "buy_amount_usd": buy_amount_usd,
                        "wallet": wallet,
                        "wallet_label": WATCHED_WALLETS.get(wallet, wallet[:8]),
                        "tx_sig": tx_sig
                    }

        except Exception as e:
            logger.debug(f"Parse tx error: {e}")
            return None

    async def handle_copy_signal(self, signal: dict):
        """Handle copy trade signal - buy kalau memenuhi kriteria."""
        mint = signal["mint"]
        wallet_label = signal["wallet_label"]

        # Skip kalau udah di-copy
        if mint in self.recent_copies:
            logger.debug(f"Copy trade skip {mint}: already copied")
            return

        # Cek max positions
        if len(self.copy_positions) >= MAX_COPY_POSITIONS:
            logger.info(f"Copy trade skip: max {MAX_COPY_POSITIONS} copy positions reached")
            return

        # Cek umur token
        age_hours = await self.get_token_age_hours(mint)
        if age_hours is None or age_hours > MAX_TOKEN_AGE_HOURS:
            logger.info(f"Copy trade skip {mint}: token too old ({age_hours:.1f}h)")
            return

        logger.info(f"🔥 Copy trade signal dari {wallet_label}: {mint} (age: {age_hours:.1f}h, buy: ${signal['buy_amount_usd']:.0f})")

        if self.notify:
            await self.notify(
                f"👀 Copy trade signal!\n"
                f"Wallet: {wallet_label}\n"
                f"Token: {mint[:20]}...\n"
                f"Their buy: ${signal['buy_amount_usd']:.0f}\n"
                f"Age: {age_hours:.1f}h\n"
                f"Executing copy..."
            )

        # Execute copy trade via trader
        if self.trader:
            token_data = {
                "mint": mint,
                "symbol": mint[:8],  # fallback, trader akan update
                "dex": "copy_trade",
                "age_days": age_hours / 24,
                "liquidity": 10000,  # placeholder
                "market_cap": 50000,  # placeholder
                "volume_spike": 2.0,
                "price_1h": 0,
                "price_6h": 0,
                "price_24h": 0,
                "buy_ratio": 60,
                "txns_1h_buys": 10,
                "txns_1h_sells": 5,
                "rugcheck_score": 500,
                "mint_enabled": False,
                "freeze_enabled": False,
                "bundle_pct": 10,
                "copy_trade": True,
                "copy_wallet": wallet_label,
            }
            self.recent_copies.add(mint)
            self.copy_positions[mint] = wallet_label
            await self.trader.handle_token_signal(token_data)

    async def monitor_wallet(self, wallet: str):
        """Monitor satu wallet via Helius websocket."""
        label = WATCHED_WALLETS.get(wallet, wallet[:8])
        logger.info(f"👀 Monitoring wallet: {label} ({wallet[:20]}...)")

        while self.running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        HELIUS_WS_URL,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as ws:
                        # Subscribe ke transaksi wallet
                        sub_msg = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "logsSubscribe",
                            "params": [
                                {"mentions": [wallet]},
                                {"commitment": "confirmed"}
                            ]
                        }
                        await ws.send_json(sub_msg)
                        logger.info(f"✅ Subscribed to {label}")

                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                
                                # Handle subscription confirm
                                if "result" in data:
                                    continue

                                # Handle log notification
                                params = data.get("params", {})
                                result = params.get("result", {})
                                value = result.get("value", {})
                                
                                tx_sig = value.get("signature", "")
                                err = value.get("err")
                                
                                if tx_sig and not err:
                                    # Parse transaksi
                                    signal = await self.parse_transaction(tx_sig, wallet)
                                    if signal:
                                        asyncio.create_task(self.handle_copy_signal(signal))

                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                break

            except Exception as e:
                logger.error(f"Websocket error for {label}: {e}")
                await asyncio.sleep(5)  # reconnect setelah 5 detik

    async def start(self):
        """Start monitoring semua wallets."""
        self.running = True
        logger.info(f"🚀 Copy trader started - monitoring {len(WATCHED_WALLETS)} wallets")
        
        # Monitor tiap wallet di task terpisah
        tasks = [
            asyncio.create_task(self.monitor_wallet(wallet))
            for wallet in WATCHED_WALLETS
        ]
        await asyncio.gather(*tasks)

    def stop(self):
        self.running = False
