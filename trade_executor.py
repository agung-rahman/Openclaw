"""
trade_executor.py - Eksekusi swap di Solana via Jupiter API
- Buy token dengan SOL/USDC
- Sell token kembali ke SOL/USDC
"""

import asyncio
import aiohttp
import json
import base64
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Constants
JUPITER_QUOTE_URL = "https://public.jupiterapi.com/quote"
JUPITER_SWAP_URL = "https://public.jupiterapi.com/swap"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Trade config
TRADE_AMOUNT_USD = 3.0      # $3 per trade
SLIPPAGE_BPS = 1000          # 3% slippage (degen token perlu lebih tinggi)
PRIORITY_FEE = 200_000      # 0.0001 SOL priority fee


@dataclass
class Position:
    token_mint: str
    token_symbol: str
    buy_price_usd: float
    amount_token: float         # jumlah token yang dipegang
    amount_invested_usd: float  # total USD yang diinvest
    buy_time: datetime
    tp1_hit: bool = False       # sudah hit TP1 (2x) belum
    tp1_amount_sold: float = 0  # token yang sudah dijual di TP1
    status: str = "open"        # open, tp1_hit, closed
    tx_buy: Optional[str] = None
    tx_sell_tp1: Optional[str] = None
    tx_sell_final: Optional[str] = None

    def current_value_usd(self, current_price: float) -> float:
        return self.amount_token * current_price

    def pnl_pct(self, current_price: float) -> float:
        if self.buy_price_usd == 0:
            return 0
        return ((current_price - self.buy_price_usd) / self.buy_price_usd) * 100

    def to_dict(self):
        return {
            "token_mint": self.token_mint,
            "token_symbol": self.token_symbol,
            "buy_price_usd": self.buy_price_usd,
            "amount_token": self.amount_token,
            "amount_invested_usd": self.amount_invested_usd,
            "buy_time": self.buy_time.isoformat(),
            "tp1_hit": self.tp1_hit,
            "status": self.status,
            "tx_buy": self.tx_buy,
        }


class TradeExecutor:
    def __init__(self, keypair, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.keypair = keypair
        self.rpc_url = rpc_url
        self.public_key = str(keypair.pubkey())

    async def get_sol_price_usd(self) -> float:
        """Ambil harga SOL dalam USD via Jupiter."""
        try:
            async with aiohttp.ClientSession() as session:
                # Quote 1 SOL → USDC
                params = {
                    "inputMint": SOL_MINT,
                    "outputMint": USDC_MINT,
                    "amount": 1_000_000_000,  # 1 SOL in lamports
                    "slippageBps": 50,
                }
                async with session.get(JUPITER_QUOTE_URL, params=params) as resp:
                    data = await resp.json()
                    usdc_out = int(data["outAmount"]) / 1_000_000  # USDC 6 decimals
                    return usdc_out
        except Exception as e:
            logger.error(f"Failed to get SOL price: {e}")
            return 130.0  # fallback

    async def get_token_price_usd(self, token_mint: str) -> Optional[float]:
        """Ambil harga token dalam USD."""
        try:
            async with aiohttp.ClientSession() as session:
                # Quote 1 USDC → token untuk dapat harga
                params = {
                    "inputMint": USDC_MINT,
                    "outputMint": token_mint,
                    "amount": 1_000_000,  # 1 USDC
                    "slippageBps": 100,
                }
                async with session.get(JUPITER_QUOTE_URL, params=params) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if "error" in data:
                        return None
                    token_out = int(data["outAmount"])
                    decimals = await self.get_token_decimals(token_mint)
                    token_out_adj = token_out / (10 ** decimals)
                    if token_out_adj == 0:
                        return None
                    return 1.0 / token_out_adj  # 1 token = ? USD
        except Exception as e:
            logger.error(f"Failed to get token price: {e}")
            return None

    async def get_token_decimals(self, token_mint: str) -> int:
        """Ambil decimals token dari RPC."""
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [
                        token_mint,
                        {"encoding": "jsonParsed"}
                    ]
                }
                async with session.post(self.rpc_url, json=payload) as resp:
                    data = await resp.json()
                    decimals = data["result"]["value"]["data"]["parsed"]["info"]["decimals"]
                    return decimals
        except:
            return 9  # default

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = SLIPPAGE_BPS
    ) -> Optional[dict]:
        """Ambil quote dari Jupiter."""
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "inputMint": input_mint,
                    "outputMint": output_mint,
                    "amount": amount,
                    "slippageBps": slippage_bps,
                }
                async with session.get(JUPITER_QUOTE_URL, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"Quote error {resp.status}: {text}")
                        return None
                    data = await resp.json()
                    if "error" in data:
                        logger.error(f"Quote error: {data['error']}")
                        return None
                    return data
        except Exception as e:
            logger.error(f"Get quote exception: {e}")
            return None

    async def execute_swap(self, quote: dict) -> Optional[str]:
        """Eksekusi swap berdasarkan quote. Return tx signature."""
        try:
            from solders.transaction import VersionedTransaction

            async with aiohttp.ClientSession() as session:
                swap_payload = {
                    "quoteResponse": quote,
                    "userPublicKey": self.public_key,
                    "wrapAndUnwrapSol": True,
                    "prioritizationFeeLamports": PRIORITY_FEE,
                    "dynamicComputeUnitLimit": True,
                }

                async with session.post(
                    JUPITER_SWAP_URL,
                    json=swap_payload,
                    headers={"Content-Type": "application/json"}
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"Swap API error: {text}")
                        return None
                    swap_data = await resp.json()

                # Decode transaksi
                swap_tx_bytes = base64.b64decode(swap_data["swapTransaction"])
                tx = VersionedTransaction.from_bytes(swap_tx_bytes)

                # Sign
                signed_tx = VersionedTransaction(tx.message, [self.keypair])

                # Send via RPC
                tx_signature = await self._send_transaction(bytes(signed_tx))
                return tx_signature

        except Exception as e:
            logger.error(f"Execute swap exception: {e}", exc_info=True)
            return None

    async def _send_transaction(self, signed_tx_bytes: bytes) -> Optional[str]:
        """Kirim transaksi ke RPC."""
        try:
            async with aiohttp.ClientSession() as session:
                encoded_tx = base64.b64encode(signed_tx_bytes).decode()
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        encoded_tx,
                        {
                            "encoding": "base64",
                            "skipPreflight": True,
                            "maxRetries": 3,
                        }
                    ]
                }
                async with session.post(self.rpc_url, json=payload) as resp:
                    data = await resp.json()
                    if "error" in data:
                        logger.error(f"Send tx error: {data['error']}")
                        return None
                    return data.get("result")
        except Exception as e:
            logger.error(f"Send transaction exception: {e}")
            return None

    async def buy_token(self, token_mint: str, token_symbol: str) -> Optional[Position]:
        """
        Buy token dengan SOL senilai TRADE_AMOUNT_USD.
        Return Position object kalau sukses.
        """
        logger.info(f"🛒 Buying {token_symbol} ({token_mint})")

        # Hitung berapa SOL yang perlu dikirim
        sol_price = await self.get_sol_price_usd()
        sol_amount = TRADE_AMOUNT_USD / sol_price
        lamports = int(sol_amount * 1_000_000_000)

        logger.info(f"   SOL price: ${sol_price:.2f}, Amount: {sol_amount:.4f} SOL ({lamports} lamports)")

        # Get quote SOL → Token
        quote = await self.get_quote(SOL_MINT, token_mint, lamports)
        if not quote:
            logger.error(f"Failed to get quote for {token_symbol}")
            return None

        decimals = await self.get_token_decimals(token_mint)
        expected_token_out = int(quote["outAmount"]) / (10 ** decimals)
        logger.info(f"   Expected output: {expected_token_out:.2f} {token_symbol}")

        # Eksekusi
        tx_sig = await self.execute_swap(quote)
        if not tx_sig:
            logger.error(f"Failed to execute buy for {token_symbol}")
            return None

        logger.info(f"   ✅ Buy TX: https://solscan.io/tx/{tx_sig}")

        # Hitung buy price
        token_price = await self.get_token_price_usd(token_mint)
        if not token_price:
            token_price = TRADE_AMOUNT_USD / expected_token_out

        position = Position(
            token_mint=token_mint,
            token_symbol=token_symbol,
            buy_price_usd=token_price,
            amount_token=expected_token_out,
            amount_invested_usd=TRADE_AMOUNT_USD,
            buy_time=datetime.now(),
            tx_buy=tx_sig,
        )

        logger.info(f"   📊 Position opened: {expected_token_out:.2f} {token_symbol} @ ${token_price:.8f}")
        return position

    async def sell_token(
        self,
        position: Position,
        sell_pct: float = 1.0,  # 1.0 = jual semua, 0.5 = jual setengah
        reason: str = "manual"
    ) -> Optional[str]:
        """
        Jual sebagian atau semua token.
        Return tx signature.
        """
        decimals = await self.get_token_decimals(position.token_mint)
        sell_amount = position.amount_token * sell_pct
        sell_amount_raw = int(sell_amount * (10 ** decimals))

        logger.info(f"💸 Selling {sell_pct*100:.0f}% of {position.token_symbol} ({reason})")
        logger.info(f"   Amount: {sell_amount:.4f} {position.token_symbol}")

        # Get quote Token → SOL
        quote = await self.get_quote(position.token_mint, SOL_MINT, sell_amount_raw)
        if not quote:
            logger.error(f"Failed to get sell quote for {position.token_symbol}")
            return None

        sol_out = int(quote["outAmount"]) / 1_000_000_000
        sol_price = await self.get_sol_price_usd()
        usd_out = sol_out * sol_price

        logger.info(f"   Expected: {sol_out:.4f} SOL (${usd_out:.2f})")

        tx_sig = await self.execute_swap(quote)
        if not tx_sig:
            logger.error(f"Failed to execute sell for {position.token_symbol}")
            return None

        logger.info(f"   ✅ Sell TX ({reason}): https://solscan.io/tx/{tx_sig}")
        return tx_sig
