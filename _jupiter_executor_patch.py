import sys
sys.path.insert(0, '/root')

content = open('/root/pump_executor.py').read()

# Tambah Jupiter import di atas
old_import = 'PUMP_PORTAL = "https://pumpportal.fun/api/trade-local"'
new_import = '''PUMP_PORTAL = "https://pumpportal.fun/api/trade-local"

# Jupiter fallback
JUPITER_QUOTE = "https://public.jupiterapi.com/quote"
JUPITER_SWAP  = "https://public.jupiterapi.com/swap"
SOL_MINT      = "So11111111111111111111111111111111111111112"'''

# Ganti fungsi buy — wrap dengan Jupiter fallback
old_buy_call = '''        except Exception as e:
            import traceback
            logger.error(f"   ❌ Buy failed: {e!r}")
            logger.error(traceback.format_exc())
            return {"success": False, "error": repr(e)}'''

new_buy_call = '''        except Exception as e:
            import traceback
            logger.warning(f"   ⚠️ Pump Portal failed: {e!r}, retrying via Jupiter...")
            # Fallback ke Jupiter
            try:
                result = await _jupiter_buy(mint, amount_sol, symbol, wallet_source, session)
                return result
            except Exception as e2:
                logger.error(f"   ❌ Jupiter also failed: {e2!r}")
                logger.error(traceback.format_exc())
                return {"success": False, "error": repr(e2)}'''

fixes = [
    (old_import, new_import, "Jupiter import"),
    (old_buy_call, new_buy_call, "Jupiter fallback"),
]

for old, new, name in fixes:
    if old in content:
        content = content.replace(old, new)
        print(f"✅ {name}")
    else:
        print(f"❌ {name} not found")

# Tambah fungsi _jupiter_buy sebelum fungsi sell
jupiter_func = '''

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

'''

# Insert sebelum fungsi sell
if 'async def sell(' in content:
    content = content.replace('async def sell(', jupiter_func + 'async def sell(', 1)
    print("✅ _jupiter_buy function added")
else:
    print("❌ sell() not found for insertion point")

open('/root/pump_executor.py', 'w').write(content)
print("Done.")
