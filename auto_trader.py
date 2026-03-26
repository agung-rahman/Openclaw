"""
auto_trader.py - Auto trading berdasarkan signal queue
"""
import asyncio
import json
import logging
import re
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

def load_config() -> dict:
    cfg_file = Path("/root/.risk_config.json")
    default = {
        "trade_amount_sol": 0.02,
        "stop_loss_pct": 15,
        "take_profit_pct": 30,
        "daily_loss_limit_pct": 50,
        "trading_paused": False,
        "max_open_positions": 5,
        "min_score": 65,
        "min_liquidity_usd": 3000,
        "max_holder_top1_pct": 20,
        "require_verdict_not_skip": True,
    }
    if cfg_file.exists():
        saved = json.loads(cfg_file.read_text())
        default.update(saved)
    return default

def load_positions() -> dict:
    pos_file = Path("/root/.openclaw_positions.json")
    return json.loads(pos_file.read_text()) if pos_file.exists() else {}

def load_daily_stats() -> dict:
    stats_file = Path("/root/.daily_stats.json")
    today = datetime.now().strftime("%Y-%m-%d")
    if stats_file.exists():
        stats = json.loads(stats_file.read_text())
        if stats.get("date") == today:
            if stats.get("total_invested_sol", 0) == 0:
                stats["total_returned_sol"] = 0
            return stats
    new_stats = {"date": today, "total_invested_sol": 0, "total_returned_sol": 0, "trades": 0, "losses": 0}
    stats_file.write_text(json.dumps(new_stats, indent=2))
    return new_stats

def save_daily_stats(stats: dict):
    Path("/root/.daily_stats.json").write_text(json.dumps(stats, indent=2))

def should_trade(config: dict, positions: dict, daily_stats: dict, sol_balance: float) -> tuple:
    if config.get("trading_paused"):
        return False, f"Trading paused: {config.get('pause_reason', 'manual')}"
    open_positions = {k:v for k,v in positions.items() if v.get("status") == "open"}
    if len(open_positions) >= config.get("max_open_positions", 3):
        return False, f"Max positions reached ({len(open_positions)})"
    trade_amount = config.get("trade_amount_sol", 0.02)
    if sol_balance < trade_amount + 0.005:
        return False, f"Insufficient balance: {sol_balance:.4f} SOL"
    invested = daily_stats.get("total_invested_sol", 0)
    returned = daily_stats.get("total_returned_sol", 0)
    # Daily loss limit disabled — pantau manual via TG
    return True, "OK"

def score_signal(signal: dict, config: dict) -> float:
    text = signal.get("text", "")
    score = 50.0

    # Holder distribution
    top1_match = re.search(r'Top 1: ([\d.]+)%', text)
    if top1_match:
        top1 = float(top1_match.group(1))
        if top1 > 50: score -= 30
        elif top1 > 20: score -= 15
        elif top1 < 10: score += 15

    # AI Verdict
    # APE IN verdict — tapi kurangi bonus kalau price lagi turun
    price_1h_for_verdict = 0
    _pm = re.search(r'Price 1h: ([+-]?[\d.]+)%', text)
    if _pm:
        price_1h_for_verdict = float(_pm.group(1))
    if "VERDICT: APE IN" in text or "APE IN" in text.upper():
        if price_1h_for_verdict < -10:
            score += 10  # Masih kasih bonus tapi kecil
        else:
            score += 25
    elif "VERDICT: WAIT" in text or "**: WAIT" in text:
        score += 5
    elif "VERDICT: SKIP" in text or "**: SKIP" in text:
        score -= 30

    # Liquidity
    liq_match = re.search(r'Liquidity: \$([\d,]+)', text)
    if liq_match:
        liq = float(liq_match.group(1).replace(',', ''))
        if liq == 0: score -= 40
        elif liq < 3000: score -= 20
        elif liq > 20000: score += 10

    # Volume
    vol_match = re.search(r'Vol 24h: \$([\d,]+)', text)
    if vol_match:
        vol = float(vol_match.group(1).replace(',', ''))
        if vol < 1000: score -= 20
        elif vol > 50000: score += 10

    # Rugcheck
    rug_match = re.search(r'Rugcheck: ([\d,]+)/1000', text)
    if rug_match:
        rug = int(rug_match.group(1).replace(',', ''))
        # Rugcheck: score TINGGI = AMAN, score RENDAH = BANYAK ISSUE
        if rug >= 700: score += 10
        elif rug >= 400: score += 5
        elif rug < 200: score -= 20
        elif rug < 400: score -= 10

    # Red flags
    if "creator history of rugged" in text.lower(): score -= 30
    if "Whale Risk: LOW" in text: score += 10
    if "Whale Risk: HIGH" in text: score -= 10

    # Wallet reputation scoring disabled — semua wallet dianalisa equal

    # Price momentum
    price_1h_match = re.search(r'Price 1h: ([+-]?[\d.]+)%', text)
    if price_1h_match:
        price_1h = float(price_1h_match.group(1))
        if price_1h < -20: score -= 30
        elif price_1h < -10: score -= 15
        elif price_1h < -5: score -= 5
        elif price_1h > 10: score += 10
        elif price_1h > 20: score += 15

    # Token age
    age_match = re.search(r'Age: ([\d.]+)([hd])', text)
    if age_match:
        age_val = float(age_match.group(1))
        age_unit = age_match.group(2)
        age_hours = age_val * 24 if age_unit == 'd' else age_val
        if age_hours > 48: score -= 20
        elif age_hours > 24: score -= 10
        elif age_hours < 2: score += 10
    # Bundle check — bagus di bawah 25%
    bundle_match = re.search(r'Bundle[s]?[:\s]+(\d+\.?\d*)%', text, re.IGNORECASE)
    if bundle_match:
        bundle_pct = float(bundle_match.group(1))
        if bundle_pct > 50: score -= 40
        elif bundle_pct > 25: score -= 25
        elif bundle_pct > 15: score -= 10
        else: score += 5
    # Sniper check
    sniper_match = re.search(r'Sniper[s]?[:\s]+(\d+\.?\d*)%', text, re.IGNORECASE)
    if sniper_match:
        sniper_pct = float(sniper_match.group(1))
        if sniper_pct > 20: score -= 20
        elif sniper_pct > 10: score -= 10

    # Wallet signal lebih trusted
    if signal.get("type") == "wallet":
        score += 10
    _w = signal.get("wallet","").lower()
    if any(tw in _w for tw in {"jason", "sniper fish", "sniper fish 2", "sniper fish 3", "brox", "gake"}):
        score += 15
    elif any(tw in _w for tw in {"solanadegen", "bandit gblk"}):
        score += 8

    return max(0, min(100, score))

async def process_signal(signal: dict) -> bool:
    import sys
    sys.path.insert(0, '/root')
    from pump_executor import buy, get_sol_balance

    config = load_config()
    mint = signal.get("mint", "")
    symbol = signal.get("token", "UNKNOWN")
    text = signal.get("text", "")

    # Parse mint dari DexScreener URL kalau field mint kosong
    if not mint or len(mint) < 30:
        _url = re.search(r'dexscreener\.com/solana/([A-Za-z0-9]{30,})', text)
        if _url:
            mint = _url.group(1)
        else:
            return False

    # Parse symbol dari text kalau UNKNOWN
    if symbol == "UNKNOWN":
        _sym = re.search(r'Token: .+\(\$([^\)]+)\)', text)
        if _sym:
            symbol = _sym.group(1).strip()

    # Skip kalau token masih open/di-hold ATAU baru kena SL dalam 1 jam
    try:
        import json as _j
        from datetime import datetime as _dt, timedelta as _td
        _pos = _j.loads(Path("/root/.openclaw_positions.json").read_text())
        if mint in _pos and _pos[mint].get("status") == "open":
            logger.info(f"Skip {symbol} — token masih di-hold (mint match)")
            return False
        for _p in _pos.values():
            _sym_match = _p.get("token_symbol","").upper() == symbol.upper()
            if _sym_match:
                if _p.get("status") == "open":
                    logger.info(f"Skip {symbol} — token masih di-hold (name match)")
                    return False
                # Cooldown 1 jam setelah SL/closed
                _close_time = _p.get("close_time","")
                _close_reason = _p.get("close_reason","")
                # Skip cooldown kalau close karena failed buy (amount_token == 1.0 dummy atau no balance langsung)
                _is_failed_buy = (
                    _p.get("amount_token", 99) <= 1.0 and
                    "no balance" in _close_reason.lower()
                )
                if _close_time and not _is_failed_buy:
                    _age = (_dt.now() - _dt.fromisoformat(_close_time)).total_seconds() / 3600
                    if _age < 1:
                        logger.info(f"Skip {symbol} — cooldown 1 jam setelah close ({_age:.1f}h ago)")
                        return False
    except:
        pass

    # Filter: verdict tidak boleh SKIP
    TRUSTED_WALLETS = {"jason", "sniper fish", "sniper fish 2", "sniper fish 3", "brox", "gake"}
    SEMI_TRUSTED = {"solanadegen", "bandit gblk"}
    wallet_source = signal.get("wallet", "").lower()
    is_trusted = any(tw in wallet_source for tw in TRUSTED_WALLETS)
    is_semi = any(tw in wallet_source for tw in SEMI_TRUSTED)

    if config.get("require_verdict_not_skip", True) and not is_trusted and not is_semi:
        if "SKIP" in text.upper() and "VERDICT" in text.upper():
            if not ("APE IN" in text.upper() or "WAIT" in text.upper()):
                logger.info(f"Skip {symbol} — verdict SKIP")
                return False
    elif (is_trusted or is_semi) and "SKIP" in text.upper() and "VERDICT" in text.upper():
        logger.info(f"Allow {symbol} — {'trusted' if is_trusted else 'semi'} wallet ({wallet_source}) bypass verdict SKIP")

    # Filter: token age max 14 hari
    age_match = re.search(r'Age: ([\d.]+)([hd])', text)
    if age_match:
        age_val = float(age_match.group(1))
        age_unit = age_match.group(2)
        age_days = age_val if age_unit == 'd' else age_val / 24
        if age_days > 14:
            logger.info(f"Skip {symbol} — token age {age_days:.1f} hari > 14 hari")
            return False

    # Filter: max MCap 200K
    mcap_match = re.search(r'MCap: \$([\d,]+)', text)
    if mcap_match:
        mcap = float(mcap_match.group(1).replace(',', ''))
        if mcap > 200000:
            logger.info(f"Skip {symbol} — MCap ${mcap:,.0f} > $200K")
            return False

    # Filter: liquidity check — support bonding curve (liq $0 tapi vol ada = aktif)
    liq_match = re.search(r'Liquidity: \$([\d,]+)', text)
    vol_for_liq = 0
    vol_for_liq_match = re.search(r'Vol 24h: \$([\d,]+)', text)
    if vol_for_liq_match:
        vol_for_liq = float(vol_for_liq_match.group(1).replace(',', ''))
    if liq_match:
        liq = float(liq_match.group(1).replace(',', ''))
        if liq == 0:
            if vol_for_liq >= 5000:
                logger.info(f"Allow {symbol} — Liq $0 tapi Vol ${vol_for_liq:,.0f} (bonding curve aktif)")
            elif is_trusted and vol_for_liq >= 1000:
                logger.info(f"Allow {symbol} — trusted wallet, Liq $0 tapi Vol ${vol_for_liq:,.0f}")
            else:
                logger.info(f"Skip {symbol} — Liq $0 + Vol ${vol_for_liq:,.0f} rendah (dead token)")
                return False
        elif liq < 1000:
            logger.info(f"Skip {symbol} — Liquidity ${liq:,.0f} terlalu rendah")
            return False

    # Filter: HARD — volume $0 = dead token, skip langsung
    vol_match = re.search(r'Vol 24h: \$([\d,]+)', text)
    if vol_match:
        vol = float(vol_match.group(1).replace(',', ''))
        min_vol = config.get("min_volume_24h", 500)
        if vol < min_vol:
            logger.info(f"Skip {symbol} — Vol 24h ${vol:,.0f} < ${min_vol:,.0f}")
            return False

    # Filter: price 1h = 0.0% DAN volume rendah = dead token
    price_match = re.search(r'Price 1h: \+?0\.0%', text)
    if price_match:
        vol_check = re.search(r'Vol 24h: \$([\d,]+)', text)
        vol_val = float(vol_check.group(1).replace(',','')) if vol_check else 0
        if is_trusted:
            logger.info(f"Allow {symbol} — trusted wallet ({wallet_source}), bypass flat price filter")
        elif vol_val < 1000:
            logger.info(f"Skip {symbol} — Price 1h flat 0.0% + volume rendah ${vol_val:.0f}")
            return False
        else:
            logger.info(f"Allow {symbol} — Price 1h flat tapi volume ada ${vol_val:.0f}")

    # Filter: holder top 1
    top1_match = re.search(r'Top 1: ([\d.]+)%', text)
    if top1_match:
        top1 = float(top1_match.group(1))
        if top1 > config.get("max_holder_top1_pct", 20):
            logger.info(f"Skip {symbol} — top1 {top1}% terlalu tinggi")
            return False

    # Filter: rugcheck score terlalu tinggi = banyak issues
    rug_match = re.search(r'Rugcheck: ([\d,]+)/1000', text)
    if rug_match:
        rug = int(rug_match.group(1).replace(',', ''))
        if rug > 10000:
            logger.info(f"Skip {symbol} — Rugcheck {rug}/1000 terlalu tinggi")
            return False

    # Filter: creator history of rugged = hard skip
    if "creator history of rugged" in text.lower():
        logger.info(f"Skip {symbol} — creator history of rugged")
        return False

    # Score
    score = score_signal(signal, config)
    min_score = config.get("min_score", 65)
    if is_trusted:
        min_score = max(55, min_score - 10)
    elif is_semi:
        min_score = max(60, min_score - 5)
    if score < min_score:
        logger.info(f"Skip {symbol} — score {score:.1f} < {min_score}")
        return False
    
    # Alert kalau score tinggi banget — kirim notif ke TG biar bisa monitor manual
    if score >= 85:
        try:
            BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
            import aiohttp as _aio
            alert_msg = f"🔥 HIGH SCORE ALERT!\n\n🪙 {symbol}\n📊 Score: {score:.0f}/100\n🔗 https://dexscreener.com/solana/{mint}\nAxiom: https://axiom.trade/meme/{mint}\n\n⚡ Bot akan auto-buy sekarang..."
            async with _aio.ClientSession() as _s:
                await _s.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": CHAT_ID, "text": alert_msg, "parse_mode": "HTML",
                          "disable_web_page_preview": True}
                )
        except:
            pass

    # Cek balance & kondisi trading
    bal = await get_sol_balance()
    can_trade, reason = should_trade(config, load_positions(), load_daily_stats(), bal)
    if not can_trade:
        logger.warning(f"Cannot trade: {reason}")
        return False

    # Chart analysis sebelum entry
    try:
        import subprocess, os
        proc = subprocess.run(
            ['python3', '-u', '/root/chart_analyzer.py', mint, symbol],
            capture_output=True, text=True, timeout=35,
            env={**os.environ}
        )
        chart_output = proc.stdout.strip()
        if not chart_output:
            logger.info(f"Skip {symbol} — chart output kosong (no data)")
            return False
        if "Tidak ada data chart" in chart_output or "terlalu baru" in chart_output:
            logger.info(f"Skip {symbol} — no chart data (token terlalu baru/dead)")
            return False
        # Cek RSI — kalau ga ada RSI data, izinkan kalau score tinggi
        rsi_match = re.search(r'RSI: ([\d.]+)', chart_output)
        if not rsi_match:
            rsi_threshold = 65 if is_trusted else 75
            if score >= rsi_threshold:
                logger.info(f"Allow {symbol} — no RSI tapi score tinggi ({score:.0f})")
            else:
                logger.info(f"Skip {symbol} — no RSI data, score {score:.0f} < {rsi_threshold}")
                return False
        rsi = float(rsi_match.group(1))
        # Cek trend
        trend_down = "DOWNTREND" in chart_output
        # Cek chart verdict
        chart_skip = "CHART VERDICT: SELL" in chart_output or "CHART VERDICT: **SELL**" in chart_output
        logger.info(f"Chart check {symbol}: RSI={rsi} | downtrend={trend_down} | skip={chart_skip}")
        # Skip kalau RSI overbought atau downtrend kuat
        if rsi > 75:
            logger.info(f"Skip {symbol} — RSI overbought ({rsi})")
            return False
        if trend_down and rsi > 55:
            logger.info(f"Skip {symbol} — downtrend + RSI {rsi}")
            return False
        if chart_skip:
            logger.info(f"Skip {symbol} — chart verdict SELL")
            return False
    except Exception as e:
        logger.warning(f"Chart check failed for {symbol}: {e}")
        # Kalau chart timeout tapi score tinggi, tetap lanjut
        if score >= 75:
            logger.info(f"Allow {symbol} — chart timeout tapi score tinggi ({score:.0f}), lanjut buy")
        else:
            logger.info(f"Skip {symbol} — chart timeout + score {score:.0f} < 75")
            return False

    # Execute BUY
    trade_amount = config.get("trade_amount_sol", 0.02)
    logger.info(f"🚀 BUY {symbol} — {trade_amount} SOL (score: {score:.1f})")

    result = await buy(mint, trade_amount, symbol, wallet_source=signal.get("wallet", ""))

    if result.get("success"):
        pass  # wallet_source sudah di-save langsung di buy() -> _save_position()

        # Update daily stats
        stats = load_daily_stats()
        stats["total_invested_sol"] += trade_amount
        stats["trades"] += 1
        save_daily_stats(stats)

        # Notify
        await _notify_trade(symbol, mint, trade_amount, result["tx"], score, config, text)
        return True
    else:
        logger.error(f"Trade failed: {result.get('error')}")
        return False

async def _notify_trade(symbol, mint, amount_sol, tx, score, config, signal_text=""):
    import aiohttp
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    tp = config.get("take_profit_pct", 30)
    sl = config.get("stop_loss_pct", 15)
    # Buat alasan buy dari signal text yang sebenarnya
    reasons = []
    if score >= 85: reasons.append("🔥 Score tinggi")
    if "VERDICT: APE IN" in signal_text.upper(): reasons.append("✅ AI verdict APE IN")
    elif "VERDICT: WAIT" in signal_text.upper(): reasons.append("⏳ AI verdict WAIT")
    if "Whale Risk: LOW" in signal_text: reasons.append("🐋 Whale risk rendah")
    import re as _re
    _b = _re.search(r'Bundle[s]?[:\s]+([\d.]+)%', signal_text, _re.IGNORECASE)
    if _b and float(_b.group(1)) <= 15: reasons.append(f"✅ Bundle clean ({_b.group(1)}%)")
    _w = _re.search(r'from (\w+)', signal_text)
    if _w: reasons.append(f"👛 Wallet: {_w.group(1)}")
    reason_text = " | ".join(reasons) if reasons else "📈 Filter lolos semua"

    msg = (
        f"🚀 <b>AUTO BUY!</b>\n\n"
        f"🪙 <b>{symbol}</b>\n"
        f"💰 {amount_sol} SOL\n"
        f"📊 Score: {score:.0f}/100\n"
        f"💡 {reason_text}\n"
        f"📋 CA: <code>{mint}</code>\n"
        f"🎯 TP: +{tp}% | SL: -{sl}%\n"
        f"🔗 <a href='https://solscan.io/tx/{tx}'>TX</a> | "
        f"<a href='https://dexscreener.com/solana/{mint}'>Chart</a>"
    )
    async with aiohttp.ClientSession() as s:
        await s.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML",
                  "disable_web_page_preview": True}
        )

async def auto_trader_loop():
    logger.info("🤖 Auto trader started!")
    # Load processed mints dari file biar ga reprocess setelah restart
    _proc_file = Path("/root/.processed_signals.json")
    try:
        processed = set(json.loads(_proc_file.read_text())) if _proc_file.exists() else set()
    except:
        processed = set()

    while True:
        try:
            config = load_config()
            if config.get("trading_paused"):
                await asyncio.sleep(30)
                continue

            queue_file = Path("/root/.signal_queue.json")
            if not queue_file.exists():
                await asyncio.sleep(30)
                continue

            queue = json.loads(queue_file.read_text())

            for signal in queue:
                mint = signal.get("mint", "")
                if not mint or mint in processed:
                    continue

                # Skip signal stale > 30 menit
                ts_str = signal.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if (datetime.now() - ts) > timedelta(minutes=15):
                            processed.add(mint)
                            continue
                    except:
                        pass

                executed = await process_signal(signal)
                processed.add(mint)

                if executed:
                    await asyncio.sleep(5)

            if len(processed) > 500:
                processed = set(list(processed)[-100:])
            # Persist processed set
            try:
                _proc_file = Path("/root/.processed_signals.json")
                _proc_file.write_text(json.dumps(list(processed)))
            except:
                pass

        except Exception as e:
            logger.error(f"Auto trader error: {e}", exc_info=True)

        await asyncio.sleep(30)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    asyncio.run(auto_trader_loop())
