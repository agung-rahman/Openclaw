"""
wallet_manager.py - Generate & manage bot trading wallet
Run sekali: python3 wallet_manager.py --generate
"""

import json
import os
import argparse
from pathlib import Path

try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
except ImportError:
    print("Installing solders...")
    os.system("pip3 install solders --break-system-packages")
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

WALLET_FILE = Path("/root/.openclaw_wallet.json")


def generate_wallet():
    """Generate wallet baru dan simpan ke file."""
    if WALLET_FILE.exists():
        print(f"⚠️  Wallet sudah ada di {WALLET_FILE}")
        print("Kalau mau generate ulang, hapus file dulu.")
        return load_wallet()

    keypair = Keypair()
    wallet_data = {
        "public_key": str(keypair.pubkey()),
        "private_key": list(bytes(keypair)),  # 64 bytes
    }

    # Simpan dengan permission ketat
    WALLET_FILE.write_text(json.dumps(wallet_data, indent=2))
    WALLET_FILE.chmod(0o600)

    print("✅ Wallet baru berhasil di-generate!")
    print(f"📍 Public Key: {wallet_data['public_key']}")
    print(f"💾 Tersimpan di: {WALLET_FILE}")
    print()
    print("⚠️  PENTING:")
    print("1. Fund wallet ini dengan SOL dulu (minimal 0.1 SOL untuk gas)")
    print("2. Fund dengan USDC/USDT untuk modal trading")
    print("3. JANGAN share private key ke siapapun!")
    print(f"4. Backup file: {WALLET_FILE}")

    return wallet_data


def load_wallet():
    """Load wallet dari file."""
    if not WALLET_FILE.exists():
        raise FileNotFoundError(
            f"Wallet file tidak ditemukan: {WALLET_FILE}\n"
            "Jalankan: python3 wallet_manager.py --generate"
        )

    data = json.loads(WALLET_FILE.read_text())
    return data


def get_keypair() -> Keypair:
    """Return Keypair object untuk signing transaksi."""
    data = load_wallet()
    private_key_bytes = bytes(data["private_key"])
    return Keypair.from_bytes(private_key_bytes)


def get_public_key() -> str:
    """Return public key string."""
    data = load_wallet()
    return data["public_key"]


def check_balance(public_key: str, rpc_url: str = "https://api.mainnet-beta.solana.com"):
    """Cek balance SOL wallet."""
    import urllib.request
    import json

    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [public_key]
    }).encode()

    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    lamports = result.get("result", {}).get("value", 0)
    sol = lamports / 1_000_000_000
    print(f"💰 Balance: {sol:.4f} SOL")
    return sol


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenClaw Wallet Manager")
    parser.add_argument("--generate", action="store_true", help="Generate wallet baru")
    parser.add_argument("--show", action="store_true", help="Tampilkan public key")
    parser.add_argument("--balance", action="store_true", help="Cek balance SOL")
    args = parser.parse_args()

    if args.generate:
        generate_wallet()
    elif args.show:
        pk = get_public_key()
        print(f"📍 Public Key: {pk}")
    elif args.balance:
        pk = get_public_key()
        check_balance(pk)
    else:
        parser.print_help()
