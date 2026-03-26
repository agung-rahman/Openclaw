content = open('/root/pump_executor.py').read()

old = '''        buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0
            logger.info(f"   📊 Bought {token_amount:.2f} {symbol} @ ${buy_price:.8f} (actual fill)")
            # Selalu simpan posisi kalau TX sukses
            
            # Simpan posisi
            _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)
            
            return {"success": True, "tx": tx_sig, "pool": pool}'''

new = '''            buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0
            logger.info(f"   📊 Bought {token_amount:.2f} {symbol} @ ${buy_price:.8f} (actual fill)")

            # Kalau token_amount 0 = TX mungkin pending — simpan dengan flag warning
            if token_amount == 0:
                logger.warning(f"   ⚠️ token_amount 0 — TX pending/failed, position disimpan untuk review")
                _save_position(mint, symbol, amount_sol, tx_sig, 0, 0, wallet_source)
                return {"success": True, "tx": tx_sig, "pool": pool, "warning": "token_amount_unknown"}

            # Simpan posisi
            _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)

            return {"success": True, "tx": tx_sig, "pool": pool}'''

if old in content:
    content = content.replace(old, new)
    open('/root/pump_executor.py', 'w').write(content)
    print("✅ Fix 1b done")
else:
    print("❌ not found")
    # debug indentasi exact
    idx = content.find('# Selalu simpan posisi kalau TX sukses')
    print(repr(content[idx-300:idx+200]))
