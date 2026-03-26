"""
tg_commander.py - TG Bot Commander
Commands:
/status - liat semua open positions + PnL realtime
/pnl - summary profit/loss hari ini
/buy <mint> <symbol> - manual buy
/sell <mint> - manual sell 100%
/pause - pause trading
/resume - resume trading
/config - liat config sekarang
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5664251521")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"

_last_update_id = 0

async def send_msg(text: str, parse_mode: str = "HTML"):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{API}/sendMessage", json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        })

async def get_updates():
    global _last_update_id
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{API}/getUpdates", params={
                "offset": _last_update_id + 1,
                "timeout": 10,
                "limit": 10
            }, timeout=aiohttp.ClientTimeout(total=15)) as r:
                data = await r.json()
                return data.get("result", [])
    except:
        return []

async def get_sol_price() -> float:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                d = await r.json()
                return float(d.get("pair", {}).get("priceUsd", 87) or 87)
    except:
        return 87.0

async def get_token_price(mint: str) -> float:
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
    # Fallback pump.fun
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://frontend-api.pump.fun/coins/{mint}",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status == 200:
                    d = await r.json()
                    virt_sol = d.get("virtual_sol_reserves", 0) / 1e9
                    virt_tokens = d.get("virtual_token_reserves", 0) / 1e6
                    if virt_sol > 0 and virt_tokens > 0:
                        sol_price = await get_sol_price()
                        return (virt_sol / virt_tokens) * sol_price
    except:
        pass
    return 0.0

async def cmd_status():
    pos_file = Path("/root/.openclaw_positions.json")
    cfg_file = Path("/root/.risk_config.json")
    if not pos_file.exists():
        await send_msg("❌ Tidak ada posisi")
        return

    positions = json.loads(pos_file.read_text())
    open_pos = {k: v for k, v in positions.items() if v.get("status") == "open"}
    config = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    sol_price = await get_sol_price()

    if not open_pos:
        await send_msg("📭 <b>Tidak ada open positions</b>\n\nBot aktif, nunggu signal...")
        return

    lines = [f"📊 <b>OPEN POSITIONS ({len(open_pos)}/{config.get('max_open_positions', 3)})</b>\n"]
    total_invested_sol = 0
    total_current_sol = 0

    for mint, pos in open_pos.items():
        symbol = pos.get("token_symbol", "?")
        buy_price = pos.get("buy_price_usd", 0)
        amount_token = pos.get("amount_token", 0)
        amount_sol = pos.get("amount_invested_sol", 0.02)
        wallet_src = pos.get("wallet_source", "?") or "?"
        buy_time = pos.get("buy_time", "")
        peak_price = pos.get("peak_price_usd", buy_price)

        # Age
        age_str = "?"
        if buy_time:
            age_min = (datetime.now() - datetime.fromisoformat(buy_time)).total_seconds() / 60
            age_str = f"{age_min:.0f}m" if age_min < 60 else f"{age_min/60:.1f}h"

        current_price = await get_token_price(mint)

        if current_price and buy_price:
            pnl_pct = (current_price - buy_price) / buy_price * 100
            pnl_sol = amount_sol * (pnl_pct / 100)
            pnl_usd = pnl_sol * sol_price
            current_sol = amount_sol + pnl_sol
            peak_pnl = (peak_price - buy_price) / buy_price * 100 if buy_price else 0
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            pnl_str = f"{pnl_pct:+.1f}% ({pnl_usd:+.3f}$ / {pnl_sol:+.4f} SOL)"
        else:
            pnl_pct = 0
            pnl_sol = 0
            pnl_usd = 0
            current_sol = amount_sol
            peak_pnl = 0
            emoji = "⚪"
            pnl_str = "fetching..."

        total_invested_sol += amount_sol
        total_current_sol += current_sol

        lines.append(
            f"{emoji} <b>{symbol}</b> | {age_str} | from {wallet_src}\n"
            f"   💰 PnL: {pnl_str}\n"
            f"   📈 Peak: {peak_pnl:+.1f}% | Buy: ${buy_price:.8f}\n"
            f"   📋 <code>{mint[:20]}...</code>\n"
        )

    # Summary
    total_pnl_sol = total_current_sol - total_invested_sol
    total_pnl_usd = total_pnl_sol * sol_price
    total_pnl_pct = (total_pnl_sol / total_invested_sol * 100) if total_invested_sol > 0 else 0
    summary_emoji = "🟢" if total_pnl_sol > 0 else "🔴"

    lines.append(
        f"━━━━━━━━━━━━━━━\n"
        f"{summary_emoji} <b>Total PnL: {total_pnl_pct:+.1f}%</b>\n"
        f"   💵 {total_pnl_usd:+.3f} USD\n"
        f"   ◎ {total_pnl_sol:+.4f} SOL\n"
        f"   Invested: {total_invested_sol:.3f} SOL (${total_invested_sol*sol_price:.2f})"
    )

    await send_msg("\n".join(lines))

async def cmd_pnl():
    pos_file = Path("/root/.openclaw_positions.json")
    stats_file = Path("/root/.daily_stats.json")
    sol_price = await get_sol_price()

    if not pos_file.exists():
        await send_msg("❌ Tidak ada data")
        return

    positions = json.loads(pos_file.read_text())
    today = datetime.now().strftime("%Y-%m-%d")

    # Ambil semua trade hari ini
    today_trades = []
    for mint, pos in positions.items():
        buy_time = pos.get("buy_time", "")
        if buy_time and buy_time.startswith(today):
            today_trades.append(pos)

    if not today_trades:
        await send_msg("📭 Belum ada trade hari ini")
        return

    total_invested = sum(p.get("amount_invested_sol", 0.02) for p in today_trades)
    wins, losses, timeouts, open_count = 0, 0, 0, 0
    total_pnl_sol = 0

    for p in today_trades:
        status = p.get("status", "")
        pnl_pct = p.get("pnl_pct", 0) or 0
        invested = p.get("amount_invested_sol", 0.02)
        pnl_sol = invested * (pnl_pct / 100)
        reason = p.get("close_reason", "")

        if status == "open":
            open_count += 1
        elif pnl_pct > 0:
            wins += 1
            total_pnl_sol += pnl_sol
        elif "TIMEOUT" in reason.upper():
            timeouts += 1
            total_pnl_sol += pnl_sol
        else:
            losses += 1
            total_pnl_sol += pnl_sol

    total_pnl_usd = total_pnl_sol * sol_price
    total_pnl_pct = (total_pnl_sol / total_invested * 100) if total_invested > 0 else 0
    closed = len(today_trades) - open_count
    wr = (wins / closed * 100) if closed > 0 else 0
    summary_emoji = "🟢" if total_pnl_sol > 0 else "🔴"

    msg = (
        f"📈 <b>PnL HARI INI — {today}</b>\n\n"
        f"📊 Total Trade: {len(today_trades)} ({open_count} open)\n"
        f"✅ Win: {wins} | ❌ Loss: {losses} | ⏰ Timeout: {timeouts}\n"
        f"🎯 Win Rate: {wr:.0f}%\n\n"
        f"💰 Invested: {total_invested:.3f} SOL (${total_invested*sol_price:.2f})\n"
        f"{summary_emoji} <b>PnL: {total_pnl_pct:+.1f}%</b>\n"
        f"   💵 {total_pnl_usd:+.3f} USD\n"
        f"   ◎ {total_pnl_sol:+.4f} SOL\n\n"
        f"<i>*Open positions belum dihitung</i>"
    )
    await send_msg(msg)

async def cmd_buy(mint: str, symbol: str):
    import sys
    sys.path.insert(0, '/root')
    from pump_executor import buy, get_sol_balance
    from auto_trader import load_config, load_positions, load_daily_stats, should_trade

    config = load_config()
    bal = await get_sol_balance()
    can_trade, reason = should_trade(config, load_positions(), load_daily_stats(), bal)
    if not can_trade:
        await send_msg(f"❌ Cannot trade: {reason}")
        return

    await send_msg(f"⏳ Manual buy {symbol} — {config.get('trade_amount_sol', 0.02)} SOL...")
    result = await buy(mint, config.get("trade_amount_sol", 0.02), symbol, wallet_source="manual_tg")
    if result.get("success"):
        await send_msg(f"✅ <b>Manual buy berhasil!</b>\n🪙 {symbol}\n🔗 TX: https://solscan.io/tx/{result['tx']}")
    else:
        await send_msg(f"❌ Manual buy gagal: {result.get('error')}")

async def cmd_sell(mint: str):
    import sys
    sys.path.insert(0, '/root')
    from pump_executor import sell
    from pathlib import Path
    import json

    pos_file = Path("/root/.openclaw_positions.json")
    positions = json.loads(pos_file.read_text()) if pos_file.exists() else {}
    symbol = positions.get(mint, {}).get("token_symbol", mint[:8])

    await send_msg(f"⏳ Manual sell {symbol}...")
    result = await sell(mint, 100, symbol)
    if result.get("success"):
        positions[mint]["status"] = "closed"
        positions[mint]["close_reason"] = "manual sell via TG command"
        positions[mint]["close_time"] = datetime.now().isoformat()
        pos_file.write_text(json.dumps(positions, indent=2))
        await send_msg(f"✅ <b>Sold {symbol}</b>\n🔗 TX: https://solscan.io/tx/{result['tx']}")
    else:
        await send_msg(f"❌ Sell gagal: {result.get('error')}")

async def cmd_pause():
    cfg_file = Path("/root/.risk_config.json")
    config = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    config["trading_paused"] = True
    config["pause_reason"] = "manual pause via TG"
    cfg_file.write_text(json.dumps(config, indent=2))
    await send_msg("⏸ <b>Trading PAUSED</b>")

async def cmd_resume():
    cfg_file = Path("/root/.risk_config.json")
    config = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    config["trading_paused"] = False
    config["pause_reason"] = ""
    cfg_file.write_text(json.dumps(config, indent=2))
    await send_msg("▶️ <b>Trading RESUMED</b>")

async def cmd_config():
    cfg_file = Path("/root/.risk_config.json")
    config = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
    sol_price = await get_sol_price()
    trade_sol = config.get('trade_amount_sol', 0.02)
    msg = (
        f"⚙️ <b>CONFIG SEKARANG</b>\n\n"
        f"💰 Trade amount: {trade_sol} SOL (${trade_sol*sol_price:.2f})\n"
        f"🎯 Take Profit: +{config.get('take_profit_pct', 45)}%\n"
        f"🛑 Stop Loss: -{config.get('stop_loss_pct', 10)}%\n"
        f"📊 Min Score: {config.get('min_score', 65)}\n"
        f"📈 Max Positions: {config.get('max_open_positions', 3)}\n"
        f"⏸ Paused: {config.get('trading_paused', False)}\n"
        f"💧 Min Liquidity: ${config.get('min_liquidity_usd', 3000):,}\n"
        f"📉 Min Volume: ${config.get('min_volume_24h', 1000):,}"
    )
    await send_msg(msg)

async def cmd_help():
    msg = (
        "🤖 <b>OPENCLAW COMMANDER</b>\n\n"
        "/status — open positions + PnL realtime\n"
        "/pnl — summary profit/loss hari ini\n"
        "/buy &lt;mint&gt; &lt;symbol&gt; — manual buy\n"
        "/sell &lt;mint&gt; — manual sell\n"
        "/pause — pause auto trading\n"
        "/resume — resume auto trading\n"
        "/config — liat config sekarang\n"
        "/help — bantuan ini"
    )
    await send_msg(msg)

async def handle_command(text: str):
    text = text.strip()
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]

    if cmd == "/status":
        await cmd_status()
    elif cmd == "/pnl":
        await cmd_pnl()
    elif cmd == "/buy":
        if len(parts) < 3:
            await send_msg("Usage: /buy &lt;mint&gt; &lt;symbol&gt;\nContoh: /buy ABC123... MYTOKEN")
        else:
            await cmd_buy(parts[1], parts[2])
    elif cmd == "/sell":
        if len(parts) < 2:
            await send_msg("Usage: /sell &lt;mint&gt;")
        else:
            await cmd_sell(parts[1])
    elif cmd == "/pause":
        await cmd_pause()
    elif cmd == "/resume":
        await cmd_resume()
    elif cmd == "/config":
        await cmd_config()
    elif cmd == "/help":
        await cmd_help()

async def commander_loop():
    global _last_update_id
    logger.info("🤖 TG Commander started!")
    await send_msg("🤖 <b>OpenClaw Commander online!</b>\n\nKetik /help untuk list commands.")

    while True:
        try:
            updates = await get_updates()
            for update in updates:
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")

                # Security: hanya proses dari CHAT_ID lo sendiri
                if chat_id != CHAT_ID:
                    continue

                if text.startswith("/"):
                    logger.info(f"Command: {text}")
                    await handle_command(text)

        except Exception as e:
            logger.error(f"Commander error: {e}")

        await asyncio.sleep(2)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    asyncio.run(commander_loop())
