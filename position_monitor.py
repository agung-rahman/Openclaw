"""
position_monitor.py - Monitor open positions, eksekusi TP/SL otomatis
Strategy:
  - TP1: Jual 50% di 2x → recover modal + profit
  - TP2: Jual sisa 50% di 3x
  - SL: Jual semua di -30%
  - Emergency SL: Jual semua kalau harga turun >50% setelah TP1
"""

import asyncio
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

from trade_executor import TradeExecutor, Position

logger = logging.getLogger(__name__)

# TP/SL Config
TP1_MULTIPLIER = 2.0      # Jual 50% di 2x
TP2_MULTIPLIER = 3.0      # Jual sisa 50% di 3x
SL_PCT = -15.0            # Stop loss -15%
POST_TP1_SL_PCT = -50.0   # Emergency SL setelah TP1 (dari harga beli)
MAX_HOLD_HOURS = 24       # Auto-exit setelah 24 jam
TRAILING_STOP_PCT = 20.0  # Trailing stop 20% dari highest price

# Monitor config
CHECK_INTERVAL_SEC = 15   # Cek harga tiap 15 detik
POSITIONS_FILE = Path("/root/.openclaw_positions.json")
MAX_OPEN_POSITIONS = 3

def save_positions(positions: Dict[str, Position]):
    """Simpan open positions ke file."""
    data = {mint: pos.to_dict() for mint, pos in positions.items()}
    POSITIONS_FILE.write_text(json.dumps(data, indent=2))


def load_positions() -> Dict[str, dict]:
    """Load positions dari file (raw dict)."""
    if not POSITIONS_FILE.exists():
        return {}
    return json.loads(POSITIONS_FILE.read_text())


class PositionMonitor:
    def __init__(
        self,
        executor: TradeExecutor,
        notify_callback: Optional[Callable] = None  # fungsi async untuk kirim notif Telegram
    ):
        self.executor = executor
        self.positions: Dict[str, Position] = {}
        self.notify = notify_callback
        self.running = False
        self.highest_prices: Dict[str, float] = {}  # tracking highest price per token

    async def add_position(self, position: Position):
        """Tambah position baru ke monitor."""
        self.positions[position.token_mint] = position
        save_positions(self.positions)
        logger.info(f"📈 Position added: {position.token_symbol}")

        if self.notify:
            msg = (
                f"🟢 **BUY EXECUTED**\n"
                f"Token: {position.token_symbol}\n"
                f"Amount: {position.amount_token:.2f} tokens\n"
                f"Invested: ${position.amount_invested_usd:.2f}\n"
                f"Buy price: ${position.buy_price_usd:.8f}\n"
                f"TP1: ${position.buy_price_usd * TP1_MULTIPLIER:.8f} (2x)\n"
                f"TP2: ${position.buy_price_usd * TP2_MULTIPLIER:.8f} (3x)\n"
                f"SL: ${position.buy_price_usd * (1 + SL_PCT/100):.8f} (-15%)\n"
                f"TX: https://solscan.io/tx/{position.tx_buy}"
            )
            await self.notify(msg)

    async def remove_position(self, token_mint: str):
        """Hapus position dari monitor."""
        if token_mint in self.positions:
            del self.positions[token_mint]
            save_positions(self.positions)
        self.highest_prices.pop(token_mint, None)

    def get_open_count(self) -> int:
        return len([p for p in self.positions.values() if p.status == "open" or p.status == "tp1_hit"])

    async def check_position(self, position: Position):
        """Cek satu position dan eksekusi TP/SL kalau perlu."""
        current_price = await self.executor.get_token_price_usd(position.token_mint)
        if not current_price:
            logger.warning(f"⚠️ Cannot get price for {position.token_symbol}, skipping")
            return

        pnl_pct = position.pnl_pct(current_price)
        hold_hours = (datetime.now() - position.buy_time).total_seconds() / 3600

        # Update highest price untuk trailing stop
        mint = position.token_mint
        if mint not in self.highest_prices:
            self.highest_prices[mint] = current_price
        elif current_price > self.highest_prices[mint]:
            self.highest_prices[mint] = current_price

        highest = self.highest_prices[mint]
        trailing_stop_price = highest * (1 - TRAILING_STOP_PCT / 100)
        trailing_drop_pct = ((current_price - highest) / highest) * 100

        logger.info(
            f"📊 {position.token_symbol}: "
            f"${current_price:.8f} | PnL: {pnl_pct:+.1f}% | "
            f"Hold: {hold_hours:.1f}h | TP1: {'✅' if position.tp1_hit else '❌'} | "
            f"Highest: ${highest:.8f} | Trail: {trailing_drop_pct:.1f}%"
        )

        # === TRAILING STOP (hanya aktif setelah TP1 atau profit > 30%) ===
        if position.tp1_hit or pnl_pct >= 30:
            if current_price <= trailing_stop_price:
                logger.warning(
                    f"🔴 TRAILING STOP hit for {position.token_symbol}: "
                    f"${current_price:.8f} <= ${trailing_stop_price:.8f} "
                    f"({trailing_drop_pct:.1f}% from highest)"
                )
                await self._execute_trailing_stop(position, current_price, pnl_pct, trailing_drop_pct)
                return

        # === STOP LOSS ===
        if pnl_pct <= SL_PCT and not position.tp1_hit:
            logger.warning(f"🔴 SL hit for {position.token_symbol}: {pnl_pct:.1f}%")
            await self._execute_sl(position, current_price, pnl_pct)
            return

        # === EMERGENCY SL setelah TP1 ===
        if position.tp1_hit and pnl_pct <= POST_TP1_SL_PCT:
            logger.warning(f"🔴 Post-TP1 emergency SL for {position.token_symbol}: {pnl_pct:.1f}%")
            await self._execute_tp2_or_emergency(position, current_price, pnl_pct, emergency=True)
            return

        # === TP1: 2x → Jual 50% ===
        if not position.tp1_hit and pnl_pct >= (TP1_MULTIPLIER - 1) * 100:
            logger.info(f"🎯 TP1 hit for {position.token_symbol}: {pnl_pct:.1f}%!")
            await self._execute_tp1(position, current_price, pnl_pct)
            return

        # === TP2: 3x → Jual sisa 50% ===
        if position.tp1_hit and pnl_pct >= (TP2_MULTIPLIER - 1) * 100:
            logger.info(f"🎯🎯 TP2 hit for {position.token_symbol}: {pnl_pct:.1f}%!")
            await self._execute_tp2_or_emergency(position, current_price, pnl_pct)
            return

        # === Time-based exit: 24 jam ===
        if hold_hours >= MAX_HOLD_HOURS:
            logger.info(f"⏰ Time exit for {position.token_symbol}: held {hold_hours:.1f}h")
            await self._execute_time_exit(position, current_price, pnl_pct)
            return

    async def _execute_sl(self, position: Position, current_price: float, pnl_pct: float):
        """Eksekusi stop loss."""
        tx = await self.executor.sell_token(position, sell_pct=1.0, reason="STOP_LOSS")
        position.status = "closed"
        position.tx_sell_final = tx

        loss_usd = position.amount_invested_usd * (pnl_pct / 100)
        await self.remove_position(position.token_mint)

        if self.notify:
            msg = (
                f"🔴 **STOP LOSS TRIGGERED**\n"
                f"Token: {position.token_symbol}\n"
                f"PnL: {pnl_pct:.1f}% (${loss_usd:.2f})\n"
                f"Sell price: ${current_price:.8f}\n"
                f"TX: https://solscan.io/tx/{tx}" if tx else
                f"🔴 **STOP LOSS** {position.token_symbol} {pnl_pct:.1f}% - TX FAILED!"
            )
            await self.notify(msg)

    async def _execute_tp1(self, position: Position, current_price: float, pnl_pct: float):
        """Eksekusi TP1 - jual 50%."""
        tx = await self.executor.sell_token(position, sell_pct=0.5, reason="TP1_2x")
        if tx:
            position.tp1_hit = True
            position.status = "tp1_hit"
            position.tp1_amount_sold = position.amount_token * 0.5
            position.amount_token = position.amount_token * 0.5  # sisa 50%
            position.tx_sell_tp1 = tx
            save_positions(self.positions)

            profit_usd = position.amount_invested_usd * (pnl_pct / 100) * 0.5
            if self.notify:
                msg = (
                    f"🟡 **TP1 HIT (2x)** 🎯\n"
                    f"Token: {position.token_symbol}\n"
                    f"Sold: 50% @ {pnl_pct:.1f}%\n"
                    f"Profit locked: +${profit_usd:.2f}\n"
                    f"Remaining: 50% riding to 3x\n"
                    f"New SL: -50% from buy price\n"
                    f"TX: https://solscan.io/tx/{tx}"
                )
                await self.notify(msg)
        else:
            logger.error(f"TP1 sell failed for {position.token_symbol}!")

    async def _execute_tp2_or_emergency(
        self,
        position: Position,
        current_price: float,
        pnl_pct: float,
        emergency: bool = False
    ):
        """Eksekusi TP2 atau emergency SL setelah TP1."""
        reason = "EMERGENCY_SL_POST_TP1" if emergency else "TP2_3x"
        tx = await self.executor.sell_token(position, sell_pct=1.0, reason=reason)
        position.status = "closed"
        position.tx_sell_final = tx
        await self.remove_position(position.token_mint)

        if self.notify:
            if emergency:
                msg = (
                    f"🔴 **EMERGENCY SL (Post-TP1)**\n"
                    f"Token: {position.token_symbol}\n"
                    f"Total PnL from buy: {pnl_pct:.1f}%\n"
                    f"Note: TP1 profit already locked ✅\n"
                    f"TX: https://solscan.io/tx/{tx}" if tx else f"Emergency SL TX FAILED! {position.token_symbol}"
                )
            else:
                profit_usd = position.amount_invested_usd * (pnl_pct / 100) * 0.5
                msg = (
                    f"🟢 **TP2 HIT (3x)** 🚀🎯\n"
                    f"Token: {position.token_symbol}\n"
                    f"Remaining 50% sold @ {pnl_pct:.1f}%\n"
                    f"Profit this tranche: +${profit_usd:.2f}\n"
                    f"TX: https://solscan.io/tx/{tx}" if tx else f"TP2 TX FAILED! {position.token_symbol}"
                )
            await self.notify(msg)

    async def _execute_time_exit(self, position: Position, current_price: float, pnl_pct: float):
        """Keluar karena waktu hold terlalu lama."""
        sell_pct = 1.0 if not position.tp1_hit else 1.0  # sell sisa
        tx = await self.executor.sell_token(position, sell_pct=sell_pct, reason="TIME_EXIT")
        position.status = "closed"
        position.tx_sell_final = tx
        await self.remove_position(position.token_mint)

        if self.notify:
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            msg = (
                f"{emoji} **TIME EXIT (24h)**\n"
                f"Token: {position.token_symbol}\n"
                f"Final PnL: {pnl_pct:+.1f}%\n"
                f"TX: https://solscan.io/tx/{tx}" if tx else f"Time exit TX FAILED! {position.token_symbol}"
            )
            await self.notify(msg)

    async def _execute_trailing_stop(
        self,
        position: Position,
        current_price: float,
        pnl_pct: float,
        trailing_drop_pct: float
    ):
        """Eksekusi trailing stop - jual semua sisa posisi."""
        tx = await self.executor.sell_token(position, sell_pct=1.0, reason="TRAILING_STOP")
        position.status = "closed"
        position.tx_sell_final = tx

        # Hapus dari highest price tracker
        self.highest_prices.pop(position.token_mint, None)
        await self.remove_position(position.token_mint)

        if self.notify:
            emoji = "🟢" if pnl_pct > 0 else "🔴"
            msg = (
                f"{emoji} **TRAILING STOP HIT**\n"
                f"Token: {position.token_symbol}\n"
                f"Drop from highest: {trailing_drop_pct:.1f}%\n"
                f"Final PnL: {pnl_pct:+.1f}%\n"
                f"Sell price: ${current_price:.8f}\n"
                f"TP1 was: {'✅ locked' if position.tp1_hit else '❌ not hit'}\n"
                f"TX: https://solscan.io/tx/{tx}"
            ) if tx else (
                f"🔴 TRAILING STOP TX FAILED! {position.token_symbol}"
            )
            await self.notify(msg)

    async def run(self):
        """Main monitor loop."""
        self.running = True
        logger.info("🔍 Position monitor started")

        while self.running:
            try:
                if self.positions:
                    positions_copy = list(self.positions.values())
                    for position in positions_copy:
                        if position.status in ("open", "tp1_hit"):
                            await self.check_position(position)
                        await asyncio.sleep(1)  # jeda antar token
                else:
                    logger.debug("No open positions, waiting...")

            except Exception as e:
                logger.error(f"Monitor loop error: {e}", exc_info=True)

            await asyncio.sleep(CHECK_INTERVAL_SEC)

    def stop(self):
        self.running = False
        logger.info("Position monitor stopped")
