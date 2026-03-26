import json
import os
from datetime import datetime, timedelta

BLACKLIST_FILE = '/root/token_blacklist.json'
COOLDOWN_HOURS = 6

def load_blacklist():
    if not os.path.exists(BLACKLIST_FILE):
        return {}
    try:
        with open(BLACKLIST_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_blacklist(bl):
    with open(BLACKLIST_FILE, 'w') as f:
        json.dump(bl, f)

def is_blacklisted(address):
    bl = load_blacklist()
    if address not in bl:
        return False
    rejected_at = datetime.fromisoformat(bl[address])
    return datetime.now() < rejected_at + timedelta(hours=COOLDOWN_HOURS)

def add_to_blacklist(address, reason="rejected"):
    bl = load_blacklist()
    bl[address] = datetime.now().isoformat()
    save_blacklist(bl)
    print(f"[BLACKLIST] {address[:8]}... added ({reason})")

def cleanup_blacklist():
    """Hapus entry yang udah expired."""
    bl = load_blacklist()
    now = datetime.now()
    cleaned = {k: v for k, v in bl.items()
               if now < datetime.fromisoformat(v) + timedelta(hours=COOLDOWN_HOURS)}
    save_blacklist(cleaned)
    return len(bl) - len(cleaned)
