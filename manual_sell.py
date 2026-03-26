"""
manual_sell.py - Sell token secara manual
Usage:
    python3 /root/manual_sell.py --list              # lihat open positions
    python3 /root/manual_sell.py --sell lolcoin      # sell token by symbol
    python3 /root/manual_sell.py --sell all          # sell semua posisi
    python3 /root/manual_sell.py --sell lolcoin --pct 50  # sell 50%
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, '/root')

from wallet_manager import get_keypair
from trade_executor import TradeExecutor, Position
from datetime import datetime

HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={__import__('os').getenv('HELIUS_API_KEY', '')}"
POSITIONS_FILE = Path("/root/.openclaw_positions.json")


def load_positions():
    if not POSITIONS_FILE.exists():
        return {}
    return json.loads(POSITIONS_FILE.read_text())


def remove_position(token_mint: str):
    positions = load_positions()
    if token_mint in positions:
        del positions[token_mint]
        POSITIONS_FILE.write_text(json.dumps(positions, indent=2))


async def list_positions(executor: TradeExecutor):
    positions = load_positions()
    if not positions:
        print("📭 Ga ada open positions")
        return

    print(f"\n{'='*60}")
    print(f"{'OPEN POSITIONS':^60}")
    print(f"{'='*60}")

    for mint, pos_data in positions.items():
        symbol = pos_data.get("token_symbol", "?")
        buy_price = pos_data.get("buy_price_usd", 0)
        amount = pos_data.get("amount_token", 0)
        invested = pos_data.get("amount_invested_usd", 0)
        tp1_hit = pos_data.get("tp1_hit", False)

        # Get current price
        current_price = await executor.get_token_price_usd(mint)
        if current_price:
            pnl_pct = ((current_price - buy_price) / buy_price) * 100
            current_value = amount * current_price
            pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
        else:
            pnl_pct = 0
            current_value = 0
            pnl_emoji = "⚪"

        print(f"\n🪙 {symbol}")
        print(f"   Mint: {mint[:20]}...")
        print(f"   Amount: {amount:,.2f} tokens")
        print(f"   Buy price: ${buy_price:.8f}")
        print(f"   Current: ${current_price:.8f}" if current_price else "   Current: N/A")
        print(f"   {pnl_emoji} PnL: {pnl_pct:+.1f}%")
        print(f"   Invested: ${invested:.2f} | Now: ${current_value:.2f}")
        print(f"   TP1 hit: {'✅' if tp1_hit else '❌'}")
        print(f"   TX Buy: https://solscan.io/tx/{pos_data.get('tx_buy', 'N/A')}")

    print(f"\n{'='*60}\n")


async def sell_token(executor: TradeExecutor, symbol_or_mint: str, pct: float = 100):
    positions = load_positions()

    # Cari token by symbol atau mint
    target_mint = None
    target_pos = None

    for mint, pos_data in positions.items():
        if (pos_data.get("token_symbol", "").lower() == symbol_or_mint.lower() or
                mint.lower() == symbol_or_mint.lower()):
            target_mint = mint
            target_pos = pos_data
            break

    if not target_pos:
        print(f"❌ Token '{symbol_or_mint}' tidak ditemukan di open positions")
        print("Gunakan --list untuk lihat posisi yang ada")
        return

    symbol = target_pos.get("token_symbol", "?")
    amount = target_pos.get("amount_token", 0)
    buy_price = target_pos.get("buy_price_usd", 0)
    invested = target_pos.get("amount_invested_usd", 0)

    # Get current price
    current_price = await executor.get_token_price_usd(target_mint)
    pnl_pct = ((current_price - buy_price) / buy_price * 100) if current_price else 0

    sell_amount = amount * (pct / 100)

    print(f"\n{'='*50}")
    print(f"🔴 MANUAL SELL: {symbol}")
    print(f"   Amount to sell: {sell_amount:,.2f} ({pct:.0f}%)")
    print(f"   Buy price: ${buy_price:.8f}")
    print(f"   Current price: ${current_price:.8f}" if current_price else "   Current: N/A")
    print(f"   PnL: {pnl_pct:+.1f}%")
    print(f"{'='*50}")

    # Konfirmasi
    confirm = input(f"\nKonfirmasi sell {pct:.0f}% {symbol}? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Dibatalin")
        return

    # Buat Position object
    pos = Position(
        token_mint=target_mint,
        token_symbol=symbol,
        buy_price_usd=buy_price,
        amount_token=amount,
        amount_invested_usd=invested,
        buy_time=datetime.now(),
        tp1_hit=target_pos.get("tp1_hit", False),
    )

    # Execute sell
    print(f"\n⏳ Executing sell...")
    tx = await executor.sell_token(pos, sell_pct=pct/100, reason="MANUAL_SELL")

    if tx:
        print(f"\n✅ SELL BERHASIL!")
        print(f"   TX: https://solscan.io/tx/{tx}")

        # Update atau hapus position
        if pct >= 100:
            remove_position(target_mint)
            print(f"   Position {symbol} dihapus dari tracker")
        else:
            # Update amount
            positions[target_mint]["amount_token"] = amount * (1 - pct/100)
            POSITIONS_FILE.write_text(json.dumps(positions, indent=2))
            print(f"   Position {symbol} diupdate (sisa {100-pct:.0f}%)")
    else:
        print(f"\n❌ SELL GAGAL! Cek log untuk detail")
        print(f"   Coba sell manual via Phantom/Jupiter")


async def sell_all(executor: TradeExecutor):
    positions = load_positions()
    if not positions:
        print("📭 Ga ada open positions")
        return

    print(f"\n⚠️  Akan sell SEMUA {len(positions)} posisi!")
    confirm = input("Konfirmasi? (y/n): ").strip().lower()
    if confirm != 'y':
        print("❌ Dibatalin")
        return

    for mint, pos_data in list(positions.items()):
        symbol = pos_data.get("token_symbol", "?")
        print(f"\n🔴 Selling {symbol}...")

        pos = Position(
            token_mint=mint,
            token_symbol=symbol,
            buy_price_usd=pos_data.get("buy_price_usd", 0),
            amount_token=pos_data.get("amount_token", 0),
            amount_invested_usd=pos_data.get("amount_invested_usd", 0),
            buy_time=datetime.now(),
            tp1_hit=pos_data.get("tp1_hit", False),
        )

        tx = await executor.sell_token(pos, sell_pct=1.0, reason="MANUAL_SELL_ALL")
        if tx:
            print(f"   ✅ {symbol} sold! TX: https://solscan.io/tx/{tx}")
            remove_position(mint)
        else:
            print(f"   ❌ {symbol} sell GAGAL!")

    print("\n✅ Selesai!")


async def main():
    parser = argparse.ArgumentParser(description="OpenClaw Manual Sell")
    parser.add_argument("--list", action="store_true", help="Lihat open positions")
    parser.add_argument("--sell", type=str, help="Sell token (symbol/mint/all)")
    parser.add_argument("--pct", type=float, default=100, help="Persentase yang dijual (default: 100)")
    args = parser.parse_args()

    keypair = get_keypair()
    executor = TradeExecutor(keypair, rpc_url=HELIUS_RPC)

    if args.list:
        await list_positions(executor)
    elif args.sell:
        if args.sell.lower() == "all":
            await sell_all(executor)
        else:
            await sell_token(executor, args.sell, args.pct)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
