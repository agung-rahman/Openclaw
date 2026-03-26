"""
position_monitor_v2.py - Monitor posisi, auto TP/SL
Lebih robust: multi-source price, error handling proper
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
HELIUS_KEY = os.getenv("HELIUS_API_KEY_EXECUTOR", "")


async def send_tg(text: str):
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{API}/sendMessage", json={
                "chat_id": CHAT_ID, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True
            })
    except Exception as e:
        logger.error(f"TG send error: {e}")


async def get_token_price(mint: str, session: aiohttp.ClientSession) -> float:
    """Ambil harga token — DexScreener dulu, fallback ke pump.fun."""
    # 1. DexScreener
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            pairs = data.get("pairs", [])
            if pairs:
                price = float(pairs[0].get("priceUsd", 0) or 0)
                if price > 0:
                    return price
    except:
        pass

    # 2. Pump.fun bonding curve
    try:
        async with session.get(
            f"https://frontend-api.pump.fun/coins/{mint}",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            if r.status == 200:
                d = await r.json()
                virt_sol = d.get("virtual_sol_reserves", 0) / 1e9
                virt_tokens = d.get("virtual_token_reserves", 0) / 1e6
                if virt_sol > 0 and virt_tokens > 0:
                    # Get SOL price
                    sol_price = 87.0
                    try:
                        async with session.get(
                            "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                            timeout=aiohttp.ClientTimeout(total=4)
                        ) as r2:
                            d2 = await r2.json()
                            sol_price = float(d2.get("pair", {}).get("priceUsd", 87) or 87)
                    except:
                        pass
                    return (virt_sol / virt_tokens) * sol_price
    except:
        pass

    return 0.0


async def monitor_positions():
    """Main monitor loop."""
    import sys
    sys.path.insert(0, '/root')
    
    logger.info("👁️ Position monitor v2 started!")
    
    while True:
        try:
            pos_file = Path("/root/.openclaw_positions.json")
            cfg_file = Path("/root/.risk_config.json")
            
            if not pos_file.exists():
                await asyncio.sleep(15)
                continue
            
            positions = json.loads(pos_file.read_text())
            open_positions = {k: v for k, v in positions.items() 
                            if v.get("status") == "open"}
            
            if not open_positions:
                await asyncio.sleep(15)
                continue

            # Auto-sync: close posisi yang tokennya udah ga ada di wallet
            from pump_executor import get_token_balance as _gtb
            for _mint, _pos in list(open_positions.items()):
                _sym = _pos.get("token_symbol", "?")
                try:
                    _bal = await _gtb(_mint)
                    if _bal == 0:
                        # Cek peak PnL dulu
                        _buy_px = _pos.get("buy_price_usd", 0)
                        _peak_px = _pos.get("peak_price_usd", _buy_px)
                        _peak_pnl = (_peak_px - _buy_px) / _buy_px * 100 if _buy_px else 0
                        positions[_mint]["status"] = "closed"
                        positions[_mint]["close_reason"] = f"auto-sync: no balance in wallet (peak PnL was {_peak_pnl:+.1f}%)"
                        positions[_mint]["close_time"] = datetime.now().isoformat()
                        pos_file.write_text(json.dumps(positions, indent=2))
                        logger.info(f"Auto-sync closed {_sym} — no balance in wallet")
                        await send_tg(f"🔄 <b>Auto-sync</b> — {_sym} ditutup (token ga ada di wallet)")
                        open_positions = {k:v for k,v in positions.items() if v.get("status")=="open"}
                except Exception as _se:
                    logger.warning(f"Auto-sync check failed for {_sym}: {_se}")
            
            config = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
            tp_pct = config.get("take_profit_pct", 30)
            sl_pct = config.get("stop_loss_pct", 15)
            
            logger.info(f"Monitoring {len(open_positions)} positions (TP={tp_pct}% SL={sl_pct}%)")
            
            async with aiohttp.ClientSession() as session:
                for mint, pos in list(open_positions.items()):
                    symbol = pos.get("token_symbol", "?")
                    buy_price = pos.get("buy_price_usd", 0)
                    
                    if not buy_price:
                        # Coba fetch harga sekarang sebagai buy_price
                        fetched = await get_token_price(mint, session)
                        if fetched:
                            positions[mint]["buy_price_usd"] = fetched
                            pos_file.write_text(json.dumps(positions, indent=2))
                            buy_price = fetched
                            logger.info(f"{symbol}: buy_price set from current price ${fetched:.8f}")
                        else:
                            logger.warning(f"{symbol}: no buy_price, skipping")
                            continue
                    
                    # Time-based exit — auto sell kalau 30 menit ga gerak
                    buy_time_str = pos.get("buy_time", "")
                    if buy_time_str:
                        from datetime import datetime, timedelta
                        buy_time = datetime.fromisoformat(buy_time_str)
                        age_minutes = (datetime.now() - buy_time).total_seconds() / 60
                        
                        # Kalau udah 30 menit dan PnL antara -5% sampai +5% (ga gerak)
                        if age_minutes >= 15:
                            current_price_check = await get_token_price(mint, session)
                            if current_price_check and buy_price:
                                pnl_check = (current_price_check - buy_price) / buy_price * 100
                                if -5 <= pnl_check <= 5:
                                    # Cek volume dulu — kalau masih ada volume, mungkin akumulasi, tahan sampai 60 menit
                                    has_volume = False
                                    try:
                                        async with session.get(
                                            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
                                            timeout=aiohttp.ClientTimeout(total=5)
                                        ) as _r:
                                            _d = await _r.json()
                                            _pairs = _d.get("pairs", [])
                                            if _pairs:
                                                vol_1h = float(_pairs[0].get("volume", {}).get("h1", 0) or 0)
                                                txns_1h = _pairs[0].get("txns", {}).get("h1", {})
                                                buys_1h = int(txns_1h.get("buys", 0) or 0)
                                                has_volume = vol_1h > 500 or buys_1h > 10
                                                logger.info(f"{symbol}: vol_1h=${vol_1h:.0f} buys_1h={buys_1h} has_volume={has_volume}")
                                    except:
                                        pass
                                    # Kalau masih ada volume, tahan sampai 60 menit
                                    if has_volume and age_minutes < 60:
                                        logger.info(f"{symbol}: flat tapi volume ada — tunggu sampai 60 menit")
                                        continue
                                    logger.info(f"{symbol}: timeout, PnL={pnl_check:+.1f}% — selling dead token")
                                    try:
                                        from pump_executor import sell
                                        # Retry sell sampai 3x
                                        result = {"success": False, "error": "not attempted"}
                                        for _attempt in range(3):
                                            result = await sell(mint, 100, symbol)
                                            if result.get("success"):
                                                break
                                            logger.warning(f"{symbol}: sell attempt {_attempt+1}/3 gagal: {result.get('error')} — retry 5s")
                                            await asyncio.sleep(5)
                                        # Kalau masih gagal, cek balance
                                        if not result.get("success"):
                                            _bal_after = await _gtb(mint)
                                            if _bal_after == 0:
                                                logger.warning(f"{symbol}: sell gagal tapi balance 0 — mark closed")
                                                result = {"success": True, "tx": "sold-unknown"}
                                            else:
                                                logger.error(f"{symbol}: sell GAGAL 3x, token masih ada {_bal_after:.0f}")
                                                await asyncio.sleep(30)
                                                continue
                                        if result.get("success"):
                                            positions[mint]["status"] = "closed"
                                            positions[mint]["close_reason"] = f"⏰ TIMEOUT 30min (PnL={pnl_check:+.1f}%)"
                                            positions[mint]["pnl_pct"] = round(pnl_check, 2)
                                            positions[mint]["close_time"] = datetime.now().isoformat()
                                            pos_file.write_text(json.dumps(positions, indent=2))
                                            await send_tg(
                                                f"\u23f0 <b>TIMEOUT EXIT — {symbol}</b>\n\n"
                                                f"30 menit ga gerak\n"
                                                f"\U0001f4b0 PnL: {pnl_check:+.1f}%\n"
                                                f"\U0001f517 TX: https://solscan.io/tx/{result['tx']}"
                                            )
                                    except Exception as e:
                                        logger.error(f"Timeout sell error: {e}")
                                    continue
                    
                    current_price = await get_token_price(mint, session)
                    
                    if not current_price:
                        logger.warning(f"{symbol}: cannot get price")
                        continue
                    
                    pnl_pct = (current_price - buy_price) / buy_price * 100
                    logger.info(f"{symbol}: ${buy_price:.8f} → ${current_price:.8f} | PnL={pnl_pct:+.1f}%")
                    
                    # Update peak price untuk trailing stop
                    peak_price = pos.get("peak_price_usd", buy_price)
                    if current_price > peak_price:
                        peak_price = current_price
                        positions[mint]["peak_price_usd"] = peak_price
                        pos_file.write_text(json.dumps(positions, indent=2))
                    
                    peak_pnl = (peak_price - buy_price) / buy_price * 100
                    drawdown_from_peak = (current_price - peak_price) / peak_price * 100
                    
                    should_sell = False
                    reason = ""
                    
                    # Trailing stop — aktif setelah naik > 20%
                    if peak_pnl >= 35 and drawdown_from_peak <= -15:
                        should_sell = True
                        reason = f"📉 TRAILING STOP (peak={peak_pnl:+.1f}% | drawdown={drawdown_from_peak:.1f}%)"
                    elif pnl_pct >= tp_pct:
                        should_sell = True
                        reason = f"✅ TP +{pnl_pct:.1f}%"
                    elif pnl_pct <= -sl_pct:
                        should_sell = True
                        reason = f"🛑 SL {pnl_pct:.1f}%"
                    
                    if should_sell:
                        logger.info(f"{reason} — SELLING {symbol}")
                        try:
                            from pump_executor import sell, get_token_balance as _gtb
                            # Cek balance dulu — kalau 0 langsung mark closed, jangan spam sell
                            _bal = await _gtb(mint)
                            if _bal == 0:
                                logger.warning(f"{symbol}: no balance in wallet — auto closing")
                                positions[mint]["status"] = "closed"
                                positions[mint]["close_reason"] = f"auto-closed: no balance ({reason})"
                                positions[mint]["close_time"] = datetime.now().isoformat()
                                pos_file.write_text(json.dumps(positions, indent=2))
                                continue
                            result = await sell(mint, 100, symbol)
                            
                            if result.get("success"):
                                positions[mint]["status"] = "closed"
                                positions[mint]["close_reason"] = reason
                                positions[mint]["pnl_pct"] = round(pnl_pct, 2)
                                positions[mint]["close_time"] = datetime.now().isoformat()
                                pos_file.write_text(json.dumps(positions, indent=2))
                                
                                # Update wallet reputation
                                try:
                                    from wallet_reputation import record_trade_result
                                    wallet = pos.get("wallet_source", "")
                                    if wallet:
                                        record_trade_result(wallet, symbol, pnl_pct)
                                except:
                                    pass
                                
                                # Update daily stats
                                try:
                                    stats_file = Path("/root/.daily_stats.json")
                                    stats = json.loads(stats_file.read_text()) if stats_file.exists() else {}
                                    invested = pos.get("amount_invested_sol", 0.02)
                                    returned = invested * (1 + pnl_pct/100)
                                    stats["total_returned_sol"] = stats.get("total_returned_sol", 0) + returned
                                    if pnl_pct < 0:
                                        stats["losses"] = stats.get("losses", 0) + 1
                                    stats_file.write_text(json.dumps(stats, indent=2))
                                except:
                                    pass
                                
                                emoji = "🟢" if pnl_pct > 0 else "🔴"
                                await send_tg(
                                    f"{emoji} <b>AUTO SELL — {symbol}</b>\n\n"
                                    f"{reason}\n"
                                    f"💰 PnL: {pnl_pct:+.1f}%\n"
                                    f"🔗 <a href='https://solscan.io/tx/{result['tx']}'>View TX</a>"
                                )
                                logger.info(f"✅ Sold {symbol} — {reason}")
                            else:
                                logger.error(f"Sell failed: {result.get('error')}")
                                await send_tg(f"⚠️ Sell failed for {symbol}: {result.get('error')}")
                        except Exception as e:
                            logger.error(f"Sell error {symbol}: {e}", exc_info=True)
                            await send_tg(f"⚠️ Sell error {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"Monitor loop error: {e}", exc_info=True)
        
        await asyncio.sleep(2)  # cek tiap 2 detik


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    asyncio.run(monitor_positions())
