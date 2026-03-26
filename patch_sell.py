import re

content = open('/root/pump_executor.py').read()

# Cari batas fungsi sell() sampai _save_position
start = content.find('\nasync def sell(mint: str, pct: float = 100')
end = content.find('\ndef _save_position(')

if start == -1 or end == -1:
    print(f"ERROR: start={start}, end={end}")
    exit(1)

old_sell = content[start:end]
print(f"Found sell() — {len(old_sell)} chars")

new_sell = '''
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

'''

content = content[:start] + new_sell + content[end:]
open('/root/pump_executor.py', 'w').write(content)
print("✅ sell() patched!")
