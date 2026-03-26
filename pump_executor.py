"""
pump_executor.py - Eksekusi trade via Pump Portal
Auto-detect pool (pump vs pump-amm) berdasarkan token status
"""

import asyncio
import aiohttp
import base64
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY_EXECUTOR', "")}"
FALLBACK_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
]

async def _rpc_call(session, payload):
    """RPC call dengan fallback kalau Helius rate limit."""
    endpoints = [HELIUS_RPC] + FALLBACK_RPCS
    for ep in endpoints:
        try:
            async with session.post(ep, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
                data = await r.json()
                err = data.get("error")
                if err and err.get("code") == -32429:
                    logger.warning(f"Rate limit on {ep}, trying fallback...")
                    continue
                return data
        except Exception as e:
            logger.warning(f"RPC error on {ep}: {e}")
            continue
    return {}
PUMP_PORTAL = "https://pumpportal.fun/api/trade-local"

# Jupiter fallback
JUPITER_QUOTE = "https://public.jupiterapi.com/quote"
JUPITER_SWAP  = "https://public.jupiterapi.com/swap"
SOL_MINT      = "So11111111111111111111111111111111111111112"

def get_keypair() -> Keypair:
    from wallet_manager import get_keypair as _get_keypair
    return _get_keypair()

async def detect_pool(mint: str, session: aiohttp.ClientSession) -> str:
    """Detect apakah token masih di bonding curve atau udah migrate ke pump-amm."""
    # Cek pump.fun API dulu
    try:
        async with session.get(
            f"https://frontend-api.pump.fun/coins/{mint}",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status == 200:
                d = await r.json()
                if d.get("complete", False) or d.get("raydium_pool"):
                    logger.info(f"   Pool detect: pump-amm (bonding complete)")
                    return "pump-amm"
                # Masih di bonding curve
                logger.info(f"   Pool detect: pump (bonding curve)")
                return "pump"
            elif r.status == 404:
                # Token tidak ada di pump.fun — bukan pump token
                logger.info(f"   Pool detect: pump-amm (not on pump.fun)")
                return "pump-amm"
            else:
                # pump.fun API error (530, 503, dll) — jangan assume pump
                logger.warning(f"   pump.fun API status {r.status} — fallback ke DexScreener")
    except Exception as e:
        logger.warning(f"   Pool detect error: {e}")

    # Fallback: cek DexScreener — kalau ada pair di raydium/orca = pump-amm
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=6)
        ) as r:
            if r.status == 200:
                d = await r.json()
                pairs = d.get("pairs", [])
                for p in pairs:
                    dex = p.get("dexId", "").lower()
                    if dex in ("raydium", "orca", "meteora"):
                        logger.info(f"   Pool detect: pump-amm (found on {dex})")
                        return "pump-amm"
                if pairs:
                    dex = pairs[0].get("dexId", "").lower()
                    if "pump" in dex:
                        logger.info(f"   Pool detect: pump (found on {dex})")
                        return "pump"
    except Exception as e:
        logger.warning(f"   Pool detect DexScreener error: {e}")

    # Default pump-amm — lebih aman, Pump Portal support keduanya
    logger.info(f"   Pool detect: pump-amm (default fallback)")
    return "pump-amm"


async def get_transaction_bytes(
    action: str,  # "buy" atau "sell"
    mint: str,
    amount,  # SOL untuk buy, % untuk sell (0-100)
    pool: str,
    slippage: int = 25,
    priority_fee: float = 0.001,
    session: aiohttp.ClientSession = None
) -> bytes:
    """Ambil transaction bytes dari Pump Portal."""
    payload = {
        "publicKey": str(get_keypair().pubkey()),
        "action": action,
        "mint": mint,
        "denominatedInSol": "true" if action == "buy" else "false",
        "amount": amount,
        "slippage": slippage,
        "priorityFee": priority_fee,
        "pool": pool
    }
    
    async with session.post(
        PUMP_PORTAL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=aiohttp.ClientTimeout(total=10)
    ) as r:
        if r.status != 200:
            text = await r.text()
            # Auto-retry dengan pool sebaliknya kalau 400
            if r.status == 400:
                other_pool = "pump" if payload.get("pool") == "pump-amm" else "pump-amm"
                logger.warning(f"   Pump Portal 400 (pool={payload['pool']}), retry {other_pool}...")
                payload["pool"] = other_pool
                async with session.post(
                    PUMP_PORTAL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r2:
                    if r2.status != 200:
                        text2 = await r2.text()
                        raise Exception(f"Pump Portal error {r2.status} (both pools tried): {text2}")
                    return await r2.read()
            raise Exception(f"Pump Portal error {r.status}: {text}")
        return await r.read()


async def sign_and_send(tx_bytes: bytes, session: aiohttp.ClientSession) -> str:
    """Sign transaction dan kirim ke Solana via Helius RPC."""
    keypair = get_keypair()
    
    # Deserialize transaction
    tx = VersionedTransaction.from_bytes(tx_bytes)
    
    # Sign
    tx = VersionedTransaction(tx.message, [keypair])
    signed_bytes = bytes(tx)
    
    # Send via Helius RPC
    encoded = base64.b64encode(signed_bytes).decode()
    async with session.post(
        HELIUS_RPC,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                encoded,
                {
                    "encoding": "base64",
                    "skipPreflight": True,
                    "maxRetries": 3,
                    "preflightCommitment": "processed"
                }
            ]
        },
        timeout=aiohttp.ClientTimeout(total=15)
    ) as r:
        data = await r.json()
        if "error" in data:
            raise Exception(f"RPC error: {data['error']}")
        return data["result"]  # tx signature


async def buy(mint: str, amount_sol: float, symbol: str = "", wallet_source: str = "") -> dict:
    """
    Buy token dengan SOL.
    Returns: {"success": bool, "tx": str, "error": str}
    """
    logger.info(f"🛒 BUY {symbol or mint[:8]} — {amount_sol} SOL")
    
    async with aiohttp.ClientSession() as session:
        try:
            # Detect pool
            pool = await detect_pool(mint, session)
            logger.info(f"   Pool: {pool}")
            
            # Get transaction
            tx_bytes = await get_transaction_bytes(
                action="buy",
                mint=mint,
                amount=amount_sol,
                pool=pool,
                slippage=25,
                priority_fee=0.001,
                session=session
            )
            logger.info(f"   Got tx bytes: {len(tx_bytes)} bytes")
            
            # Ambil harga beli SEBELUM TX sent — biar akurat
            # Sign & send dulu, hitung harga dari actual fill
            tx_sig = await sign_and_send(tx_bytes, session)
            
            # Validasi TX berhasil
            if not tx_sig or len(tx_sig) < 50:
                raise Exception(f"Invalid TX signature: {tx_sig}")
            
            logger.info(f"   ✅ TX: https://solscan.io/tx/{tx_sig}")
            # Notif TG langsung setelah TX sent
            _tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            _tg_chat = os.getenv("TELEGRAM_CHAT_ID", "5664251521")
            try:
                async with aiohttp.ClientSession() as _tgs:
                    await _tgs.post(
                        f"https://api.telegram.org/bot{_tg_token}/sendMessage",
                        json={"chat_id": int(_tg_chat), "text":
                            f"⏳ <b>BUY SENT</b> — {symbol}\n📋 CA: <code>{mint}</code>\n🔗 TX: https://solscan.io/tx/{tx_sig}\n<i>Menunggu konfirmasi...</i>",
                            "parse_mode": "HTML"},
                        timeout=aiohttp.ClientTimeout(total=5)
                    )
            except:
                pass
            
            
            # Ambil token amount dari wallet
            # Tunggu TX confirm — ambil dari TX data Helius (akurat)
            await asyncio.sleep(5)
            token_amount = 0
            _HELIUS = os.environ.get("HELIUS_API_KEY_EXECUTOR", "")
            _WALLET = os.environ.get("WALLET_ADDRESS", "75m7QVKfXhJZqfCFX5jgKbyyYQXvEG4U4p1EsX3xRrwA")
            for _attempt in range(5):
                try:
                    async with aiohttp.ClientSession() as _hs:
                        async with _hs.post(
                            f"https://mainnet.helius-rpc.com/?api-key={_HELIUS}",
                            json={"jsonrpc":"2.0","id":1,"method":"getTransaction",
                                  "params":[tx_sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]},
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as _r:
                            _d = await _r.json()
                            _post = ((_d.get("result") or {}).get("meta") or {}).get("postTokenBalances", [])
                            for _pb in _post:
                                if _pb.get("mint") == mint and _pb.get("owner") == _WALLET:
                                    token_amount = float((_pb.get("uiTokenAmount") or {}).get("uiAmount") or 0)
                                    break
                    if token_amount > 0:
                        logger.info(f"   ✅ TX confirmed — {token_amount:.2f} {symbol} (attempt {_attempt+1})")
                        break
                except Exception as _e:
                    logger.warning(f"   ⚠️ TX fetch attempt {_attempt+1}: {_e}")
                await asyncio.sleep(6)
            if token_amount == 0:
                logger.warning(f"   ⚠️ TX data kosong, fallback ke wallet balance")
                await asyncio.sleep(10)
                token_amount = await get_token_balance(mint)
            if token_amount == 0:
                logger.warning(f"   ⚠️ Balance masih 0 — estimasi dari wallet balance")
                token_amount = await get_token_balance(mint)
            if token_amount == 0:
                token_amount = 1.0
            if token_amount <= 0:
                token_amount = 1.0
            # Hitung actual buy price dari SOL spent / tokens received
            sol_price = 87.0
            try:
                async with aiohttp.ClientSession() as _sp:
                    async with _sp.get(
                        "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                        timeout=aiohttp.ClientTimeout(total=4)
                    ) as _rsp:
                        _dsp = await _rsp.json()
                        sol_price = float(_dsp.get("pair",{}).get("priceUsd", 87) or 87)
            except: pass
            buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0
            logger.info(f"   📊 Bought {token_amount:.2f} {symbol} @ ${buy_price:.8f} (actual fill)")

            # Kalau token_amount 0 = TX mungkin pending — simpan dengan flag warning
            if token_amount == 0:
                logger.warning(f"   ⚠️ token_amount 0 — TX pending/failed, position disimpan untuk review")
                _save_position(mint, symbol, amount_sol, tx_sig, 0, 0, wallet_source)
                return {"success": True, "tx": tx_sig, "pool": pool, "warning": "token_amount_unknown"}

            # Simpan posisi
            _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)

            return {"success": True, "tx": tx_sig, "pool": pool}
            
        except Exception as e:
            import traceback
            logger.warning(f"   ⚠️ Pump Portal failed: {e!r}, retrying via Jupiter...")
            # Fallback ke Jupiter
            try:
                result = await _jupiter_buy(mint, amount_sol, symbol, wallet_source, session)
                return result
            except Exception as e2:
                logger.error(f"   ❌ Jupiter also failed: {e2!r}")
                logger.error(traceback.format_exc())
                return {"success": False, "error": repr(e2)}



async def get_token_price_usd(mint: str) -> float:
    """Ambil harga token dari DexScreener."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
                timeout=aiohttp.ClientTimeout(total=8)
            ) as r:
                data = await r.json()
                pairs = data.get("pairs", [])
                if pairs:
                    return float(pairs[0].get("priceUsd", 0) or 0)
    except:
        pass
    return 0.0

async def get_token_balance(mint: str) -> float:
    """Cek balance token di wallet — dengan retry dan fallback RPC."""
    WALLET = str(get_keypair().pubkey())
    endpoints = [HELIUS_RPC] + FALLBACK_RPCS
    for endpoint in endpoints:
        for attempt in range(3):
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.post(
                        endpoint,
                        json={"jsonrpc": "2.0", "id": 1,
                              "method": "getTokenAccountsByOwner",
                              "params": [WALLET, {"mint": mint}, {"encoding": "jsonParsed"}]},
                        timeout=aiohttp.ClientTimeout(total=8)
                    ) as r:
                        if r.status != 200:
                            await asyncio.sleep(1)
                            continue
                        data = await r.json()
                        err = data.get("error")
                        if err:
                            await asyncio.sleep(1)
                            continue
                        accounts = data.get("result", {}).get("value", [])
                        for acc in accounts:
                            amount = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
                            bal = float(amount.get("uiAmount", 0) or 0)
                            if bal > 0:
                                return bal
                        # Accounts kosong tapi request sukses — token memang 0
                        return 0.0
            except Exception as e:
                logger.warning(f"get_token_balance attempt {attempt+1} failed ({endpoint[:30]}): {e}")
                await asyncio.sleep(1)
    return 0.0




async def _jupiter_buy(mint: str, amount_sol: float, symbol: str, wallet_source: str, session: aiohttp.ClientSession) -> dict:
    """Buy via Jupiter API — fallback kalau Pump Portal gagal."""
    import base64 as _b64
    from solders.transaction import VersionedTransaction as _VT

    keypair = get_keypair()
    pubkey = str(keypair.pubkey())
    lamports = int(amount_sol * 1_000_000_000)

    logger.info(f"   🔄 Jupiter buy {symbol} — {lamports} lamports")

    # 1. Get quote
    async with session.get(JUPITER_QUOTE, params={
        "inputMint": SOL_MINT, "outputMint": mint,
        "amount": lamports, "slippageBps": 1500,
    }, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status != 200:
            raise Exception(f"Jupiter quote error {r.status}: {await r.text()}")
        quote = await r.json()
        if "error" in quote:
            raise Exception(f"Jupiter quote: {quote['error']}")

    token_out = int(quote["outAmount"])
    logger.info(f"   Jupiter quote OK — expected {token_out} tokens")

    # 2. Get swap tx
    async with session.post(JUPITER_SWAP, json={
        "quoteResponse": quote,
        "userPublicKey": pubkey,
        "wrapAndUnwrapSol": True,
        "prioritizationFeeLamports": 200000,
        "dynamicComputeUnitLimit": True,
    }, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status != 200:
            raise Exception(f"Jupiter swap error: {await r.text()}")
        swap_data = await r.json()

    # 3. Sign & send
    tx_bytes = _b64.b64decode(swap_data["swapTransaction"])
    tx = _VT.from_bytes(tx_bytes)
    tx = _VT(tx.message, [keypair])
    tx_sig = await sign_and_send(bytes(tx), session)

    if not tx_sig or len(tx_sig) < 50:
        raise Exception(f"Invalid TX sig: {tx_sig}")

    logger.info(f"   ✅ Jupiter TX: https://solscan.io/tx/{tx_sig}")

    # 4. Tunggu confirm & ambil token amount
    await asyncio.sleep(6)
    token_amount = 0
    _HELIUS = os.environ.get("HELIUS_API_KEY_EXECUTOR", "")
    _WALLET = os.environ.get("WALLET_ADDRESS", pubkey)
    for _attempt in range(5):
        try:
            async with aiohttp.ClientSession() as _hs:
                async with _hs.post(
                    f"https://mainnet.helius-rpc.com/?api-key={_HELIUS}",
                    json={"jsonrpc":"2.0","id":1,"method":"getTransaction",
                          "params":[tx_sig,{"encoding":"jsonParsed","maxSupportedTransactionVersion":0}]},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as _r:
                    _d = await _r.json()
                    _post = ((_d.get("result") or {}).get("meta") or {}).get("postTokenBalances", [])
                    for _pb in _post:
                        if _pb.get("mint") == mint and _pb.get("owner") == _WALLET:
                            token_amount = float((_pb.get("uiTokenAmount") or {}).get("uiAmount") or 0)
                            break
            if token_amount > 0:
                break
        except:
            pass
        await asyncio.sleep(6)

    if token_amount == 0:
        token_amount = await get_token_balance(mint)
    if token_amount == 0:
        token_amount = 1.0

    sol_price = 91.0
    try:
        async with aiohttp.ClientSession() as _sp:
            async with _sp.get(
                "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                timeout=aiohttp.ClientTimeout(total=4)
            ) as _r:
                _d = await _r.json()
                sol_price = float(_d.get("pair",{}).get("priceUsd", 91) or 91)
    except:
        pass

    buy_price = (amount_sol * sol_price) / token_amount if token_amount > 1 else 0
    _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)
    logger.info(f"   📊 Jupiter bought {token_amount:.2f} {symbol} @ ${buy_price:.8f}")
    return {"success": True, "tx": tx_sig, "pool": "jupiter"}

async def sell(mint: str, pct: float = 100, symbol: str = "") -> dict:
    """
    Sell token — dual pool retry + Jupiter fallback + balance verification.
    pct: 100 = jual semua, 50 = jual setengah
    """
    logger.info(f"💰 SELL {symbol or mint[:8]} — {pct}%")

    async with aiohttp.ClientSession() as session:
        # Cek balance dulu
        token_balance = await get_token_balance(mint)
        if token_balance <= 0:
            logger.warning(f"   ⚠️ No token balance for {symbol}, double checking in 3s...")
            await asyncio.sleep(3)
            token_balance = await get_token_balance(mint)
            if token_balance <= 0:
                return {"success": False, "error": "No token balance"}

        sell_amount = token_balance * (pct / 100)
        logger.info(f"   Token balance: {token_balance:.2f}, selling {sell_amount:.2f}")

        # Try Pump Portal — coba kedua pool
        for pool in ["pump-amm", "pump"]:
            try:
                tx_bytes = await get_transaction_bytes(
                    action="sell",
                    mint=mint,
                    amount=sell_amount,
                    pool=pool,
                    slippage=30,
                    priority_fee=0.002,
                    session=session
                )
                tx_sig = await sign_and_send(tx_bytes, session)
                if not tx_sig or len(tx_sig) < 50:
                    logger.warning(f"   ⚠️ Invalid tx_sig from {pool}: {tx_sig}")
                    continue

                logger.info(f"   ✅ SELL TX ({pool}): https://solscan.io/tx/{tx_sig}")

                # Verify balance berkurang
                await asyncio.sleep(5)
                remaining = await get_token_balance(mint)
                if remaining < token_balance * 0.1:
                    logger.info(f"   ✅ Sell confirmed — {token_balance:.0f} → {remaining:.0f}")
                    return {"success": True, "tx": tx_sig, "pool": pool}
                else:
                    logger.warning(f"   ⚠️ TX sent tapi balance masih {remaining:.0f} — coba pool lain")
                    continue
            except Exception as e:
                logger.warning(f"   ⚠️ Pump Portal sell ({pool}) failed: {e!r}")
                continue

        # Fallback Jupiter sell
        logger.warning(f"   🔄 Semua Pump Portal pool gagal — fallback Jupiter sell")
        try:
            return await _jupiter_sell(mint, sell_amount, symbol, session)
        except Exception as e:
            logger.error(f"   ❌ Jupiter sell juga gagal: {e!r}")
            return {"success": False, "error": f"All sell methods failed: {e!r}"}


def _save_position(mint: str, symbol: str, amount_sol: float, tx_sig: str, buy_price_usd: float = 0, amount_token: float = 0, wallet_source: str = ""):
    """Simpan posisi ke file."""
    pos_file = Path("/root/.openclaw_positions.json")
    positions = json.loads(pos_file.read_text()) if pos_file.exists() else {}
    positions[mint] = {
        "token_symbol": symbol,
        "amount_invested_sol": amount_sol,
        "buy_time": datetime.now().isoformat(),
        "tx_buy": tx_sig,
        "status": "open",
        "buy_price_usd": buy_price_usd,
        "amount_token": amount_token,
        "wallet_source": wallet_source
    }
    pos_file.write_text(json.dumps(positions, indent=2))


async def get_sol_balance() -> float:
    """Cek SOL balance wallet."""
    pubkey = str(get_keypair().pubkey())
    async with aiohttp.ClientSession() as session:
        async with session.post(
            HELIUS_RPC,
            json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pubkey]},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            lamports = data.get("result", {}).get("value", 0)
            return lamports / 1_000_000_000


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 3:
        print("Usage: python3 pump_executor.py buy <mint> [amount_sol]")
        print("       python3 pump_executor.py sell <mint> [pct]")
        sys.exit(1)
    
    action = sys.argv[1]
    mint = sys.argv[2]
    
    async def main():
        bal = await get_sol_balance()
        print(f"💰 Balance: {bal:.4f} SOL")
        
        if action == "buy":
            amount = float(sys.argv[3]) if len(sys.argv) > 3 else 0.02
            result = await buy(mint, amount)
        elif action == "sell":
            pct = float(sys.argv[3]) if len(sys.argv) > 3 else 100
            result = await sell(mint, pct)
        else:
            print("Unknown action")
            return
        
        print(json.dumps(result, indent=2))
    
    asyncio.run(main())


async def _jupiter_sell(mint: str, token_amount: float, symbol: str, session: aiohttp.ClientSession) -> dict:
    """Sell via Jupiter — fallback kalau Pump Portal gagal semua pool."""
    import base64 as _b64
    from solders.transaction import VersionedTransaction as _VT

    keypair = get_keypair()
    pubkey = str(keypair.pubkey())

    logger.info(f"   🔄 Jupiter sell {symbol} — {token_amount:.0f} tokens")

    # Ambil decimals dari RPC
    decimals = 6
    try:
        async with session.post(
            HELIUS_RPC,
            json={"jsonrpc":"2.0","id":1,"method":"getTokenSupply","params":[mint]},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            d = await r.json()
            decimals = d.get("result",{}).get("value",{}).get("decimals", 6)
    except:
        pass

    raw_amount = int(token_amount * (10 ** decimals))
    logger.info(f"   Jupiter sell raw: {raw_amount} (decimals={decimals})")

    # Get quote SOL output
    async with session.get(JUPITER_QUOTE, params={
        "inputMint": mint,
        "outputMint": SOL_MINT,
        "amount": raw_amount,
        "slippageBps": 3000,
    }, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status != 200:
            raise Exception(f"Jupiter quote error {r.status}: {await r.text()}")
        quote = await r.json()
        if "error" in quote:
            raise Exception(f"Jupiter quote: {quote['error']}")

    sol_out = int(quote.get("outAmount", 0)) / 1e9
    logger.info(f"   Jupiter sell quote OK — {sol_out:.4f} SOL out")

    # Get swap tx
    async with session.post(JUPITER_SWAP, json={
        "quoteResponse": quote,
        "userPublicKey": pubkey,
        "wrapAndUnwrapSol": True,
        "prioritizationFeeLamports": 300000,
        "dynamicComputeUnitLimit": True,
    }, timeout=aiohttp.ClientTimeout(total=10)) as r:
        if r.status != 200:
            raise Exception(f"Jupiter swap error: {await r.text()}")
        swap_data = await r.json()

    # Sign & send
    tx_bytes = _b64.b64decode(swap_data["swapTransaction"])
    tx = _VT.from_bytes(tx_bytes)
    tx = _VT(tx.message, [keypair])
    tx_sig = await sign_and_send(bytes(tx), session)

    if not tx_sig or len(tx_sig) < 50:
        raise Exception(f"Invalid TX sig: {tx_sig}")

    logger.info(f"   ✅ Jupiter SELL TX: https://solscan.io/tx/{tx_sig}")

    # Verify
    await asyncio.sleep(6)
    remaining = await get_token_balance(mint)
    if remaining < token_amount * 0.1:
        logger.info(f"   ✅ Jupiter sell confirmed")
        return {"success": True, "tx": tx_sig, "pool": "jupiter"}
    else:
        logger.warning(f"   ⚠️ Jupiter sell TX sent tapi balance masih {remaining:.0f}")
        return {"success": True, "tx": tx_sig, "pool": "jupiter", "warning": "balance still present"}
