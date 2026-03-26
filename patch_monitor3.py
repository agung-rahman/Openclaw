content = open('/root/position_monitor_v2.py').read()

old = '''                                        result = await sell(mint, 100, symbol)
                                        if result.get("success"):
                                            positions[mint]["status"] = "closed"'''

new = '''                                        # Retry sell sampai 3x
                                        result = {"success": False, "error": "not attempted"}
                                        for _attempt in range(3):
                                            result = await sell(mint, 100, symbol)
                                            if result.get("success"):
                                                break
                                            logger.warning(f"{symbol}: sell attempt {_attempt+1}/3 gagal: {result.get('error')} — retry 5s")
                                            await asyncio.sleep(5)
                                        # Kalau masih gagal, cek balance
                                        if not result.get("success"):
                                            _bal_after = await get_token_balance(mint)
                                            if _bal_after == 0:
                                                logger.warning(f"{symbol}: sell gagal tapi balance 0 — mark closed")
                                                result = {"success": True, "tx": "sold-unknown"}
                                            else:
                                                logger.error(f"{symbol}: sell GAGAL 3x, token masih ada {_bal_after:.0f}")
                                                await asyncio.sleep(30)
                                                continue
                                        if result.get("success"):
                                            positions[mint]["status"] = "closed"'''

if old in content:
    content = content.replace(old, new)
    open('/root/position_monitor_v2.py', 'w').write(content)
    print("✅ monitor retry logic patched!")
else:
    print("❌ pattern not found lagi — debug:")
    idx = content.find('result = await sell(mint, 100, symbol)')
    print(repr(content[idx-10:idx+200]))
