import re

# ============================================
# FIX 1: pump_executor.py — tambah Jupiter fallback di sell()
# ============================================
content = open('/root/pump_executor.py').read()

old_sell = '''async def sell(mint: str, pct: float = 100, symbol: str = "") -> dict:
    """
    Sell token by exact token amount (lebih reliable dari % based).
    pct: 100 = jual semua, 50 = jual setengah
    """
    logger.info(f"💰 SELL {symbol or mint[:8]} — {pct}%")

    async with aiohttp.ClientSession() as session:
        try:
            pool = await detect_pool(mint, session)

            # Ambil balance token dulu
            token_balance = await get_token_balance(mint)
            if token_balance <= 0:
                return {"success": False, "error": "No token balance"}

            sell_amount = token_balance * (pct / 100)
            logger.info(f"   Token balance: {token_balance:.2f}, selling {sell_amount:.2f}")

            tx_bytes = await get_transaction_bytes(
                action="sell",
                mint=mint,
                amount=sell_amount,
                pool=pool,
                slippage=25,
                priority_fee=0.001,
                session=session
            )

            tx_sig = await sign_and_send(tx_bytes, session)
            logger.info(f"   ✅ SELL TX: https://solscan.io/tx/{tx_sig}")

            return {"success": True, "tx": tx_sig}

        except Exception as e:
            logger.error(f"   ❌ Sell failed: {e}")
            return {"success": False, "error": str(e)}'''

new_sell = '''async def sell(mint: str, pct: float = 100, symbol: str = "") -> dict:
    """
    Sell token by exact token amount (lebih reliable dari % based).
    pct: 100 = jual semua, 50 = jual setengah
    Includes: Jupiter fallback + both pool retry + balance verification
    """
    logger.info(f"💰 SELL {symbol or mint[:8]} — {pct}%")

    async with aiohttp.ClientSession() as session:
        # Ambil balance token dulu
        token_balance = await get_token_balance(mint)
        if token_balance <= 0:
            logger.warning(f"   ⚠️ No token balance for {symbol}, double checking...")
            await asyncio.sleep(3)
            token_balance = await get_token_balance(mint)
            if token_balance <= 0:
                return {"success": False, "error": "No token balance"}

        sell_amount = token_balance * (pct / 100)
        logger.info(f"   Token balance: {token_balance:.2f}, selling {sell_amount:.2f}")

        # Try Pump Portal dengan kedua pool
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
                if tx_sig and len(tx_sig) > 50:
                    logger.info(f"   ✅ SELL TX ({pool}): https://solscan.io/tx/{tx_sig}")
                    # Verify token sudah keluar
                    await asyncio.sleep(5)
                    remaining = await get_token_balance(mint)
                    if remaining < token_balance * 0.1:
                        logger.info(f"   ✅ Sell confirmed — balance {token_balance:.0f} → {remaining:.0f}")
                        return {"success": True, "tx": tx_sig, "pool": pool}
                    else:
                        logger.warning(f"   ⚠️ TX sent tapi balance masih ada ({remaining:.0f}) — coba pool lain")
                        continue
            except Exception as e:
                logger.warning(f"   ⚠️ Pump Portal sell ({pool}) failed: {e!r}")
                continue

        # Fallback Jupiter sell
        logger.warning(f"   🔄 Pump Portal gagal semua pool — fallback Jupiter sell")
        try:
            result = await _jupiter_sell(mint, sell_amount, symbol, session)
            return result
        except Exception as e:
            logger.error(f"   ❌ Jupiter sell also failed: {e!r}")
            return {"success": False, "error": f"All sell methods failed: {e!r}"}'''

if old_sell in content:
    content = content.replace(old_sell, new_sell)
    print("✅ sell() function replaced")
else:
    print("❌ sell() pattern not found — manual check needed")

open('/root/pump_executor.py', 'w').write(content)
