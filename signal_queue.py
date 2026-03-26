import json
from pathlib import Path
from datetime import datetime

QUEUE_FILE = Path("/root/.signal_queue.json")

def add_signal(signal: dict):
    queue = get_queue()
    
    # Dedup — skip kalau mint sama sudah ada di queue dalam 30 menit
    mint = signal.get("mint", "")
    if mint:
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(minutes=30)
        for existing in queue:
            if existing.get("mint") == mint:
                try:
                    ts = datetime.fromisoformat(existing.get("timestamp", "2000-01-01"))
                    if ts > cutoff:
                        return  # Skip duplikat
                except:
                    pass

    signal["timestamp"] = datetime.now().isoformat()
    queue.append(signal)
    
    # Max 50 signal tersimpan
    if len(queue) > 50:
        queue = queue[-50:]
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))

def get_queue() -> list:
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except:
            return []
    return []

def clear_queue():
    QUEUE_FILE.write_text("[]")

def remove_signal(mint: str):
    """Hapus signal spesifik dari queue by mint."""
    queue = get_queue()
    queue = [s for s in queue if s.get("mint") != mint]
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))
