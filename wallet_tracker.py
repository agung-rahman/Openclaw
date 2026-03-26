"""
wallet_tracker.py - Track 80 copytrade wallets, analisa token ke queue
Anti-duplikat: token yang sama ga dianalisa 2x dalam 1 jam
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("wallet_tracker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

HELIUS_KEY = os.getenv("HELIUS_API_KEY", "")
BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY", "")
RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}"

ANALYZED_FILE = Path("/root/.wallet_analyzed.json")
LAST_TX_FILE = Path("/root/.wallet_last_tx.json")

WALLETS = [
  {"address": "HdxkiXqeN6qpK2YbG51W23QSWj3Yygc1eEk2zwmKJExp", "name": "whale 2"},
  {"address": "9VKYME2xdBfK9GVpR4zDjCrAFbDKVgrbJTh1Kjthch3", "name": "whale"},
  {"address": "FpYRwY67eXeLmfUiGBosYLe6Ns3y8s3KKRiKQkz3e6iX", "name": "top trade"},
  {"address": "66eMMe1Ga3FyJqmv1rmcPcHEgg8bYs74MvABtwVxtZJH", "name": "whale bisnis"},
  {"address": "qNGhUruCGJpXJdsnV74USHErcbm3CrXRsnP8D6Z34Hh", "name": "100xdan"},
  {"address": "PDxV89p3PyUwnfH4gsbhDp72zjx4QBwrgzhkkKnbtU3", "name": "samet"},
  {"address": "4vw54BmAogeRV3vPKWyFet5yf8DTLcREzdSzx4rw9Ud9", "name": "decu"},
  {"address": "Hw5UKBU5k3YudnGwaykj5E8cYUidNMPuEewRRar5Xoc7", "name": "trenchman"},
  {"address": "7VBTpiiEjkwRbRGHJFUz6o5fWuhPFtAmy8JGhNqwHNnn", "name": "brox"},
  {"address": "DshPqYhX7JJhWaSUY5R4mWw5JRZU6Lb2qZczFdTLGztM", "name": "sniperCope"},
  {"address": "4e5rXS3gxcGade812ePdAVDq67NwR65aZ97bDbzdX3g8", "name": "sniper2"},
  {"address": "mW4PZB45isHmnjGkLpJvjKBzVS5NXzTJ8UDyug4gTsM", "name": "dex2"},
  {"address": "DTwgYLW69g3yKE7EtCm2wFQHwUNJCsoRNVJ3xUp252Va", "name": "sniper6"},
  {"address": "5B52w1ZW9tuwUduueP5J7HXz5AcGfruGoX6YoAudvyxG", "name": "yenni"},
  {"address": "4xxBGBnXqfCyUpsKRix1VaWm15uND2P83ForEzYDngbD", "name": "whale 5"},
  {"address": "9KEShFaBjyBjLVWSXGE6mvWwQbJkkxw1vF2K2R1abKvy", "name": "sniper 2"},
  {"address": "AeLaMjzxErZt4drbWVWvcxpVyo8p94xu5vrg41eZPFe3", "name": "1simple"},
  {"address": "suqh5sHtr8HyJ7q8scBimULPkPpA557prMG47xCHQfK", "name": "cupseyy"},
  {"address": "CvNiezB8hofusHCKqu8irJ6t2FKY7VjzpSckofMzk5mB", "name": "dali"},
  {"address": "86AEJExyjeNNgcp7GrAvCXTDicf5aGWgoERbXFiG1EdD", "name": "publix"},
  {"address": "Be24Gbf5KisDk1LcWWZsBn8dvB816By7YzYF5zWZnRR6", "name": "chairman"},
  {"address": "EszKEbQLk1zWij8SKTdC36SAVXsapyrG9PpWWcqYsSbr", "name": "sniper fish"},
  {"address": "fNrJmJ1aQMx1vgnGwJcLWkUCBrDy7GF7ZpVqiXuRFrJ", "name": "insider"},
  {"address": "Bz429AezLuxgftrYKGCaTJsjZBN6LibmYp9eVfL9MXZ9", "name": "bz42_gmgn"},
  {"address": "922VvmmYDHV9KMTJJ71Y5Yd3Vn7cfJuFasLNSsZPygrG", "name": "zuki"},
  {"address": "JDd3hy3gQn2V982mi1zqhNqUw1GfV2UL6g76STojCJPN", "name": "west"},
  {"address": "2fg5QD1eD7rzNNCsvnhmXFm5hqNgwTTG8p7kQ6f3rx6f", "name": "cupsey"},
  {"address": "HQJ4iFLpm1Uyj92barvzUBYWZ8agjZBqn4gmKVgv6Ufy", "name": "topblast"},
  {"address": "DZAa55HwXgv5hStwaTEJGXZz1DhHejvpb7Yr762urXam", "name": "ozark"},
  {"address": "71PCu3E4JP5RDBoY6wJteqzxkKNXLyE1byg5BTAL9UtQ", "name": "ramset"},
  {"address": "98T65wcMEjoNLDTJszBHGZEX75QRe8QaANXokv4yw3Mp", "name": "leck"},
  {"address": "J1XAE4onKYG1kTghgaytnyFgR3otQs1xEnJRRWM3djSQ", "name": "yode"},
  {"address": "BPHyg5hR3GFfnYBNpVry49TpwwyXSw4ggBXJp2bwUFvt", "name": "sniper tiktok"},
  {"address": "2kv8X2a9bxnBM8NKLc6BBTX2z13GFNRL4oRotMUJRva9", "name": "ghostee"},
  {"address": "Di75xbVUg3u1qcmZci3NcZ8rjFMj7tsnYEoFdEMjS4ow", "name": "no"},
  {"address": "FAicXNV5FVqtfbpn4Zccs71XcfGeyxBSGbqLDyDJZjke", "name": "radience"},
  {"address": "GM7Hrz2bDq33ezMtL6KGidSWZXMWgZ6qBuugkb5H8NvN", "name": "beaver"},
  {"address": "ACTbvbNm5qTLuofNRPxFPMtHAAtdH1CtzhCZatYHy831", "name": "jason"},
  {"address": "GeCyh1n9KjhEPPsQSDFsnsRSLxkCho6w9f14UjnS1n61", "name": "sniper h"},
  {"address": "3h65MmPZksoKKyEpEjnWU2Yk2iYT5oZDNitGy5cTaxoE", "name": "jidin"},
  {"address": "3BLjRcxWGtR7WRshJ3hL25U3RjWr5Ud98wMcczQqk4Ei", "name": "sebastian"},
  {"address": "EHg5YkU2SZBTvuT87rUsvxArGp3HLeye1fXaSDfuMyaf", "name": "til"},
  {"address": "5B79fMkcFeRTiwm7ehsZsFiKsC7m7n1Bgv9yLxPp9q2X", "name": "bandit gblk"},
  {"address": "AQ46kfYT3hW28Xg5gWHrJkzFSz1oGWBHC3FsTbqgMEco", "name": "eco snip"},
  {"address": "2LzZjYDTJjvSxySdvEqYk3fdaWuFnVpXacuZjcct59MZ", "name": "whale 4"},
  {"address": "8u4vSynSiF1JDK63gaubouaAfG4hufuGkPwwygUicS4z", "name": "whale chad"},
  {"address": "9oHYHRyxmyWN3xct4jHJn6k1ugAzve6csL8AiH9p1G8R", "name": "0xdeployer"},
  {"address": "PA6vr5VhdwbueWTckLEfGgBVGimDK9F4fqyqQk3tKCQ", "name": "sniper c"},
  {"address": "6UcanEPgy9t6aJxpvaU62CmmXpnAp5ny5e8XeoFr1q9b", "name": "whale pump"},
  {"address": "F1DfCGA3Hfx2CDn98o7zYHTJMfVjqbn5sARyUpQ3fz4Q", "name": "whale ani 2"},
  {"address": "CY8iVeeWssr4nVPGeASKoSqpx7ii2hQBgdTW89sN4MD6", "name": "bundler"},
  {"address": "As7HjL7dzzvbRbaD3WCun47robib2kmAKRXMvjHkSMB5", "name": "otta"},
  {"address": "DNfuF1L62WWyW3pNakVkyGGFzVVhj4Yr52jSmdTyeBHm", "name": "gake"},
  {"address": "beatXW1PmeVVXxebbyLuc3uKy2Vj8mt6vedBhP9AYXo", "name": "sniper"},
  {"address": "9LjZSrnSN7a6VTT3LeCM5hZ95yt2KfU2YyN5VLnDznTr", "name": "sniper fish 3"},
  {"address": "9tY7u1HgEt2RDcxym3RJ9sfvT3aZStiiUwXd44X9RUr8", "name": "solanadegen"},
  {"address": "G8CwQWHPQDr5xY5oDeU3Lnuon87DdmLSTxAZR6ZdbBDT", "name": "sniper 69"},
  {"address": "4sAUSQFdvWRBxR8UoLBYbw8CcXuwXWxnN8pXa4mtm5nU", "name": "scharo"},
  {"address": "G6fUXjMKPJzCY1rveAE6Qm7wy5U3vZgKDJmN1VPAdiZC", "name": "clukz"},
  {"address": "8oMPPE6JJXN1bLu3NyHZPKZUQMH6gWnrWqJpHNCirN5e", "name": "Sniper bir"},
  {"address": "BuhkHhM3j4viF71pMTd23ywxPhF35LUnc2QCLAvUxCdW", "name": "saif"},
  {"address": "G2ejjxMcTMThn8NuWUjD4TUggrKgcdeAYUqNa9qm8X1V", "name": "madge whale"},
  {"address": "6K2CJbTsSDtNBtNRtetkayNAdd7oFTDZiJrcb2nkWnmZ", "name": "whale 3"},
  {"address": "FjSysoa9ohYkMdjdJnHUpi8ZGD8QJCxMTCWr46biuqhg", "name": "whale ani"},
  {"address": "BTf4A2exGK9BCVDNzy65b9dUzXgMqB4weVkvTMFQsadd", "name": "kev"},
  {"address": "CAPn1yH4oSywsxGU456jfgTrSSUidf9jgeAnHceNUJdw", "name": "cap"},
  {"address": "GhXtCwfznbLYpLKhtuDqbN7ByTin3GiJCFmvVP3G7HQb", "name": "sniper terminal"},
  {"address": "95nrZPWVi7iSH6HA3us6UzpvaPUBuGo5T1NDDG49Shun", "name": "whale 6"},
  {"address": "2pUUZYtokRgDV2YzL6M5pjb1jyoHE367yU1sdQ7ac3ea", "name": "log"},
  {"address": "9y3qT1y4Y9yACtt8Jkv2kFVov6FTDygaCnkh1SYGusEd", "name": "sniper 3"},
  {"address": "3UNPM7X6LbmxUms5ij6zm9P7J1Ev2Wd7TwwXmYrPX3n3", "name": "tendra"},
  {"address": "BAr5csYtpWoNpwhUjixX7ZPHXkUciFZzjBp9uNxZXJPh", "name": "jack"},
  {"address": "H7XESvNa8NkL6ciZQiuGoDsWNeShwPKPW7TtyNrRNk78", "name": "sniper fish 2"},

  {"address": "xXpRSpAe1ajq4tJP78tS3X1AqNwJVQ4Vvb1Swg4hHQh", "name": "aloh"},
  {"address": "GvmgmxkE7ed9b74YigRuNeAS6rSnpCAUbjtK4Wc8ed4S", "name": "sniper ss"},
  {"address": "9cfVFMuEwaTLqoyLrfGxDU85zVmHG6NMonFk9WgroFjq", "name": "serenity"},
  {"address": "DVMkhiQe1D8yenuEgsW44NjRn9LfVQjGEpZcez5x7Mff", "name": "iceman"},
  {"address": "B9K2wTQcRDLRLhMKFyRh2hPqHrr6VKiCC9yNGpkMUXrh", "name": "xanse"},
  {"address": "7cQjAvzJsmdePPMk8TiW8hYHHhCfdNtEaaNK3o46YP12", "name": "parsix"},
  {"address": "6G76Pub42rwDdPGxw59Hq3574vaBjcZmA9FJ9j9dexYh", "name": "bonemal"},
  {"address": "3NtxeVw1TUKM5i6o7SMx8pnbnwq7q6qoXN5WHAfnHmWJ", "name": "ponyin"},
  {"address": "A8Z1ejQGk45EJibBPJviWnM3UvwKSuYun53nSCkWKM52", "name": "lspfi"},
]


def load_analyzed() -> dict:
    """Load token yang udah dianalisa + timestamp-nya."""
    if ANALYZED_FILE.exists():
        return json.loads(ANALYZED_FILE.read_text())
    return {}


def save_analyzed(data: dict):
    ANALYZED_FILE.write_text(json.dumps(data, indent=2))


def is_already_analyzed(token_mint: str) -> bool:
    """Cek apakah token ini udah dianalisa dalam 1 jam terakhir."""
    analyzed = load_analyzed()
    if token_mint not in analyzed:
        return False
    ts = datetime.fromisoformat(analyzed[token_mint]["timestamp"])
    return (datetime.now() - ts) < timedelta(hours=1)


def mark_analyzed(token_mint: str, token_symbol: str, wallet_name: str):
    analyzed = load_analyzed()
    analyzed[token_mint] = {
        "symbol": token_symbol,
        "wallet": wallet_name,
        "timestamp": datetime.now().isoformat()
    }
    # Cleanup yang udah > 2 jam
    cutoff = datetime.now() - timedelta(hours=2)
    analyzed = {k: v for k, v in analyzed.items()
                if datetime.fromisoformat(v["timestamp"]) > cutoff}
    save_analyzed(analyzed)


def load_last_tx() -> dict:
    if LAST_TX_FILE.exists():
        return json.loads(LAST_TX_FILE.read_text())
    return {}


def save_last_tx(data: dict):
    LAST_TX_FILE.write_text(json.dumps(data, indent=2))


async def get_recent_transactions(wallet: str, session: aiohttp.ClientSession) -> list:
    """Ambil transaksi terbaru dari wallet via Helius."""
    try:
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {
            "api-key": HELIUS_KEY,
            "limit": 20,
            "type": "SWAP"
        }
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=8)) as r:
            if r.status != 200:
                return []
            return await r.json()
    except:
        return []


async def extract_bought_tokens(txs: list, wallet_address: str = "") -> list:
    # wallet_address kept for compatibility but not used for filtering
    """Extract token yang dibeli dari transaksi swap via tokenTransfers."""
    SKIP_MINTS = {
        "So11111111111111111111111111111111111111112",   # SOL
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    }
    bought = []
    seen = set()
    for tx in txs:
        try:
            if tx.get("type") != "SWAP":
                continue
            transfers = tx.get("tokenTransfers", [])
            for t in transfers:
                mint = t.get("mint", "")
                amount = t.get("tokenAmount", 0)
                to_user = t.get("toUserAccount", "")
                # Token masuk ke wallet kita = yang dibeli
                if mint in SKIP_MINTS or not mint:
                    continue
                if amount <= 0:
                    continue
                # Skip filter by address - Helius udah filter by wallet
                if mint not in seen:
                    seen.add(mint)
                    bought.append({
                        "mint": mint,
                        "amount": amount,
                        "tx_sig": tx.get("signature", "")
                    })
        except:
            continue
    return bought


async def get_sol_price_cached(session: aiohttp.ClientSession) -> float:
    cache_file = Path("/root/.sol_price_cache.json")
    try:
        if cache_file.exists():
            cache = json.loads(cache_file.read_text())
            if (datetime.now().timestamp() - cache["ts"]) < 300:
                return cache["price"]
    except:
        pass
    try:
        async with session.get(
            "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            price = float(data.get("pair", {}).get("priceUsd", 87) or 87)
            cache_file.write_text(json.dumps({"price": price, "ts": datetime.now().timestamp()}))
            return price
    except:
        return 87.0


async def get_pumpfun_data(mint: str, session: aiohttp.ClientSession) -> dict:
    try:
        async with session.get(
            f"https://frontend-api.pump.fun/coins/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            if r.status != 200:
                return {}
            d = await r.json()
            sol_price = await get_sol_price_cached(session)
            virtual_sol = d.get("virtual_sol_reserves", 0) / 1e9
            virtual_tokens = d.get("virtual_token_reserves", 0) / 1e6
            price_per_token = virtual_sol / virtual_tokens if virtual_tokens > 0 else 0
            total_supply = d.get("total_supply", 0) / 1e6
            mcap_usd = price_per_token * total_supply * sol_price
            bonding_progress = d.get("bonding_curve_percentage", 0) or (
                (d.get("real_sol_reserves", 0) / 85_000_000_000) * 100
                if d.get("real_sol_reserves") else 0
            )
            return {
                "symbol": d.get("symbol", "UNKNOWN"),
                "name": d.get("name", ""),
                "mcap": mcap_usd,
                "liquidity": virtual_sol * sol_price,
                "volume_24h": 0,
                "price_change_1h": 0,
                "price_change_24h": 0,
                "bonding_progress": bonding_progress,
                "is_pumpfun": True,
                "price_usd": price_per_token * sol_price,
            }
    except Exception as e:
        print(f"[WALLET] Pump.fun API error: {e}")
        return {}


async def get_token_info(mint: str, session: aiohttp.ClientSession) -> dict:
    """Ambil info token — Birdeye > DexScreener > pump.fun."""
    # 1. Coba Birdeye
    try:
        async with session.get(
            f"https://public-api.birdeye.so/defi/token_overview?address={mint}",
            headers={"X-API-KEY": BIRDEYE_KEY, "X-Chain": "solana"},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            d = data.get("data", {})
            if d.get("symbol") and d.get("symbol") != "UNKNOWN" and d.get("realMc", 0) > 0 and d.get("liquidity", 0) > 0:
                return {
                    "symbol": d.get("symbol", "UNKNOWN"),
                    "name": d.get("name", ""),
                    "price_usd": d.get("price", 0),
                    "mcap": d.get("realMc", 0),
                    "liquidity": d.get("liquidity", 0),
                    "volume_24h": d.get("v24hUSD", 0),
                    "price_change_1h": d.get("priceChange1hPercent", 0),
                    "price_change_24h": d.get("priceChange24hPercent", 0),
                }
    except:
        pass

    # 2. Fallback DexScreener
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            pairs = data.get("pairs", [])
            if pairs:
                p = sorted(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
                base = p.get("baseToken", {})
                info = {
                    "symbol": base.get("symbol", "UNKNOWN"),
                    "name": base.get("name", ""),
                    "price_usd": float(p.get("priceUsd", 0) or 0),
                    "mcap": float(p.get("marketCap", 0) or p.get("fdv", 0) or 0),
                    "liquidity": float(p.get("liquidity", {}).get("usd", 0) or 0),
                    "volume_24h": float(p.get("volume", {}).get("h24", 0) or 0),
                    "price_change_1h": float(p.get("priceChange", {}).get("h1", 0) or 0),
                    "price_change_24h": float(p.get("priceChange", {}).get("h24", 0) or 0),
                }
                if info["mcap"] > 0 or info["liquidity"] > 0:
                    return info
    except:
        pass

    # 3. Fallback pump.fun
    pump_data = await get_pumpfun_data(mint, session)
    if pump_data:
        return pump_data

    return {}


async def check_rugcheck(mint: str, session: aiohttp.ClientSession) -> dict:
    """Quick rugcheck."""
    try:
        async with session.get(
            f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            return {
                "score": data.get("score", 0),
                "risks": [r.get("name", "") for r in data.get("risks", [])[:3]]
            }
    except:
        return {"score": 0, "risks": []}


async def analyze_and_queue(mint: str, wallet_name: str, session: aiohttp.ClientSession):
    """Analisa token dan masukin ke queue."""
    from signal_queue import add_signal

    token_info = await get_token_info(mint, session)
    if not token_info:
        return

    # Filter token age — skip kalau token > 14 hari
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            dex = await r.json()
            pairs = dex.get("pairs", [])
            if pairs:
                created_at = pairs[0].get("pairCreatedAt", 0)
                if created_at:
                    age_days = (datetime.now().timestamp() - created_at/1000) / 86400
                    if age_days > 14:
                        print(f"[WALLET] Skip {token_info.get('symbol','?')} — token age {age_days:.1f} hari > 14 hari", flush=True)
                        return
    except:
        pass

    symbol = token_info.get("symbol", "UNKNOWN")
    rug = await check_rugcheck(mint, session)

    # Skip kalau rugcheck jelek banget
    rug_score = rug.get("score", 0)

    mcap = token_info.get("mcap", 0)
    liquidity = token_info.get("liquidity", 0)
    
    # Format signal
    # Hitung age dari DexScreener (udah di-fetch di filter atas)
    _age_str = ""
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=5)
        ) as _r:
            _dex = await _r.json()
            _pairs = _dex.get("pairs", [])
            if _pairs:
                _created_at = _pairs[0].get("pairCreatedAt", 0)
                if _created_at:
                    _age_days = (datetime.now().timestamp() - _created_at/1000) / 86400
                    _age_str = f"{_age_days:.1f}d" if _age_days >= 1 else f"{_age_days*24:.0f}h"
    except:
        pass

    # Ambil top holder dari rugcheck full report
    top1_pct = 0
    try:
        import httpx as _hx
        async with _hx.AsyncClient() as _hc:
            _resp = await _hc.get(
                f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",
                timeout=8
            )
            _rdata = _resp.json()
            _holders = _rdata.get("topHolders", [])
            if _holders:
                top1_pct = _holders[0].get("pct", 0) * 100
    except:
        pass

    signal_text = (
        f"👛 WALLET SIGNAL — {wallet_name}\n\n"
        f"🪙 {symbol} ({token_info.get('name', '')})\n"
        f"📊 MCap: ${mcap:,.0f}\n"
        f"💧 Liquidity: ${liquidity:,.0f}\n"
        f"💰 Vol 24h: ${token_info.get('volume_24h', 0):,.0f}\n"
        f"📈 Price 1h: {token_info.get('price_change_1h', 0):+.1f}%\n"
        f"📈 Price 24h: {token_info.get('price_change_24h', 0):+.1f}%\n"
        + (f"⏰ Age: {_age_str}\n" if _age_str else "")
        + (f"👤 Top 1: {top1_pct:.1f}%\n" if top1_pct > 0 else "")
        + f"\n🛡️ Rugcheck: {rug_score}/1000\n"
        f"⚠️ Risks: {', '.join(rug.get('risks', [])) or 'None'}\n\n"
        f"🔗 https://dexscreener.com/solana/{mint}"
    )

    # Auto-research sebelum masuk queue
    research_summary = ""
    try:
        import subprocess, sys
        proc = subprocess.run(
            ['python3', '-u', '/root/deep_research.py', mint, symbol],
            capture_output=True, text=True, timeout=45,
            env={**__import__('os').environ}
        )
        if proc.stdout.strip():
            research_summary = proc.stdout.strip()
            print(f"[WALLET] ✅ Auto-research done for {symbol}")
    except Exception as e:
        print(f"[WALLET] Auto-research failed for {symbol}: {e}")

    # Gabungin signal + research
    if research_summary:
        full_signal = signal_text + "\n\n━━━━━━━━━━━━━━━━━━━━\n\n" + research_summary
    else:
        full_signal = signal_text

    add_signal({"text": full_signal, "type": "wallet", "wallet": wallet_name,
                "token": symbol, "mint": mint})
    mark_analyzed(mint, symbol, wallet_name)
    print(f"[WALLET] ✅ Queued wallet signal: {symbol} from {wallet_name}")


async def check_wallet(wallet: dict, last_txs: dict, session: aiohttp.ClientSession):
    """Cek satu wallet untuk transaksi baru."""
    address = wallet["address"]
    name = wallet["name"]

    txs = await get_recent_transactions(address, session)
    if not txs:
        return

    import time as _t

    # Track per signature — semua TX yang belum diproses
    processed_sigs = last_txs.get(address, [])
    if isinstance(processed_sigs, str):
        processed_sigs = [processed_sigs]

    new_txs = [tx for tx in txs if tx.get("signature", "") not in processed_sigs]
    if not new_txs:
        return

    print(f"[WALLET] {name}: {len(new_txs)} new tx ditemukan", flush=True)

    # Update processed sigs, simpan max 50
    last_txs[address] = (processed_sigs + [tx.get("signature", "") for tx in new_txs])[-50:]

    bought = await extract_bought_tokens(new_txs, address)
    for token in bought:
        mint = token["mint"]
        if is_already_analyzed(mint):
            continue
        print(f"[WALLET] New buy from {name}: {mint[:8]}...", flush=True)
        try:
            await analyze_and_queue(mint, name, session)
        except Exception as _e:
            import traceback
            print(f"[WALLET] Error analyze {mint[:8]}: {_e}", flush=True)
            traceback.print_exc()

async def wallet_tracker_loop():
    """Main loop — cek semua wallet tiap 1 menit."""
    print(f"[WALLET] 👛 Wallet tracker started — monitoring {len(WALLETS)} wallets", flush=True)
    
    import time as _t
    last_txs = {}  # Mulai kosong — scan fresh dari awal
    last_clear_time = _t.time()

    while True:
        try:
            # Clear cache setiap 30 menit di AWAL cycle (bukan akhir)
            if (_t.time() - last_clear_time) > 1800:
                last_txs.clear()
                last_clear_time = _t.time()
                print("[WALLET] Cache cleared — fresh scan", flush=True)

            async with aiohttp.ClientSession() as session:
                for i in range(0, len(WALLETS), 10):
                    batch = WALLETS[i:i+10]
                    tasks = [check_wallet(w, last_txs, session) for w in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, Exception):
                            print(f"[WALLET] check_wallet error: {r}", flush=True)
                    await asyncio.sleep(1)

            save_last_tx(last_txs)
            print(f"[WALLET] Scan done — {len(last_txs)} wallets tracked", flush=True)

        except Exception as e:
            import traceback
            print(f"[WALLET] Loop error: {e}", flush=True)
            traceback.print_exc()

        await asyncio.sleep(60)

