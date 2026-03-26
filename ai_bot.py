"""
ai_bot.py - Telegram Bot API polling untuk AI assistant
Terpisah dari scanner, pure respond ke user aja
"""

import asyncio
import aiohttp
import json
import os
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "5664251521"))
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

POSITIONS_FILE = Path("/root/.openclaw_positions.json")
CHAT_HISTORY_FILE = Path("/root/.chat_history.json")
MAX_HISTORY = 10

def load_history() -> list:
    if CHAT_HISTORY_FILE.exists():
        return json.loads(CHAT_HISTORY_FILE.read_text())
    return []

def save_history(history: list):
    if len(history) > MAX_HISTORY * 2:
        history = history[-(MAX_HISTORY * 2):]
    CHAT_HISTORY_FILE.write_text(json.dumps(history, indent=2))

def add_to_history(role: str, content_text: str):
    history = load_history()
    history.append({"role": role, "content": content_text})
    save_history(history)
TRADE_HISTORY_FILE = Path("/root/.trade_history.json")
PENDING_FILE = Path("/root/.pending_approval.json")

SYSTEM_PROMPT = """Kamu adalah AI assistant untuk crypto trading bot Solana milik user.
Kamu harus ngerti maksud user meskipun bahasanya ga formal, typo, singkatan, atau campur bahasa.
Kamu adalah teman degen trader yang ngerti crypto slang Indonesia & English.

Contoh pemahaman:
- "gmn posisi w" / "ada hold apa" / "lg pegang apa" / "porto gw" / "lagi megang apa" → check_positions
- "cuan brp" / "profit w gmn" / "dapet brp" / "rugi ga" / "PnL" / "hasil trading" → check_pnl  
- "duit gw" / "saldo" / "SOL gw brp" / "balance" / "modal" / "isi wallet" → check_balance
- "ada alpha?" / "info alpha" / "kasih alpha" / "ada info?" / "infokan" / "infoin" / "minta alpha" / "alpha dong" / "gem apa" / "ada yang bagus?" / "rekomen token" / "market gimana" / "update market" / "ada sinyal?" / "signal apa" / "ada gem" / "update dong" / "token bagus ga" / "ada yang menarik?" / "pantauan gimana" / "ada berita?" / "briefing dong" / "rekap signal" / "gem hunter" / "ada apa nih" / "info dong" → check_signals
- "research [mint]" / "analisa [token]" / "cek [token]" / "deep dive" / "riset [token]" / "dyor [token]" → deep_research
- "chart [mint]" / "ta [mint]" / "grafik" / "technical" / "price action" → chart_analysis  
- "full [mint]" / "analisa lengkap" / "full research" / "semua info" → full_analysis
- "jual smua" / "cut semua" / "liquidate" / "cabut" / "exit semua" → sell_all
- "sell SYMBOL" / "jual SYMBOL" / "cut SYMBOL" → sell_symbol (target = symbol name)
- "sell SYMBOL MINTADDRESS" / "force sell SYMBOL MINT" → force_sell (target = "SYMBOL MINT")
- "add SYMBOL MINT" / "tambah SYMBOL MINT" → add_position (target = "SYMBOL MINT")
- "buy MINT" / "beli MINT" / "ape MINT" / "masuk MINT" → manual_buy (target = mint address)
- "stop dulu" / "pause" / "istirahat" / "off kan" / "jangan trade dulu" → pause_trading
- "lanjut" / "nyalain" / "gas lagi" / "resume" / "trade lagi" → resume_trading
- "status trading" / "performa bot" / "hasil trading" / "bot gimana" / "trading hari ini" / "udah cuan?" / "bot udah trade?" → trading_status
- apapun yang ga masuk kategori → general_chat, jawab natural dan helpful sebagai teman trader

Respond HANYA dengan JSON valid:
{
  "intent": "<check_positions|check_pnl|check_balance|check_signals|deep_research|chart_analysis|full_analysis|sell_all|sell_symbol|force_sell|pause_trading|resume_trading|trading_status|manual_buy|general_chat>",
  "target": "<mint address atau token symbol kalau intent deep_research, kosong kalau ga ada>",
  "reply": "<jawaban natural dalam bahasa yang sama dengan user, kasual dan friendly>",
  "needs_confirmation": <true hanya untuk sell_all>
}

Bahasa: ikutin bahasa user. Kalau Indo → Indo kasual. Kalau English → English casual.
Jangan kaku, jangan formal. Kamu kayak temen trader yang ngerti crypto."""


async def send(text: str, parse_mode: str = "HTML"):
    async with aiohttp.ClientSession() as s:
        r = await s.post(f"{API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": parse_mode
        })
        data = await r.json()
        if not data.get("ok"):
            # Retry tanpa parse_mode kalau error
            logger.warning(f"Send failed: {data.get('description')}, retrying plain...")
            await s.post(f"{API}/sendMessage", json={
                "chat_id": CHAT_ID,
                "text": text,
            })


async def get_updates(offset: int) -> list:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API}/getUpdates", params={
                "offset": offset, "timeout": 30, "allowed_updates": ["message"]
            }, timeout=aiohttp.ClientTimeout(total=35)) as r:
                data = await r.json()
                return data.get("result", [])
    except:
        return []


def load_positions() -> dict:
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text())
    return {}


def get_pnl(days=7) -> dict:
    if not TRADE_HISTORY_FILE.exists():
        return {"pnl_usd": 0, "pnl_pct": 0, "wins": 0, "losses": 0, "win_rate": 0}
    history = json.loads(TRADE_HISTORY_FILE.read_text())
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    invested = returned = wins = losses = 0
    for t in history:
        try:
            if datetime.fromisoformat(t["timestamp"]) < cutoff:
                continue
            i = t.get("amount_invested_usd", 0)
            r = t.get("amount_returned_usd", 0)
            invested += i; returned += r
            if r > i: wins += 1
            else: losses += 1
        except: continue
    pnl = returned - invested
    return {
        "pnl_usd": pnl,
        "pnl_pct": (pnl/invested*100) if invested > 0 else 0,
        "wins": wins, "losses": losses,
        "win_rate": (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
    }


async def detect_intent(text: str) -> dict:
    # Rule-based fallback dulu — ga perlu LLM untuk command yang jelas
    import re as _re
    t = text.strip().lower()
    # Sell
    if _re.match(r'^(sell|jual|cut)\s+\S+', t):
        return {"intent": "sell_symbol", "target": text.strip().split()[1], "reply": "", "needs_confirmation": False}
    # Research
    if _re.match(r'^(research|analisa|cek|riset|dyor)\s+\S+', t):
        return {"intent": "deep_research", "target": text.strip().split()[1], "reply": "", "needs_confirmation": False}
    # Full analysis
    if _re.match(r'^(full)\s+\S+', t):
        return {"intent": "full_analysis", "target": text.strip().split()[1], "reply": "", "needs_confirmation": False}
    # Chart
    if _re.match(r'^(chart|ta|grafik)\s+\S+', t):
        return {"intent": "chart_analysis", "target": text.strip().split()[1], "reply": "", "needs_confirmation": False}
    # Positions
    if any(w in t for w in ['posisi', 'porto', 'pegang', 'hold', 'position']):
        return {"intent": "check_positions", "target": "", "reply": "", "needs_confirmation": False}
    # Balance
    if any(w in t for w in ['balance', 'saldo', 'duit', 'sol gw', 'modal']):
        return {"intent": "check_balance", "target": "", "reply": "", "needs_confirmation": False}
    # PnL
    if any(w in t for w in ['pnl', 'profit', 'cuan', 'rugi', 'hasil']):
        return {"intent": "check_pnl", "target": "", "reply": "", "needs_confirmation": False}
    # Status
    if any(w in t for w in ['status', 'performa', 'bot gimana', 'udah trade', 'trading hari']):
        return {"intent": "trading_status", "target": "", "reply": "", "needs_confirmation": False}
    # Pause/resume
    if any(w in t for w in ['pause', 'stop dulu', 'jangan trade', 'istirahat']):
        return {"intent": "pause_trading", "target": "", "reply": "", "needs_confirmation": False}
    if any(w in t for w in ['resume', 'lanjut', 'gas lagi', 'trade lagi', 'nyalain']):
        return {"intent": "resume_trading", "target": "", "reply": "", "needs_confirmation": False}
    # Signals
    if any(w in t for w in ['signal', 'alpha', 'gem', 'info', 'update', 'ada apa']):
        return {"intent": "check_signals", "target": "", "reply": "", "needs_confirmation": False}
    # Sell all
    if any(w in t for w in ['sell all', 'jual semua', 'liquidate', 'cabut', 'exit semua', 'cut semua']):
        return {"intent": "sell_all", "target": "", "reply": "", "needs_confirmation": True}
    # Manual buy
    import re as _re2
    _buy_m = _re2.match(r'^(buy|beli|ape|masuk)\s+([A-Za-z0-9]{30,})', text.strip(), _re2.IGNORECASE)
    if _buy_m:
        return {"intent": "manual_buy", "target": _buy_m.group(2), "reply": "", "needs_confirmation": False}

    # Fallback ke LLM kalau rule-based ga nangkep
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": "mistralai/mistral-small-3.1-24b-instruct", "max_tokens": 300,
                      "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                   {"role": "user", "content": text}]},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await r.json()
                if "choices" not in data:
                    raise Exception(f"No choices: {data.get('error', data)}")
                content = data["choices"][0]["message"]["content"]
                import re
                content = re.sub(r'```json|```', '', content).strip()
                return json.loads(content)
    except Exception as e:
        logger.error(f"Intent error: {e}")
        return {"intent": "general_chat", "reply": "Ketik 'help' untuk lihat command yang tersedia.", "needs_confirmation": False}



async def handle_message(text: str):
    text = text.strip()
    if not text:
        return

    # Shortcut: sell command bypass LLM
    import re as _re
    _sm = _re.match(r'^(sell|jual|cut)\s+(\S+)(?:\s+(\S+))?$', text, _re.IGNORECASE)
    if _sm:
        _sym = _sm.group(2).upper()
        _mint_arg = _sm.group(3)
        positions = load_positions()
        found = None
        found_mint = None
        for _m, _p in positions.items():
            if _p.get("token_symbol","").upper() == _sym and _p.get("status") == "open":
                found = _p
                found_mint = _m
                break
        if not found_mint and _mint_arg and len(_mint_arg) > 30:
            found_mint = _mint_arg
        if not found_mint:
            await send(f"❌ Posisi open untuk {_sym} ga ditemukan.\nKalau token masih di wallet:\nsell {_sym} <MINT_ADDRESS>")
            return
        await send(f"⏳ Selling {_sym}...")
        try:
            import sys as _sys
            _sys.path.insert(0, '/root')
            from pump_executor import sell as _sell, get_token_balance as _gtb
            _bal = await _gtb(found_mint)
            if _bal == 0:
                if found:
                    found["status"] = "closed"
                    found["close_reason"] = "manual sell via TG - no balance"
                    found["close_time"] = datetime.now().isoformat()
                    POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
                await send(f"⚠️ Balance {_sym} = 0, posisi di-close.")
                return
            _result = await _sell(found_mint, 100, _sym)
            if _result.get("success"):
                if found:
                    found["status"] = "closed"
                    found["close_reason"] = "manual sell via TG"
                    found["close_time"] = datetime.now().isoformat()
                    POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
                await send(f"✅ <b>{_sym}</b> berhasil di-sell!\n🔗 TX: https://solscan.io/tx/{_result['tx']}")
            else:
                await send(f"❌ Sell gagal: {_result.get('error','unknown')}")
        except Exception as _e:
            await send(f"❌ Error: {_e}")
        return

    # Cek pending approval
    if PENDING_FILE.exists():
        pending = json.loads(PENDING_FILE.read_text())
        ts = datetime.fromisoformat(pending.get("timestamp", "2000-01-01"))
        if (datetime.now() - ts).seconds < 300:
            confirm = any(w in text.lower() for w in ['ya','yes','ok','oke','gas','lanjut','beli','jual'])
            cancel = any(w in text.lower() for w in ['tidak','no','cancel','batal','ga','gak'])
            if confirm:
                PENDING_FILE.unlink()
                action = pending.get("action")
                if action == "sell_all":
                    positions = load_positions()
                    if not positions:
                        await send("Ga ada posisi yang perlu dijual.")
                        return
                    await send(f"⏳ Executing sell all {len(positions)} posisi...")
                    Path("/root/.sell_all_signal").write_text("1")
                    await send("✅ Signal sell all dikirim ke trader!")
                elif action == "manual_buy":
                    _mint = pending.get("mint", "")
                    _sym = pending.get("symbol", "UNKNOWN")
                    _score = pending.get("score", 0)
                    await send(f"⏳ Executing buy <b>{_sym}</b>...")
                    try:
                        import sys as _sys
                        _sys.path.insert(0, '/root')
                        from pump_executor import buy as _buy
                        import json as _j
                        from pathlib import Path as _Path
                        cfg = _j.loads(_Path("/root/.risk_config.json").read_text())
                        amount = cfg.get("trade_amount_sol", 0.02)
                        res = await _buy(_mint, amount, _sym)
                        if res.get("success"):
                            await send(
                                f"✅ <b>BUY {_sym} berhasil!</b>\n"
                                f"💰 {amount} SOL\n"
                                f"📊 Score: {_score:.0f}/100\n"
                                f"🎯 TP/SL monitor otomatis aktif\n"
                                f"🔗 TX: https://solscan.io/tx/{res['tx']}\n"
                                f"📋 CA: <code>{_mint}</code>"
                            )
                        else:
                            await send(f"❌ Buy gagal: {res.get('error','unknown')}")
                    except Exception as _e:
                        await send(f"❌ Error: {_e}")
                return
            elif cancel:
                PENDING_FILE.unlink()
                await send("❌ Dibatalin.")
                return

    result = await detect_intent(text)
    intent = result.get("intent", "general_chat")
    logger.info(f"Intent detected: {intent} | text: {text[:30]}")
    reply = result.get("reply", "")

    if intent == "check_positions":
        positions = load_positions()
        open_pos = {k: v for k, v in positions.items() if v.get("status") == "open"}
        if not open_pos:
            await send("📭 Ga ada open positions saat ini.")
            return
        msg = f"📊 <b>{len(open_pos)} Open Positions:</b>\n\n"
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
            msg += f"• <b>{sym}</b> | {invested_sol} SOL | {age_min} | 👛 {wallet}\n  CA: <code>{mint[:20]}...</code>\n\n"
        await send(msg)

    elif intent == "check_pnl":
        p = get_pnl(7)
        emoji = "📈" if p["pnl_usd"] >= 0 else "📉"
        await send(
            f"{emoji} <b>PnL 7 hari:</b>\n"
            f"Total: {'+' if p['pnl_usd']>=0 else ''}${p['pnl_usd']:.2f} ({p['pnl_pct']:+.1f}%)\n"
            f"Win rate: {p['win_rate']:.0f}% ({p['wins']}W/{p['losses']}L)"
        )

    elif intent == "sell_all":
        positions = load_positions()
        if not positions:
            await send("Ga ada posisi bro.")
            return
        PENDING_FILE.write_text(json.dumps({
            "action": "sell_all",
            "timestamp": datetime.now().isoformat()
        }))
        await send(f"⚠️ Mau jual semua <b>{len(positions)} posisi</b>?\nKetik 'ya' untuk konfirmasi atau 'batal' untuk cancel.")

    elif intent == "sell_symbol":
        symbol_target = result.get("target", "").upper().strip()
        if not symbol_target:
            await send("Format: sell SYMBOL (contoh: sell GODZILLA)")
            return
        positions = load_positions()
        found = None
        found_mint = None
        for mint, p in positions.items():
            if p.get("token_symbol", "").upper() == symbol_target and p.get("status") == "open":
                found = p
                found_mint = mint
                break
        if not found:
            # Posisi ga ketemu di file — minta mint address untuk force sell
            await send(f"❌ Posisi open untuk {symbol_target} ga ditemukan di file.\nKalau token masih ada di wallet, ketik:\nsell {symbol_target} <MINT_ADDRESS>")
            return
        await send(f"⏳ Selling {symbol_target}...")
        try:
            import sys
            sys.path.insert(0, '/root')
            from pump_executor import sell as _sell, get_token_balance as _gtb
            # Cek balance dulu
            bal = await _gtb(found_mint)
            if bal == 0:
                # Mark closed kalau balance 0
                found["status"] = "closed"
                found["close_reason"] = "manual close via TG - no balance"
                found["close_time"] = datetime.now().isoformat()
                Path("/root/.openclaw_positions.json").write_text(json.dumps(positions, indent=2))
                await send(f"⚠️ Balance {symbol_target} = 0, posisi di-close.")
                return
            result_sell = await _sell(found_mint, 100, symbol_target)
            if result_sell.get("success"):
                found["status"] = "closed"
                found["close_reason"] = "manual sell via TG"
                found["close_time"] = datetime.now().isoformat()
                Path("/root/.openclaw_positions.json").write_text(json.dumps(positions, indent=2))
                await send(f"✅ <b>{symbol_target}</b> berhasil di-sell!\n🔗 TX: https://solscan.io/tx/{result_sell['tx']}")
            else:
                await send(f"❌ Sell gagal: {result_sell.get('error','unknown')}")
        except Exception as e:
            await send(f"❌ Error: {e}")

    elif intent == "force_sell":
        target = result.get("target", "").strip().split()
        if len(target) < 2:
            await send("Format: sell SYMBOL MINTADDRESS")
            return
        fs_symbol = target[0].upper()
        fs_mint = target[1]
        if len(fs_mint) < 30:
            await send("❌ Mint address tidak valid.")
            return
        await send(f"⏳ Force selling {fs_symbol}...")
        try:
            import sys
            sys.path.insert(0, '/root')
            from pump_executor import sell as _sell, get_token_balance as _gtb
            bal = await _gtb(fs_mint)
            if bal == 0:
                await send(f"❌ Balance {fs_symbol} = 0 di wallet.")
                return
            result_sell = await _sell(fs_mint, 100, fs_symbol)
            if result_sell.get("success"):
                # Update posisi file kalau ada
                positions = load_positions()
                if fs_mint in positions:
                    positions[fs_mint]["status"] = "closed"
                    positions[fs_mint]["close_reason"] = "force sell via TG"
                    positions[fs_mint]["close_time"] = datetime.now().isoformat()
                    Path("/root/.openclaw_positions.json").write_text(json.dumps(positions, indent=2))
                await send(f"✅ <b>{fs_symbol}</b> berhasil di-sell!\n🔗 TX: https://solscan.io/tx/{result_sell['tx']}")
            else:
                await send(f"❌ Sell gagal: {result_sell.get('error','unknown')}")
        except Exception as e:
            await send(f"❌ Error: {e}")

    elif intent == "add_position":
        target = result.get("target", "").strip()
        parts = target.split()
        if len(parts) < 2:
            await send("Format: add SYMBOL MINT\nContoh: add GODZILLA C18BXvYwPoTkDAFypyQHd...")
            return
        symbol_add = parts[0].upper()
        mint_add = parts[1]
        if len(mint_add) < 30:
            await send("❌ Mint address ga valid.")
            return
        await send(f"⏳ Cek balance {symbol_add}...")
        try:
            import sys
            sys.path.insert(0, '/root')
            from pump_executor import get_token_balance as _gtb, get_token_price_usd as _gtp
            bal = await _gtb(mint_add)
            if bal == 0:
                await send(f"❌ Balance {symbol_add} = 0 di wallet. Token ga ada atau mint address salah.")
                return
            price = await _gtp(mint_add)
            positions = load_positions()
            positions[mint_add] = {
                "token_symbol": symbol_add,
                "amount_invested_sol": 0.02,
                "buy_time": datetime.now().isoformat(),
                "tx_buy": "manual_add_tg",
                "status": "open",
                "buy_price_usd": price,
                "amount_token": bal,
                "wallet_source": "manual"
            }
            Path("/root/.openclaw_positions.json").write_text(json.dumps(positions, indent=2))
            await send(f"✅ <b>{symbol_add}</b> ditambah manual!\n💰 Balance: {bal:.2f} tokens\n📊 Buy price: ${price:.8f}\nTP/SL akan jalan otomatis.")
        except Exception as e:
            await send(f"❌ Error: {e}")

    elif intent == "pause_trading":
        cfg_file = Path("/root/.risk_config.json")
        cfg = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
        cfg["trading_paused"] = True
        cfg["pause_reason"] = "user request"
        cfg_file.write_text(json.dumps(cfg, indent=2))
        await send("⏸️ Trading di-pause.")

    elif intent == "resume_trading":
        cfg_file = Path("/root/.risk_config.json")
        cfg = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
        cfg["trading_paused"] = False
        cfg["pause_reason"] = ""
        cfg_file.write_text(json.dumps(cfg))
        await send("▶️ Trading dilanjutkan!")

    elif "detail signal" in text.lower() or "lihat detail" in text.lower():
        cache = Path("/root/.signal_detail_cache.json")
        if cache.exists():
            import json as _j; details = _j.loads(cache.read_text())
            await send(f"📋 Detail {len(details)} signal:")
            for d in details:
                await send(d)
            cache.unlink()
        else:
            await send("Ga ada cache detail signal. Ketik 'ada signal?' dulu.")
        return

    elif intent == "check_signals":
        try:
            from signal_queue import get_queue, clear_queue
            queue = get_queue()
            if not queue:
                await send("📭 Queue kosong, scanner lagi nyari.")
                return

            wallet_signals = [s for s in queue if s.get("type") == "wallet"]
            scanner_signals = [s for s in queue if s.get("type") != "wallet"]
            signals_text = "\n\n---\n\n".join([s["text"] for s in queue[-10:]])

            summary_prompt = f"""Berikut {len(queue)} signal token dari scanner & wallet tracker.
{len(wallet_signals)} dari wallet copytrade, {len(scanner_signals)} dari volume scanner.

PENTING: Nilai semua token, jangan skip berdasarkan rugcheck/bundle saja.
Kadang wallet masuk SEBELUM bundle terjadi atau early entry di token bagus.

Signal:
{signals_text}

Buat summary dalam bahasa Indonesia casual, max 6 kalimat:
1. Overview singkat
2. Top 2-3 token paling menarik + alasan (wallet siapa, MCap, momentum)
3. Token yang perlu extra hati-hati + kenapa
4. Verdict: GAS / WAIT / SKIP

Format baris terakhir: VERDICT: [GAS/WAIT/SKIP]"""

            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                    json={"model": "mistralai/mistral-small-3.1-24b-instruct", "max_tokens": 400,
                          "messages": [{"role": "user", "content": summary_prompt}]},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as r:
                    data = await r.json()
                    summary = data["choices"][0]["message"]["content"]

            msg = (
                f"📡 <b>{len(queue)} signal</b> "
                f"({len(wallet_signals)} wallet, {len(scanner_signals)} scanner)\n\n"
                f"{summary}\n\n"
                f"Ketik <b>'detail signal'</b> buat liat semua detail."
            )
            add_to_history("assistant", msg)
            await send(msg)
            Path("/root/.signal_detail_cache.json").write_text(
                __import__("json").dumps([s["text"] for s in queue])
            )
            clear_queue()
        except Exception as e:
            logger.error(f"check_signals error: {e}", exc_info=True)
            await send(f"❌ Error: {e}")

    elif intent == "deep_research":
        target = result.get("target", "").strip()
        if not target:
            await send("Kasih mint address atau symbol tokennya bro, contoh: 'research BHvsujaabxvm9...'")
        else:
            await send(f"🔬 Lagi deep research <b>{target}</b>... tunggu ~10 detik")
            try:
                import sys, subprocess
                sys.path.insert(0, '/root')
                if len(target) > 30:
                    import os
                    # Auto-fetch symbol dari pump.fun
                    symbol = ""
                    try:
                        async with aiohttp.ClientSession() as _s:
                            async with _s.get(f"https://frontend-api.pump.fun/coins/{target}", timeout=aiohttp.ClientTimeout(total=5)) as _r:
                                _d = await _r.json()
                                symbol = _d.get("symbol", "") or ""
                    except:
                        pass
                    if not symbol:
                        try:
                            async with aiohttp.ClientSession() as _s2:
                                async with _s2.get(f"https://api.dexscreener.com/latest/dex/tokens/{target}", timeout=aiohttp.ClientTimeout(total=5)) as _r2:
                                    _dex = await _r2.json()
                                    _pairs = _dex.get("pairs", [])
                                    if _pairs: symbol = _pairs[0].get("baseToken", {}).get("symbol", "")
                        except:
                            pass
                    env = os.environ.copy()
                    proc = await asyncio.create_subprocess_exec(
                        'python3', '-u', '/root/deep_research.py', target, symbol or 'UNKNOWN',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env=env
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
                        report = stdout.decode().strip()
                        err = stderr.decode().strip()
                        logger.info(f"Research done, len={len(report)}, err={err[:100] if err else ''}")
                        if report:
                            # Split kalau terlalu panjang (Telegram limit 4096)
                            if len(report) <= 4000:
                                await send(report)
                            else:
                                # Kirim dalam 2 bagian
                                mid = report.rfind("\n\n", 0, 4000)
                                if mid == -1:
                                    mid = 4000
                                await send(report[:mid])
                                await asyncio.sleep(1)
                                await send(report[mid:])
                        else:
                            await send(f"❌ Research kosong. Error: {err[:300]}")
                    except asyncio.TimeoutError:
                        proc.kill()
                        await send("❌ Research timeout (>90 detik), coba lagi.")
                else:
                    await send("⚠️ Butuh mint address bro, bukan symbol. Cari di dexscreener dulu.")
            except asyncio.TimeoutError:
                await send("❌ Research timeout (>30 detik), coba lagi.")
            except Exception as e:
                logger.error(f"deep_research error: {e}", exc_info=True)
                await send(f"❌ Research error: {e}")

    elif intent == "full_analysis":
        target = result.get("target", "").strip().split()[0]
        if not target or len(target) < 30:
            await send("Kasih mint address bro, contoh: 'full 9WpkZ5dr...'")
        else:
            await send(f"🔬📊 Full analysis <b>{target[:20]}...</b>\nResearch + Chart — tunggu ~30 detik")
            try:
                import os
                env = os.environ.copy()
                # Auto-fetch symbol
                _symbol = ""
                try:
                    async with aiohttp.ClientSession() as _ss:
                        async with _ss.get(f"https://frontend-api.pump.fun/coins/{target}", timeout=aiohttp.ClientTimeout(total=5)) as _rr:
                            _pd = await _rr.json()
                            _symbol = _pd.get("symbol", "") or ""
                except:
                    pass
                if not _symbol:
                    try:
                        async with aiohttp.ClientSession() as _ss2:
                            async with _ss2.get(f"https://api.dexscreener.com/latest/dex/tokens/{target}", timeout=aiohttp.ClientTimeout(total=5)) as _rr2:
                                _dex = await _rr2.json()
                                _pairs = _dex.get("pairs", [])
                                if _pairs: _symbol = _pairs[0].get("baseToken", {}).get("symbol", "")
                    except:
                        pass
                # Jalanin research dan chart parallel sebagai 2 subprocess
                proc_r = await asyncio.create_subprocess_exec(
                    'python3', '-u', '/root/deep_research.py', target, _symbol or "UNKNOWN",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
                )
                proc_c = await asyncio.create_subprocess_exec(
                    'python3', '-u', '/root/chart_analyzer.py', target, _symbol or "UNKNOWN",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
                )
                (r_out, _), (c_out, _) = await asyncio.wait_for(
                    asyncio.gather(proc_r.communicate(), proc_c.communicate()), timeout=90
                )
                research = r_out.decode().strip()
                chart = c_out.decode().strip()
                if research:
                    await send(research)
                    await asyncio.sleep(1)
                if chart:
                    await send(chart)
            except asyncio.TimeoutError:
                await send("❌ Full analysis timeout.")
            except Exception as e:
                await send(f"❌ Error: {e}")

    elif intent == "chart_analysis":
        target = result.get("target", "").strip()
        if not target or len(target) < 30:
            await send("Kasih mint address bro, contoh: 'chart 9WpkZ5dr6RN...'")
        else:
            await send(f"📊 Lagi analisa chart <b>{target[:20]}...</b> tunggu ~15 detik")
            try:
                import os
                env = os.environ.copy()
                proc = await asyncio.create_subprocess_exec(
                    'python3', '-u', '/root/chart_analyzer.py', target,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                report = stdout.decode().strip()
                if report:
                    await send(report)
                else:
                    await send(f"❌ Chart error: {stderr.decode()[:200]}")
            except asyncio.TimeoutError:
                await send("❌ Chart analysis timeout, coba lagi.")
            except Exception as e:
                await send(f"❌ Error: {e}")

    elif intent == "manual_buy":
        mint_target = result.get("target", "").strip()
        if not mint_target or len(mint_target) < 30:
            await send("❌ Kasih mint address yang valid bro.\nContoh: buy 9WpkZ5dr6RNJDxaLD4535ssRg6vNcnhZMj2LzAQa8AmP")
            return

        await send(f"🔍 Lagi analisa dulu sebelum buy...\nResearch + Chart ~30 detik, sabar ya")

        try:
            import os
            env = os.environ.copy()

            # Auto-fetch symbol
            _symbol = ""
            try:
                async with aiohttp.ClientSession() as _ss:
                    async with _ss.get(f"https://frontend-api.pump.fun/coins/{mint_target}",
                                       timeout=aiohttp.ClientTimeout(total=5)) as _rr:
                        if _rr.status == 200:
                            _pd = await _rr.json()
                            _symbol = _pd.get("symbol", "") or ""
            except: pass
            if not _symbol:
                try:
                    async with aiohttp.ClientSession() as _ss2:
                        async with _ss2.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint_target}",
                                            timeout=aiohttp.ClientTimeout(total=5)) as _rr2:
                            _dex = await _rr2.json()
                            _pairs = _dex.get("pairs", [])
                            if _pairs: _symbol = _pairs[0].get("baseToken", {}).get("symbol", "")
                except: pass

            # Research + Chart parallel
            proc_r = await asyncio.create_subprocess_exec(
                'python3', '-u', '/root/deep_research.py', mint_target, _symbol or "UNKNOWN",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            proc_c = await asyncio.create_subprocess_exec(
                'python3', '-u', '/root/chart_analyzer.py', mint_target, _symbol or "UNKNOWN",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            (r_out, _), (c_out, _) = await asyncio.wait_for(
                asyncio.gather(proc_r.communicate(), proc_c.communicate()), timeout=90
            )
            research = r_out.decode().strip()
            chart = c_out.decode().strip()

            if research:
                await send(research)
                await asyncio.sleep(1)
            if chart:
                await send(chart)
                await asyncio.sleep(1)

            # Score
            combined = research + "\n" + chart
            import sys as _sys
            _sys.path.insert(0, '/root')
            from auto_trader import score_signal
            import json as _j
            from pathlib import Path as _Path
            cfg = _j.loads(_Path("/root/.risk_config.json").read_text()) if _Path("/root/.risk_config.json").exists() else {}
            score = score_signal({"text": combined, "type": "manual"}, cfg)
            min_score = cfg.get("min_score", 65)
            trade_amount = cfg.get("trade_amount_sol", 0.02)

            score_emoji = "🟢" if score >= min_score else "🟡" if score >= 50 else "🔴"
            verdict_text = "LAYAK DIBELI" if score >= min_score else "UNDER THRESHOLD — tetap bisa buy manual"

            await send(
                f"{score_emoji} <b>Score: {score:.0f}/100</b> — {verdict_text}\n\n"
                f"💰 Trade size: <b>{trade_amount} SOL</b>\n"
                f"🎯 TP: +{cfg.get('take_profit_pct',45)}% | SL: -{cfg.get('stop_loss_pct',10)}%\n"
                f"⚡ TP/SL otomatis jalan via position monitor\n\n"
                f"Mau buy <b>{_symbol or mint_target[:16]}</b>?\n"
                f"Ketik <b>ya</b> untuk konfirmasi atau <b>batal</b> untuk cancel."
            )

            # Simpan pending
            PENDING_FILE.write_text(_j.dumps({
                "action": "manual_buy",
                "mint": mint_target,
                "symbol": _symbol or "UNKNOWN",
                "score": score,
                "timestamp": datetime.now().isoformat()
            }))

        except asyncio.TimeoutError:
            await send("❌ Analisa timeout. Coba lagi.")
        except Exception as e:
            await send(f"❌ Error: {e}")

    elif intent == "trading_status":
        try:
            import json as _j
            from pathlib import Path
            
            # Daily stats
            stats_file = Path("/root/.daily_stats.json")
            stats = _j.loads(stats_file.read_text()) if stats_file.exists() else {}
            
            # Positions
            pos_file = Path("/root/.openclaw_positions.json")
            positions = _j.loads(pos_file.read_text()) if pos_file.exists() else {}
            open_pos = {k:v for k,v in positions.items() if v.get("status") == "open"}
            closed_pos = {k:v for k,v in positions.items() if v.get("status") == "closed"}
            
            # Config
            cfg_file = Path("/root/.risk_config.json")
            config = _j.loads(cfg_file.read_text()) if cfg_file.exists() else {}
            
            # Balance
            import sys
            sys.path.insert(0, '/root')
            from pump_executor import get_sol_balance
            bal = await get_sol_balance()
            
            # PnL hari ini
            invested = stats.get("total_invested_sol", 0)
            returned = stats.get("total_returned_sol", 0)
            pnl_sol = returned - invested
            pnl_pct = (pnl_sol / invested * 100) if invested > 0 else 0
            pnl_emoji = "📈" if pnl_sol >= 0 else "📉"
            
            # Win/loss dari closed positions
            wins = sum(1 for p in closed_pos.values() if p.get("pnl_pct", 0) > 0)
            losses = sum(1 for p in closed_pos.values() if p.get("pnl_pct", 0) <= 0)
            win_rate = (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
            
            # Status trading
            paused = config.get("trading_paused", False)
            status_emoji = "⏸️" if paused else "▶️"
            status_text = "PAUSED" if paused else "RUNNING"
            
            # Top wallet reputations
            rep_text = ""
            try:
                from wallet_reputation import get_top_wallets
                top_wallets = get_top_wallets(3)
                if top_wallets:
                    rep_text = "\n\n🏆 <b>Top Wallets:</b>\n"
                    for w in top_wallets:
                        rep_text += f"• {w['wallet']}: {w['win_rate']}% WR ({w['trades']} trades)\n"
            except:
                pass
            
            msg = (
                f"{status_emoji} <b>Trading Status: {status_text}</b>\n\n"
                f"\U0001f4b0 Balance: <b>{bal:.4f} SOL</b>\n\n"
                f"\U0001f4ca <b>Hari ini:</b>\n"
                f"\u2022 Trades: {stats.get('trades', 0)}\n"
                f"\u2022 Invested: {invested:.4f} SOL\n"
                f"{pnl_emoji} PnL: {pnl_sol:+.4f} SOL ({pnl_pct:+.1f}%)\n\n"
                f"\U0001f4c2 <b>Posisi:</b>\n"
                f"\u2022 Open: {len(open_pos)}\n"
                f"\u2022 Closed: {len(closed_pos)}\n"
                f"\u2022 Win rate: {win_rate:.0f}% ({wins}W/{losses}L)\n\n"
                f"\u2699\ufe0f <b>Config:</b>\n"
                f"\u2022 Per trade: {config.get('trade_amount_sol', 0.02)} SOL\n"
                f"\u2022 TP: +{config.get('take_profit_pct', 30)}% | SL: -{config.get('stop_loss_pct', 15)}%\n"
                f"\u2022 Min score: {config.get('min_score', 65)}/100"
                + rep_text
            )
            await send(msg)
        except Exception as e:
            await send(f"❌ Error: {e}")

    elif intent == "check_balance":
        try:
            import aiohttp as ah
            helius_key = os.getenv("HELIUS_API_KEY", "")
            # Get wallet pubkey
            import subprocess
            result = subprocess.run(['python3', '-c', 
                'import sys; sys.path.insert(0, "/root"); from wallet_manager import get_public_key; print(get_public_key())'],
                capture_output=True, text=True)
            pub_key = result.stdout.strip()
            
            rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
            async with aiohttp.ClientSession() as s:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub_key]}
                async with s.post(rpc_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as r:
                    data = await r.json()
                    lamports = data.get("result", {}).get("value", 0)
                    sol = lamports / 1_000_000_000
            
            # Get SOL price
            async with aiohttp.ClientSession() as s:
                async with s.get("https://api.dexscreener.com/latest/dex/search?q=SOL+USDC",
                                  timeout=aiohttp.ClientTimeout(total=8)) as r:
                    dex = await r.json()
                    sol_price = 0
                    for p in dex.get("pairs", []):
                        if p.get("baseToken", {}).get("symbol") == "SOL":
                            sol_price = float(p.get("priceUsd", 0))
                            break
            
            await send(f"💰 <b>Balance:</b> {sol:.4f} SOL (${sol * sol_price:.2f})")
        except Exception as e:
            await send(f"❌ Ga bisa cek saldo: {e}")

    else:
        if reply:
            await send(reply)


async def main():
    logger.info("🤖 AI Bot started, polling...")
    await send("🤖 AI Assistant online! Tanya apa aja.")
    offset = 0
    while True:
        updates = await get_updates(offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg = upd.get("message", {})
            # Hanya proses pesan dari CHAT_ID lu
            if msg.get("chat", {}).get("id") != CHAT_ID:
                continue
            text = msg.get("text", "")
            if text:
                logger.info(f"Received: {text}")
                asyncio.create_task(handle_message(text))
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
