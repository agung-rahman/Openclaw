"""
risk_manager.py - Monitor dan enforce risk rules
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

RISK_CONFIG_FILE = Path("/root/.risk_config.json")
POSITIONS_FILE = Path("/root/.openclaw_positions.json")
TRADE_HISTORY_FILE = Path("/root/.trade_history.json")

DEFAULT_CONFIG = {
    "max_open_positions": 3,
    "max_daily_loss_usd": 10.0,
    "max_single_trade_usd": 5.0,
    "min_rugcheck_score": 300,
    "max_bundle_pct": 30,
    "trading_paused": False,
    "pause_reason": ""
}


def get_config() -> dict:
    if RISK_CONFIG_FILE.exists():
        return json.loads(RISK_CONFIG_FILE.read_text())
    save_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG


def save_config(config: dict):
    RISK_CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_open_positions() -> dict:
    if POSITIONS_FILE.exists():
        return json.loads(POSITIONS_FILE.read_text())
    return {}


def get_daily_loss() -> float:
    """Hitung total loss hari ini."""
    if not TRADE_HISTORY_FILE.exists():
        return 0.0
    
    history = json.loads(TRADE_HISTORY_FILE.read_text())
    today = datetime.now().date()
    daily_loss = 0.0
    
    for trade in history:
        try:
            ts = datetime.fromisoformat(trade["timestamp"]).date()
            if ts != today:
                continue
            invested = trade.get("amount_invested_usd", 0)
            returned = trade.get("amount_returned_usd", 0)
            if returned < invested:
                daily_loss += (invested - returned)
        except:
            continue
    
    return daily_loss


def check_can_trade(token_data: dict = None) -> Tuple[bool, str]:
    """
    Cek apakah boleh trade.
    Return: (can_trade, reason)
    """
    config = get_config()
    
    # Cek manual pause
    if config.get("trading_paused"):
        return False, f"Trading di-pause: {config.get('pause_reason', 'manual')}"
    
    # Cek max open positions
    positions = get_open_positions()
    if len(positions) >= config["max_open_positions"]:
        return False, f"Max posisi tercapai ({len(positions)}/{config['max_open_positions']})"
    
    # Cek daily loss
    daily_loss = get_daily_loss()
    if daily_loss >= config["max_daily_loss_usd"]:
        # Auto pause
        config["trading_paused"] = True
        config["pause_reason"] = f"Daily loss limit ${config['max_daily_loss_usd']} tercapai"
        save_config(config)
        return False, f"Daily loss limit tercapai! Total loss hari ini: ${daily_loss:.2f}"
    
    # Cek token data kalau ada
    if token_data:
        if token_data.get("rugcheck_score", 0) < config["min_rugcheck_score"] and token_data.get("rugcheck_score", 0) > 0:
            return False, f"Rugcheck terlalu rendah: {token_data.get('rugcheck_score')}"
        if token_data.get("bundle_pct", 0) > config["max_bundle_pct"]:
            return False, f"Bundle terlalu tinggi: {token_data.get('bundle_pct')}%"
    
    return True, "OK"


def get_risk_status() -> str:
    """Get human-readable risk status."""
    config = get_config()
    positions = get_open_positions()
    daily_loss = get_daily_loss()
    
    status = "🛡️ Risk Status:\n"
    status += f"Posisi: {len(positions)}/{config['max_open_positions']}\n"
    status += f"Loss hari ini: ${daily_loss:.2f}/${config['max_daily_loss_usd']:.2f}\n"
    
    if config.get("trading_paused"):
        status += f"⏸️ PAUSED: {config.get('pause_reason', '')}\n"
    else:
        status += "▶️ Trading aktif\n"
    
    return status


def pause_trading(reason: str = "manual"):
    config = get_config()
    config["trading_paused"] = True
    config["pause_reason"] = reason
    save_config(config)


def resume_trading():
    config = get_config()
    config["trading_paused"] = False
    config["pause_reason"] = ""
    save_config(config)


def update_config(key: str, value):
    config = get_config()
    config[key] = value
    save_config(config)
