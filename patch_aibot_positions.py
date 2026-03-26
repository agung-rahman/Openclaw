content = open('/root/ai_bot.py').read()

old = '''    if intent == "check_positions":
        positions = load_positions()
        if not positions:
            await send("📭 Ga ada open positions saat ini.")
            return
        msg = "📊 <b>Open Positions:</b>\\n\\n"
        for mint, pos in positions.items():
            sym = pos.get("token_symbol", "?")
            invested = pos.get("amount_invested_usd", 0)
            tp1 = "✅" if pos.get("tp1_hit") else "❌"
            msg += f"• <b>{sym}</b>: ${invested:.2f} | TP1: {tp1}\\n"
        await send(msg)'''

new = '''    if intent == "check_positions":
        positions = load_positions()
        open_pos = {k: v for k, v in positions.items() if v.get("status") == "open"}
        if not open_pos:
            await send("📭 Ga ada open positions saat ini.")
            return
        msg = f"📊 <b>{len(open_pos)} Open Positions:</b>\\n\\n"
        import sys as _sys2; _sys2.path.insert(0, '/root')
        try:
            from pump_executor import get_token_price_usd as _gtp2
        except:
            _gtp2 = None
        for mint, pos in open_pos.items():
            sym = pos.get("token_symbol", "?")
            invested_sol = pos.get("amount_invested_sol", 0.02)
            buy_price = pos.get("buy_price_usd", 0)
            buy_time = pos.get("buy_time", "")
            age_min = ""
            if buy_time:
                from datetime import datetime as _dt2
                age_sec = (_dt2.now() - _dt2.fromisoformat(buy_time)).total_seconds()
                age_min = f"{age_sec/60:.0f}m"
            wallet = pos.get("wallet_source", "?")
            msg += f"• <b>{sym}</b> | {invested_sol} SOL | {age_min} | 👛 {wallet}\\n  CA: <code>{mint[:20]}...</code>\\n\\n"
        await send(msg)'''

if old in content:
    content = content.replace(old, new)
    open('/root/ai_bot.py', 'w').write(content)
    print("✅ check_positions fixed!")
else:
    print("❌ pattern not found")
