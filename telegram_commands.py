"""
telegram_commands.py - Command handler untuk kontrol trader via Telegram
Tambahkan ini ke degen_hunter.py

Commands yang tersedia:
/positions  - lihat open positions + PnL
/balance    - cek balance SOL wallet
/sell <symbol> - sell token tertentu
/sell all   - sell semua posisi
/sell <symbol> <pct> - sell sebagian (misal: /sell lolcoin 50)
/pause      - pause auto-trading (ga beli baru)
/resume     - resume auto-trading
/status     - status bot keseluruhan
/help       - list semua commands
"""

import asyncio
import os
import sys
sys.path.insert(0, '/root')

from telethon import events
import httpx

# ── Helper ─────────────────────────────────────────────────────────
async def bot_reply(BOT_TOKEN, chat_id, text):
    async with httpx.AsyncClient() as http:
        # Kirim tanpa parse_mode biar ga error karakter special
        await http.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10
        )

# ── State ──────────────────────────────────────────────────────────
TRADING_PAUSED = False

# ── Register handlers ke tg_client ─────────────────────────────────
def register_command_handlers(tg_client, trader, executor, CHAT_ID, BOT_TOKEN=''):

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!help'))
    async def cmd_help(event):
        await bot_reply(BOT_TOKEN, CHAT_ID, 
            "🤖 **OpenClaw Commands**\n\n"
            "/positions — lihat open positions + PnL\n"
            "/balance — cek SOL balance\n"
            "!sell `<symbol>` — sell token (contoh: /sell lolcoin)\n"
            "!sell `<symbol>` `<pct>` — sell sebagian (contoh: /sell lolcoin 50)\n"
            "!sell all — sell semua posisi\n"
            "/pause — pause auto-buy\n"
            "/resume — resume auto-buy\n"
            "/status — status bot\n"
            "/help — list commands"
        )

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!positions'))
    async def cmd_positions(event):
        from pathlib import Path
        import json

        positions_file = Path("/root/.openclaw_positions.json")
        if not positions_file.exists():
            await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions")
            return

        positions = json.loads(positions_file.read_text())
        if not positions:
            await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions")
            return

        msg = "📊 **OPEN POSITIONS**\n\n"
        for mint, pos in positions.items():
            symbol = pos.get("token_symbol", "?")
            buy_price = pos.get("buy_price_usd", 0)
            amount = pos.get("amount_token", 0)
            invested = pos.get("amount_invested_usd", 0)
            tp1_hit = pos.get("tp1_hit", False)

            # Get current price
            try:
                current_price = await executor.get_token_price_usd(mint)
                if current_price:
                    pnl_pct = ((current_price - buy_price) / buy_price) * 100
                    current_value = amount * current_price
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                else:
                    pnl_pct = 0
                    current_value = invested
                    pnl_emoji = "⚪"
                    current_price = 0
            except:
                pnl_pct = 0
                current_value = invested
                pnl_emoji = "⚪"
                current_price = 0

            msg += (
                f"{'🎯' if tp1_hit else '🪙'} **{symbol}**\n"
                f"   Amount: {amount:,.0f} tokens\n"
                f"   Buy: ${buy_price:.8f}\n"
                f"   Now: ${current_price:.8f}\n"
                f"   {pnl_emoji} PnL: {pnl_pct:+.1f}% (${current_value:.2f})\n"
                f"   TP1: {'✅' if tp1_hit else '❌'}\n\n"
            )

        await bot_reply(BOT_TOKEN, CHAT_ID, msg)

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!balance'))
    async def cmd_balance(event):
        try:
            from wallet_manager import get_public_key
            import aiohttp, json

            pub_key = get_public_key()
            rpc_url = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"

            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0", "id": 1,
                    "method": "getBalance",
                    "params": [pub_key]
                }
                async with session.post(rpc_url, json=payload) as resp:
                    data = await resp.json()
                    lamports = data.get("result", {}).get("value", 0)
                    sol = lamports / 1_000_000_000

            sol_price = await executor.get_sol_price_usd()
            usd_value = sol * sol_price

            await bot_reply(BOT_TOKEN, CHAT_ID, 
                f"💰 **Wallet Balance**\n\n"
                f"SOL: {sol:.4f}\n"
                f"USD: ${usd_value:.2f}\n"
                f"Address: `{pub_key[:20]}...`"
            )
        except Exception as e:
            await bot_reply(BOT_TOKEN, CHAT_ID, f"❌ Error: {e}")

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!sell'))
    async def cmd_sell(event):
        import json
        from pathlib import Path
        from trade_executor import Position
        from datetime import datetime

        text = event.message.message.strip()
        parts = text.split()

        # Parse command
        # /sell lolcoin
        # /sell lolcoin 50
        # /sell all

        if len(parts) < 2:
            await bot_reply(BOT_TOKEN, CHAT_ID, "❌ Format: /sell <symbol> atau /sell all\nContoh: /sell lolcoin")
            return

        symbol_input = parts[1].lower()
        pct = float(parts[2]) if len(parts) >= 3 else 100.0

        positions_file = Path("/root/.openclaw_positions.json")
        if not positions_file.exists():
            await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions")
            return

        positions = json.loads(positions_file.read_text())

        # Sell all
        if symbol_input == "all":
            if not positions:
                await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions")
                return

            await bot_reply(BOT_TOKEN, CHAT_ID, f"⏳ Selling semua {len(positions)} posisi...")

            results = []
            for mint, pos_data in list(positions.items()):
                sym = pos_data.get("token_symbol", "?")
                pos = Position(
                    token_mint=mint,
                    token_symbol=sym,
                    buy_price_usd=pos_data.get("buy_price_usd", 0),
                    amount_token=pos_data.get("amount_token", 0),
                    amount_invested_usd=pos_data.get("amount_invested_usd", 0),
                    buy_time=datetime.now(),
                    tp1_hit=pos_data.get("tp1_hit", False),
                )
                tx = await executor.sell_token(pos, sell_pct=1.0, reason="MANUAL_SELL_ALL")
                if tx:
                    results.append(f"✅ {sym}: [TX](https://solscan.io/tx/{tx})")
                    del positions[mint]
                else:
                    results.append(f"❌ {sym}: GAGAL")

            positions_file.write_text(json.dumps(positions, indent=2))
            await bot_reply(BOT_TOKEN, CHAT_ID, "**Hasil Sell All:**\n" + "\n".join(results))
            return

        # Sell specific token
        target_mint = None
        target_pos = None
        for mint, pos_data in positions.items():
            if pos_data.get("token_symbol", "").lower() == symbol_input:
                target_mint = mint
                target_pos = pos_data
                break

        if not target_pos:
            await bot_reply(BOT_TOKEN, CHAT_ID, 
                f"❌ Token '{symbol_input}' tidak ditemukan\n"
                f"Ketik /positions untuk lihat posisi yang ada"
            )
            return

        sym = target_pos.get("token_symbol", "?")
        amount = target_pos.get("amount_token", 0)

        await bot_reply(BOT_TOKEN, CHAT_ID, f"⏳ Selling {pct:.0f}% {sym}...")

        pos = Position(
            token_mint=target_mint,
            token_symbol=sym,
            buy_price_usd=target_pos.get("buy_price_usd", 0),
            amount_token=amount,
            amount_invested_usd=target_pos.get("amount_invested_usd", 0),
            buy_time=datetime.now(),
            tp1_hit=target_pos.get("tp1_hit", False),
        )

        tx = await executor.sell_token(pos, sell_pct=pct/100, reason="MANUAL_SELL")

        if tx:
            if pct >= 100:
                del positions[target_mint]
                positions_file.write_text(json.dumps(positions, indent=2))
                await bot_reply(BOT_TOKEN, CHAT_ID, 
                    f"✅ **{sym} SOLD!**\n"
                    f"[Lihat TX](https://solscan.io/tx/{tx})"
                )
            else:
                positions[target_mint]["amount_token"] = amount * (1 - pct/100)
                positions_file.write_text(json.dumps(positions, indent=2))
                await bot_reply(BOT_TOKEN, CHAT_ID, 
                    f"✅ **{sym} {pct:.0f}% SOLD!**\n"
                    f"Sisa: {100-pct:.0f}%\n"
                    f"[Lihat TX](https://solscan.io/tx/{tx})"
                )
        else:
            await bot_reply(BOT_TOKEN, CHAT_ID, f"❌ Sell {sym} GAGAL! Coba via Phantom/Jupiter")

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!pause'))
    async def cmd_pause(event):
        global TRADING_PAUSED
        TRADING_PAUSED = True
        # Set flag di trader juga
        if hasattr(trader, 'paused'):
            trader.paused = True
        await bot_reply(BOT_TOKEN, CHAT_ID, 
            "⏸️ **Auto-trading PAUSED**\n"
            "Bot masih monitor posisi yang ada tapi ga beli baru.\n"
            "Ketik /resume untuk lanjut."
        )

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!resume'))
    async def cmd_resume(event):
        global TRADING_PAUSED
        TRADING_PAUSED = False
        if hasattr(trader, 'paused'):
            trader.paused = False
        await bot_reply(BOT_TOKEN, CHAT_ID, "▶️ **Auto-trading RESUMED**\nBot aktif lagi!")

    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!status'))
    async def cmd_status(event):
        import json
        from pathlib import Path

        positions_file = Path("/root/.openclaw_positions.json")
        positions = {}
        if positions_file.exists():
            positions = json.loads(positions_file.read_text())

        paused_str = "⏸️ PAUSED" if TRADING_PAUSED else "▶️ ACTIVE"

        await bot_reply(BOT_TOKEN, CHAT_ID, 
            f"🤖 **OpenClaw Status**\n\n"
            f"Trading: {paused_str}\n"
            f"Open positions: {len(positions)}\n"
            f"Max positions: 3\n"
            f"Trade size: $3.00\n"
            f"TP1: 2x (sell 50%)\n"
            f"TP2: 3x (sell rest)\n"
            f"SL: -15%\n"
        )


    @tg_client.on(events.NewMessage(outgoing=True, pattern=r'^!analyze'))
    async def cmd_analyze(event):
        import httpx
        from datetime import datetime

        text = event.message.message.strip()
        parts = text.split()

        if len(parts) < 2:
            await bot_reply(BOT_TOKEN, CHAT_ID, "❌ Format: !analyze <token_address>\nContoh: !analyze GL4SNFE269B3oyD7KGYusiVH6TuYd1HpdrHcrFBLpump")
            return

        token_address = parts[1].strip()
        await bot_reply(BOT_TOKEN, CHAT_ID, f"🔍 Analyzing {token_address[:20]}...\nMohon tunggu ~10 detik...")

        try:
            async with httpx.AsyncClient() as http:
                # 1. DexScreener data
                resp = await http.get(
                    f"https://api.dexscreener.com/latest/dex/tokens/{token_address}",
                    timeout=10
                )
                dex_data = resp.json()
                pairs = dex_data.get("pairs", [])

                if not pairs:
                    await bot_reply(BOT_TOKEN, CHAT_ID, "❌ Token tidak ditemukan di DexScreener")
                    return

                pair = pairs[0]
                token_name = pair.get("baseToken", {}).get("name", "Unknown")
                token_symbol = pair.get("baseToken", {}).get("symbol", "?")
                dex_id = pair.get("dexId", "unknown")
                liquidity = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                market_cap = float(pair.get("marketCap", 0) or 0)
                volume_1h = float(pair.get("volume", {}).get("h1", 0) or 0)
                volume_24h = float(pair.get("volume", {}).get("h24", 0) or 0)
                price_1h = float(pair.get("priceChange", {}).get("h1", 0) or 0)
                price_6h = float(pair.get("priceChange", {}).get("h6", 0) or 0)
                price_24h = float(pair.get("priceChange", {}).get("h24", 0) or 0)
                buys_1h = pair.get("txns", {}).get("h1", {}).get("buys", 0)
                sells_1h = pair.get("txns", {}).get("h1", {}).get("sells", 0)
                total_txns = buys_1h + sells_1h
                buy_ratio = (buys_1h / total_txns * 100) if total_txns > 0 else 0
                created_at = pair.get("pairCreatedAt", 0)
                age_hours = (datetime.now().timestamp() - created_at / 1000) / 3600 if created_at else 0
                dex_url = pair.get("url", "")
                avg_hourly = volume_24h / 24 if volume_24h > 0 else 0
                spike = volume_1h / avg_hourly if avg_hourly > 0 else 0

                # 2. Rugcheck
                rug_resp = await http.get(
                    f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary",
                    timeout=10
                )
                rug_data = rug_resp.json()
                rug_score = rug_data.get("score", 0)
                risks = rug_data.get("risks", [])
                high_risks = [r.get("name") for r in risks if r.get("level") == "danger"]
                has_mint = any("mint" in r.get("name","").lower() for r in risks)
                has_freeze = any("freeze" in r.get("name","").lower() for r in risks)

                # 3. Narrative check
                import sys
                sys.path.insert(0, "/root")
                from narrative_manager import get_full_narrative_context
                narrative = await get_full_narrative_context(token_name, token_symbol, token_address)

                # 4. AI analysis via openclaw_trader
                if executor:
                    token_data = {
                        "mint": token_address,
                        "symbol": token_symbol,
                        "dex": dex_id,
                        "age_days": age_hours / 24,
                        "liquidity": liquidity,
                        "market_cap": market_cap,
                        "volume_spike": round(spike, 2),
                        "price_1h": price_1h,
                        "price_6h": price_6h,
                        "price_24h": price_24h,
                        "buy_ratio": round(buy_ratio, 1),
                        "txns_1h_buys": buys_1h,
                        "txns_1h_sells": sells_1h,
                        "rugcheck_score": rug_score,
                        "mint_enabled": has_mint,
                        "freeze_enabled": has_freeze,
                        "bundle_pct": 0,
                    }

                    # Jalanin AI analysis dari trader
                    try:
                        ai_result = await trader.ai_analyze(token_data, narrative)
                        ai_score = ai_result.get("score", 0)
                        ai_verdict = ai_result.get("verdict", "UNKNOWN")
                        ai_risk = ai_result.get("risk", "UNKNOWN")
                        ai_reasoning = ai_result.get("reasoning", "")
                    except Exception as e:
                        ai_score = 0
                        ai_verdict = "ERROR"
                        ai_risk = "UNKNOWN"
                        ai_reasoning = str(e)
                else:
                    ai_score = 0
                    ai_verdict = "NO_EXECUTOR"
                    ai_risk = "UNKNOWN"
                    ai_reasoning = "Executor not available"

                # Format response
                age_str = f"{age_hours:.1f}h" if age_hours < 48 else f"{age_hours/24:.1f}d"
                verdict_emoji = "🟢" if ai_verdict == "BUY" else "🔴"
                rug_emoji = "🟢" if rug_score >= 700 else "🟡" if rug_score >= 400 else "🔴"

                msg = (
                    f"{verdict_emoji} MANUAL ANALYZE: {token_name} (${token_symbol})\n\n"
                    f"📊 Market Data:\n"
                    f"DEX: {dex_id} | Age: {age_str}\n"
                    f"MC: ${market_cap:,.0f} | Liq: ${liquidity:,.0f}\n"
                    f"Vol 1h: ${volume_1h:,.0f} | Spike: {spike:.1f}x\n"
                    f"Buys/Sells 1h: {buys_1h}/{sells_1h} ({buy_ratio:.0f}% buys)\n"
                    f"Price 1h: {price_1h:+.1f}% | 6h: {price_6h:+.1f}% | 24h: {price_24h:+.1f}%\n\n"
                    f"{rug_emoji} Safety: {rug_score}/1000\n"
                    f"Mint: {'⚠️' if has_mint else '✅'} | Freeze: {'⚠️' if has_freeze else '✅'}\n"
                    f"Dangers: {', '.join(high_risks[:3]) if high_risks else 'None'}\n\n"
                    f"🤖 AI Score: {ai_score}/10 | {ai_verdict} | Risk: {ai_risk}\n"
                    f"📝 {ai_reasoning[:200]}\n\n"
                    f"🔗 {dex_url}"
                )

                await bot_reply(BOT_TOKEN, CHAT_ID, msg)

        except Exception as e:
            await bot_reply(BOT_TOKEN, CHAT_ID, f"❌ Error analyzing: {str(e)[:200]}")



    @tg_client.on(events.NewMessage(outgoing=True, chats=['@retarddegenmaxxingdisc_bot'], pattern=r'^(?!!|/).*'))
    async def cmd_natural_chat(event):
        """Handle natural language chat."""
        import sys
        sys.path.insert(0, '/root')
        from ai_assistant import (detect_intent, get_pnl_summary, 
                                   load_positions, save_pending_approval,
                                   load_pending_approval, clear_pending_approval)
        from risk_manager import get_risk_status, pause_trading, resume_trading

        text = event.message.message.strip()
        if not text or len(text) < 2:
            return

        # Cek kalau ini reply untuk approval pending
        pending = load_pending_approval()
        if pending:
            confirm_words = ['ya', 'yes', 'ok', 'oke', 'yep', 'beli', 'jual', 'gas', 'lanjut', 'confirm']
            cancel_words = ['tidak', 'no', 'cancel', 'batal', 'stop', 'ga', 'gak']
            
            text_lower = text.lower()
            if any(w in text_lower for w in confirm_words):
                action = pending.get("action")
                clear_pending_approval()
                
                if action == "sell_all":
                    await bot_reply(BOT_TOKEN, CHAT_ID, "⏳ Selling semua posisi...")
                    positions = load_positions()
                    if not positions:
                        await bot_reply(BOT_TOKEN, CHAT_ID, "Ga ada posisi yang perlu dijual.")
                        return
                    results = []
                    import json
                    from pathlib import Path
                    from trade_executor import Position
                    from datetime import datetime as dt
                    positions_file = Path("/root/.openclaw_positions.json")
                    for mint, pos_data in list(positions.items()):
                        sym = pos_data.get("token_symbol", "?")
                        pos = Position(
                            token_mint=mint, token_symbol=sym,
                            buy_price_usd=pos_data.get("buy_price_usd", 0),
                            amount_token=pos_data.get("amount_token", 0),
                            amount_invested_usd=pos_data.get("amount_invested_usd", 0),
                            buy_time=dt.now(), tp1_hit=pos_data.get("tp1_hit", False)
                        )
                        tx = await executor.sell_token(pos, sell_pct=1.0, reason="MANUAL_CHAT")
                        if tx:
                            results.append(f"✅ {sym} sold")
                            del positions[mint]
                        else:
                            results.append(f"❌ {sym} gagal")
                    positions_file.write_text(json.dumps(positions, indent=2))
                    await bot_reply(BOT_TOKEN, CHAT_ID, "Hasil:\n" + "\n".join(results))
                    return

            elif any(w in text_lower for w in cancel_words):
                clear_pending_approval()
                await bot_reply(BOT_TOKEN, CHAT_ID, "❌ Dibatalin deh.")
                return

        # Detect intent
        positions = load_positions()
        context = f"Open positions: {len(positions)}"
        
        result = await detect_intent(text, context)
        intent = result.get("intent", "general_chat")
        reply = result.get("reply", "")
        needs_confirmation = result.get("needs_confirmation", False)

        if intent == "check_positions":
            if not positions:
                await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions saat ini.")
                return
            msg = "📊 Open Positions:\n\n"
            for mint, pos in positions.items():
                sym = pos.get("token_symbol", "?")
                invested = pos.get("amount_invested_usd", 0)
                tp1 = "✅" if pos.get("tp1_hit") else "❌"
                msg += f"• {sym}: ${invested:.2f} | TP1: {tp1}\n"
            await bot_reply(BOT_TOKEN, CHAT_ID, msg)

        elif intent == "check_pnl":
            pnl = get_pnl_summary(7)
            emoji = "📈" if pnl["pnl_usd"] >= 0 else "📉"
            msg = (
                f"{emoji} PnL 7 hari:\n"
                f"Total: {'+' if pnl['pnl_usd'] >= 0 else ''}${pnl['pnl_usd']:.2f} ({pnl['pnl_pct']:+.1f}%)\n"
                f"Win rate: {pnl['win_rate']:.0f}% ({pnl['wins']}W/{pnl['losses']}L)"
            )
            await bot_reply(BOT_TOKEN, CHAT_ID, msg)

        elif intent == "check_balance":
            # Trigger !balance command logic
            try:
                from wallet_manager import get_public_key
                import aiohttp as ah
                pub_key = get_public_key()
                rpc_url = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"
                async with ah.ClientSession() as session:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub_key]}
                    async with session.post(rpc_url, json=payload) as resp:
                        data = await resp.json()
                        lamports = data.get("result", {}).get("value", 0)
                        sol = lamports / 1_000_000_000
                sol_price = await executor.get_sol_price_usd()
                await bot_reply(BOT_TOKEN, CHAT_ID, f"💰 Balance: {sol:.4f} SOL (${sol * sol_price:.2f})")
            except Exception as e:
                await bot_reply(BOT_TOKEN, CHAT_ID, f"❌ Error: {e}")

        elif intent == "sell_all":
            if not positions:
                await bot_reply(BOT_TOKEN, CHAT_ID, "Ga ada posisi yang bisa dijual bro.")
                return
            import json as json_mod
            from datetime import datetime as dt_mod
            from ai_assistant import save_pending_approval
            save_pending_approval({"action": "sell_all", "timestamp": dt_mod.now().isoformat()})
            await bot_reply(BOT_TOKEN, CHAT_ID, 
                f"⚠️ Mau jual semua {len(positions)} posisi?\nKetik 'ya' untuk konfirmasi atau 'batal' untuk cancel.")

        elif intent == "pause_trading":
            pause_trading("user request")
            await bot_reply(BOT_TOKEN, CHAT_ID, "⏸️ Trading di-pause. Ketik 'resume' kalau mau lanjut lagi.")

        elif intent == "resume_trading":
            resume_trading()
            await bot_reply(BOT_TOKEN, CHAT_ID, "▶️ Trading dilanjutkan!")

        elif intent == "market_info":
            status = get_risk_status()
            await bot_reply(BOT_TOKEN, CHAT_ID, reply + "\n\n" + status)

        elif intent == "analyze_token":
            addr = result.get("params", {}).get("address", "")
            if addr:
                await bot_reply(BOT_TOKEN, CHAT_ID, f"Analyzing {addr[:20]}... tunggu bentar 🔍")
                # Trigger analyze command
                event.message.message = f"!analyze {addr}"
                await cmd_analyze(event)
            else:
                await bot_reply(BOT_TOKEN, CHAT_ID, "Kasih token address-nya dong. Contoh: analyze <address>")

        else:
            # General chat - reply langsung dari AI
            if reply:
                await bot_reply(BOT_TOKEN, CHAT_ID, reply)



    @tg_client.on(events.NewMessage(outgoing=True, chats=['@retarddegenmaxxingdisc_bot'], pattern=r'^(?!!|/).*'))
    async def cmd_natural_chat(event):
        """Handle natural language chat."""
        import sys
        sys.path.insert(0, '/root')
        from ai_assistant import (detect_intent, get_pnl_summary, 
                                   load_positions, save_pending_approval,
                                   load_pending_approval, clear_pending_approval)
        from risk_manager import get_risk_status, pause_trading, resume_trading

        text = event.message.message.strip()
        if not text or len(text) < 2:
            return

        # Cek kalau ini reply untuk approval pending
        pending = load_pending_approval()
        if pending:
            confirm_words = ['ya', 'yes', 'ok', 'oke', 'yep', 'beli', 'jual', 'gas', 'lanjut', 'confirm']
            cancel_words = ['tidak', 'no', 'cancel', 'batal', 'stop', 'ga', 'gak']
            
            text_lower = text.lower()
            if any(w in text_lower for w in confirm_words):
                action = pending.get("action")
                clear_pending_approval()
                
                if action == "sell_all":
                    await bot_reply(BOT_TOKEN, CHAT_ID, "⏳ Selling semua posisi...")
                    positions = load_positions()
                    if not positions:
                        await bot_reply(BOT_TOKEN, CHAT_ID, "Ga ada posisi yang perlu dijual.")
                        return
                    results = []
                    import json
                    from pathlib import Path
                    from trade_executor import Position
                    from datetime import datetime as dt
                    positions_file = Path("/root/.openclaw_positions.json")
                    for mint, pos_data in list(positions.items()):
                        sym = pos_data.get("token_symbol", "?")
                        pos = Position(
                            token_mint=mint, token_symbol=sym,
                            buy_price_usd=pos_data.get("buy_price_usd", 0),
                            amount_token=pos_data.get("amount_token", 0),
                            amount_invested_usd=pos_data.get("amount_invested_usd", 0),
                            buy_time=dt.now(), tp1_hit=pos_data.get("tp1_hit", False)
                        )
                        tx = await executor.sell_token(pos, sell_pct=1.0, reason="MANUAL_CHAT")
                        if tx:
                            results.append(f"✅ {sym} sold")
                            del positions[mint]
                        else:
                            results.append(f"❌ {sym} gagal")
                    positions_file.write_text(json.dumps(positions, indent=2))
                    await bot_reply(BOT_TOKEN, CHAT_ID, "Hasil:\n" + "\n".join(results))
                    return

            elif any(w in text_lower for w in cancel_words):
                clear_pending_approval()
                await bot_reply(BOT_TOKEN, CHAT_ID, "❌ Dibatalin deh.")
                return

        # Detect intent
        positions = load_positions()
        context = f"Open positions: {len(positions)}"
        
        result = await detect_intent(text, context)
        intent = result.get("intent", "general_chat")
        reply = result.get("reply", "")
        needs_confirmation = result.get("needs_confirmation", False)

        if intent == "check_positions":
            if not positions:
                await bot_reply(BOT_TOKEN, CHAT_ID, "📭 Ga ada open positions saat ini.")
                return
            msg = "📊 Open Positions:\n\n"
            for mint, pos in positions.items():
                sym = pos.get("token_symbol", "?")
                invested = pos.get("amount_invested_usd", 0)
                tp1 = "✅" if pos.get("tp1_hit") else "❌"
                msg += f"• {sym}: ${invested:.2f} | TP1: {tp1}\n"
            await bot_reply(BOT_TOKEN, CHAT_ID, msg)

        elif intent == "check_pnl":
            pnl = get_pnl_summary(7)
            emoji = "📈" if pnl["pnl_usd"] >= 0 else "📉"
            msg = (
                f"{emoji} PnL 7 hari:\n"
                f"Total: {'+' if pnl['pnl_usd'] >= 0 else ''}${pnl['pnl_usd']:.2f} ({pnl['pnl_pct']:+.1f}%)\n"
                f"Win rate: {pnl['win_rate']:.0f}% ({pnl['wins']}W/{pnl['losses']}L)"
            )
            await bot_reply(BOT_TOKEN, CHAT_ID, msg)

        elif intent == "check_balance":
            # Trigger !balance command logic
            try:
                from wallet_manager import get_public_key
                import aiohttp as ah
                pub_key = get_public_key()
                rpc_url = f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY', '')}"
                async with ah.ClientSession() as session:
                    payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub_key]}
                    async with session.post(rpc_url, json=payload) as resp:
                        data = await resp.json()
                        lamports = data.get("result", {}).get("value", 0)
                        sol = lamports / 1_000_000_000
                sol_price = await executor.get_sol_price_usd()
                await bot_reply(BOT_TOKEN, CHAT_ID, f"💰 Balance: {sol:.4f} SOL (${sol * sol_price:.2f})")
            except Exception as e:
                await bot_reply(BOT_TOKEN, CHAT_ID, f"❌ Error: {e}")

        elif intent == "sell_all":
            if not positions:
                await bot_reply(BOT_TOKEN, CHAT_ID, "Ga ada posisi yang bisa dijual bro.")
                return
            import json as json_mod
            from datetime import datetime as dt_mod
            from ai_assistant import save_pending_approval
            save_pending_approval({"action": "sell_all", "timestamp": dt_mod.now().isoformat()})
            await bot_reply(BOT_TOKEN, CHAT_ID, 
                f"⚠️ Mau jual semua {len(positions)} posisi?\nKetik 'ya' untuk konfirmasi atau 'batal' untuk cancel.")

        elif intent == "pause_trading":
            pause_trading("user request")
            await bot_reply(BOT_TOKEN, CHAT_ID, "⏸️ Trading di-pause. Ketik 'resume' kalau mau lanjut lagi.")

        elif intent == "resume_trading":
            resume_trading()
            await bot_reply(BOT_TOKEN, CHAT_ID, "▶️ Trading dilanjutkan!")

        elif intent == "market_info":
            status = get_risk_status()
            await bot_reply(BOT_TOKEN, CHAT_ID, reply + "\n\n" + status)

        elif intent == "analyze_token":
            addr = result.get("params", {}).get("address", "")
            if addr:
                await bot_reply(BOT_TOKEN, CHAT_ID, f"Analyzing {addr[:20]}... tunggu bentar 🔍")
                # Trigger analyze command
                event.message.message = f"!analyze {addr}"
                await cmd_analyze(event)
            else:
                await bot_reply(BOT_TOKEN, CHAT_ID, "Kasih token address-nya dong. Contoh: analyze <address>")

        else:
            # General chat - reply langsung dari AI
            if reply:
                await bot_reply(BOT_TOKEN, CHAT_ID, reply)


    print("✅ Telegram command handlers registered!")
    return TRADING_PAUSED
