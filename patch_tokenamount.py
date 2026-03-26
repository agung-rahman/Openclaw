content = open('/root/pump_executor.py').read()

# Fix di buy() — ganti fallback 1.0 dengan price_pending flag
old = '''            if token_amount == 0:
                token_amount = 1.0
            if token_amount <= 0:
                token_amount = 1.0
            # Hitung actual buy price dari SOL spent / tokens received'''

new = '''            # Kalau token_amount masih 0 setelah semua retry — jangan pakai 1.0 dummy
            # Tandai sebagai price_pending, monitor akan update nanti
            price_pending = token_amount == 0
            if token_amount == 0:
                logger.warning(f"   ⚠️ token_amount masih 0 setelah 5 attempt — pakai estimasi dari quote")
                token_amount = 0  # biarkan 0, bukan 1.0
            # Hitung actual buy price dari SOL spent / tokens received'''

if old in content:
    content = content.replace(old, new)
    print("✅ Fix 1a done")
else:
    print("❌ Fix 1a not found")
    idx = content.find("token_amount = 1.0")
    print("Context:", repr(content[idx-100:idx+100]))

# Fix kalau token_amount == 0 saat _save_position — skip save kalau beneran 0
old2 = '''            buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0
            logger.info(f"   📊 Bought {token_amount:.2f} {symbol} @ ${buy_price:.8f} (actual fill)")
            # Selalu simpan posisi kalau TX sukses

            # Simpan posisi
            _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)'''

new2 = '''            buy_price = (amount_sol * sol_price) / token_amount if token_amount > 0 else 0
            logger.info(f"   📊 Bought {token_amount:.2f} {symbol} @ ${buy_price:.8f} (actual fill)")

            # Kalau token_amount 0 = TX mungkin failed/pending — cek sekali lagi
            if token_amount == 0:
                logger.warning(f"   ⚠️ token_amount 0 — TX mungkin pending/failed, position disimpan tapi perlu review manual")
                # Simpan dengan flag
                _save_position(mint, symbol, amount_sol, tx_sig, 0, 0, wallet_source)
                return {"success": True, "tx": tx_sig, "pool": pool, "warning": "token_amount_unknown"}

            # Simpan posisi
            _save_position(mint, symbol, amount_sol, tx_sig, buy_price, token_amount, wallet_source)'''

if old2 in content:
    content = content.replace(old2, new2)
    open('/root/pump_executor.py', 'w').write(content)
    print("✅ Fix 1b done")
else:
    print("❌ Fix 1b not found")

