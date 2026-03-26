"""
wallet_reputation.py - Track win rate per wallet
Bot kasih bobot lebih ke wallet yang konsisten profit
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

REPUTATION_FILE = Path("/root/.wallet_reputation.json")

def load_reputation() -> dict:
    if REPUTATION_FILE.exists():
        return json.loads(REPUTATION_FILE.read_text())
    return {}

def save_reputation(data: dict):
    REPUTATION_FILE.write_text(json.dumps(data, indent=2))

def get_wallet_score(wallet_name: str) -> float:
    """
    Return score 0-1 berdasarkan track record wallet.
    1.0 = perfect win rate, 0.5 = unknown/new, 0.0 = always loses
    """
    rep = load_reputation()
    if wallet_name not in rep:
        return 0.5  # unknown wallet, neutral
    
    w = rep[wallet_name]
    wins = w.get("wins", 0)
    losses = w.get("losses", 0)
    total = wins + losses
    
    if total < 3:
        return 0.5  # belum cukup data
    
    win_rate = wins / total
    
    # Bonus kalau average profit tinggi
    avg_profit = w.get("avg_profit_pct", 0)
    profit_bonus = min(avg_profit / 200, 0.2)  # max +0.2 bonus
    
    return min(1.0, win_rate + profit_bonus)

def record_trade_result(wallet_name: str, token: str, profit_pct: float):
    """Record hasil trade dari wallet tertentu."""
    rep = load_reputation()
    
    if wallet_name not in rep:
        rep[wallet_name] = {
            "wins": 0, "losses": 0,
            "total_profit_pct": 0, "trades": [],
            "avg_profit_pct": 0
        }
    
    w = rep[wallet_name]
    
    if profit_pct > 0:
        w["wins"] = w.get("wins", 0) + 1
    else:
        w["losses"] = w.get("losses", 0) + 1
    
    w["total_profit_pct"] = w.get("total_profit_pct", 0) + profit_pct
    total = w.get("wins", 0) + w.get("losses", 0)
    w["avg_profit_pct"] = w["total_profit_pct"] / total if total > 0 else 0
    
    # Keep last 20 trades
    trades = w.get("trades", [])
    trades.append({
        "token": token,
        "profit_pct": profit_pct,
        "timestamp": datetime.now().isoformat()
    })
    w["trades"] = trades[-20:]
    
    rep[wallet_name] = w
    save_reputation(rep)
    logger.info(f"Recorded {wallet_name}: {token} {profit_pct:+.1f}%")

def get_top_wallets(n: int = 10) -> list:
    """Return top N wallets berdasarkan win rate."""
    rep = load_reputation()
    scored = []
    for name, data in rep.items():
        total = data.get("wins", 0) + data.get("losses", 0)
        if total < 2:
            continue
        win_rate = data.get("wins", 0) / total * 100
        scored.append({
            "wallet": name,
            "win_rate": round(win_rate, 1),
            "trades": total,
            "avg_profit": round(data.get("avg_profit_pct", 0), 1)
        })
    return sorted(scored, key=lambda x: x["win_rate"], reverse=True)[:n]

def get_reputation_summary() -> str:
    """Summary reputasi semua wallet untuk Telegram."""
    top = get_top_wallets(10)
    if not top:
        return "📊 Belum ada data reputasi wallet. Bot perlu trade dulu buat build track record."
    
    msg = "📊 <b>Wallet Reputation:</b>\n\n"
    for i, w in enumerate(top, 1):
        emoji = "🟢" if w["win_rate"] >= 60 else "🟡" if w["win_rate"] >= 40 else "🔴"
        msg += f"{i}. {emoji} <b>{w['wallet']}</b>\n"
        msg += f"   Win rate: {w['win_rate']}% | {w['trades']} trades | avg {w['avg_profit']:+.1f}%\n"
    return msg
