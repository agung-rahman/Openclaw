# Openclaw

Openclaw is an autonomous Solana trading bot built for speed and discipline.
It scans the market, tracks smart wallets, filters tokens with AI, and executes
buy/sell automatically — without emotion, without hesitation.

---

## Why I Built This

Manual trading is exhausting and emotional. I wanted a system that could monitor
the market 24/7, copy the moves of proven wallets, and cut losses automatically
before they get out of hand. Openclaw is that system.

---

## What It Does

- Scans DexScreener continuously for volume spikes and momentum signals
- Tracks 80+ smart money wallets via Helius websocket in real time
- Filters every token candidate through an AI scoring layer before buying
- Executes buy and sell on Pump.fun and Pump-AMM with automatic pool detection
- Falls back to Jupiter if primary execution fails
- Monitors open positions and triggers stop-loss / take-profit automatically
- Sends all alerts and accepts commands via Telegram

---

## System Architecture
```
Token Scanner (degen_hunter.py)
         │
         ▼
Wallet Tracker (wallet_tracker.py) ──→ Signal Queue
         │
         ▼
AI Filter (ai_filter.py)
         │
         ├── SKIP → blacklist
         │
         └── BUY → pump_executor.py
                         │
                         ▼
              Position Monitor (position_monitor_v2.py)
                         │
                    SL / TP / Trailing Stop
                         │
                         ▼
                   Telegram Alerts
```

---

## Core Modules

| File | Role |
|------|------|
| `degen_hunter.py` | Token scanner — volume spike detection |
| `wallet_tracker.py` | 80+ wallet copy-trade monitor via Helius |
| `ai_filter.py` | AI scoring layer before execution |
| `pump_executor.py` | Buy/sell engine — Pump.fun + Jupiter fallback |
| `position_monitor_v2.py` | SL/TP/trailing stop monitor |
| `tg_commander.py` | Telegram command interface |
| `deep_research.py` | On-chain token research (holder, liquidity, rug) |
| `auto_trader.py` | Main orchestrator |

---

## Tech Stack

- **Python** — async/await throughout
- **Helius RPC** — Solana RPC + wallet transaction indexing
- **DexScreener API** — token data and pair info
- **Pump.fun / Pump-AMM** — primary trade execution
- **Jupiter** — fallback swap execution
- **RugCheck API** — token safety scoring
- **Birdeye** — holder analysis and trending data
- **Telegram Bot API** — alerts and remote commands
- **OpenRouter** — AI model integration (Mistral, Gemini, Claude)

---

## Setup

**Prerequisites**
- Python 3.10+
- A funded Solana wallet
- API keys: Helius, OpenRouter, Birdeye (optional), Telegram Bot Token

**Environment Variables**

Copy `.env.example` and fill in your values:
```bash
cp .env.example .env
```
```
TELEGRAM_BOT_TOKEN=
HELIUS_API_KEY=
HELIUS_API_KEY_EXECUTOR=
OPENROUTER_API_KEY=
BIRDEYE_API_KEY=
WALLET_ADDRESS=
```

**Run**
```bash
pip install -r requirements.txt
python auto_trader.py
```

---

## Telegram Commands

| Command | Action |
|---------|--------|
| `/positions` | Show all open positions |
| `/balance` | Check SOL wallet balance |
| `/sell <symbol>` | Manually sell a token |
| `/sell all` | Close all positions |
| `/pause` | Pause auto-trading |
| `/resume` | Resume auto-trading |
| `!analyze <mint>` | Deep research a token |

---

## Risk Warning

This bot trades real funds automatically. Use at your own risk.
Always start with a small amount you can afford to lose.

---

Built by [Agung Rahman](https://github.com/agung-rahman)
