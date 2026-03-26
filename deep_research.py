"""
deep_research.py - Deep research token sebelum trading
Sources: Birdeye (holder), Helius (on-chain), DexScreener, pump.fun,RugCheck
"""

import asyncio
import aiohttp
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BIRDEYE_KEY = os.getenv("BIRDEYE_API_KEY", "")
HELIUS_KEY = os.getenv("HELIUS_API_KEY", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")


# Known LP/program accounts to exclude
LP_PROGRAM_ACCOUNTS = {
    "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM",   # pump.fun bonding curve
    "CebN5WGQ4jvEPvsVU4EoHEpgznyQHearzZAXEJ97RU8U",  # pump.fun fee
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",  # raydium LP
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # raydium authority
    "4wTV81sMk6pFnN4p2V2PQbKLPYCsSmcEWXKDGBMhzs2L",  # orca
    "DCcu1rzJyouGNQf1gU2uta5Na3EEBUJkkgaZkb2P3jUk",  # pumpswap LP pool
    "GtDZKAqvMGMle2RD9K8kCd7EsfE5z4iu2TnWznVYjuXr",  # pumpswap LP pool 2
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBymSXx8",  # pump.fun program
    "AZFkNPuBFdFhvANBQFzFjftoRHnFbyfMSzTHZaqLKvau",  # pump.fun bonding curve 2
    "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1",  # pump.fun bonding curve 3
    "7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqtj2G5",  # pump.fun migration
}

DEX_PROGRAMS = {
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",   # PumpSwap AMM
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBymSXx8",  # Pump.fun program
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",   # Pump.fun program v2
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM v4
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium authority
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",   # Orca whirlpool
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # Raydium CLMM
    "LBUZKhRxPF3XUpBCjp4YzTKgLe4eLDTemrar3kVRkHS",   # Meteora DLMM
}

async def resolve_token_account_owner(token_account: str, session: aiohttp.ClientSession) -> tuple:
    """
    Resolve token account → wallet owner → cek apakah LP/DEX.
    Return (owner_address, is_lp)
    """
    try:
        # Level 1: token account → wallet address
        async with session.post(
            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
            json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                  "params": [token_account, {"encoding": "jsonParsed"}]},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            val = data.get("result", {}).get("value", {})
            parsed = val.get("data", {}).get("parsed", {})
            wallet = parsed.get("info", {}).get("owner", "")

        if not wallet:
            return ("", False)

        # Cek hardcode LP accounts dulu (cepat, no RPC)
        if wallet in LP_PROGRAM_ACCOUNTS:
            return (wallet, True)

        # Level 2: cek apakah wallet ini dimiliki DEX program
        async with session.post(
            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
            json={"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                  "params": [wallet, {"encoding": "base64"}]},
            timeout=aiohttp.ClientTimeout(total=5)
        ) as r:
            data = await r.json()
            val = data.get("result", {}).get("value", {})
            wallet_owner = val.get("owner", "")
            # is_lp kalau owned by DEX program ATAU owned by pump.fun program
            is_lp = wallet_owner in DEX_PROGRAMS

        return (wallet, is_lp)
    except:
        return ("", False)


async def get_holder_analysis(mint: str, session: aiohttp.ClientSession) -> dict:
    """Analisa distribusi holder via Helius — 2-level LP detection."""
    try:
        async with session.post(
            f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
            json={"jsonrpc": "2.0", "id": 1,
                  "method": "getTokenLargestAccounts", "params": [mint]},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            accounts = data.get("result", {}).get("value", [])
            if not accounts:
                return {}

        # Resolve owners sequential biar ga timeout
        real_holders = []
        for acc in accounts[:10]:
            try:
                res = await resolve_token_account_owner(acc["address"], session)
                if not isinstance(res, tuple):
                    continue
                owner, is_lp = res
                if is_lp or not owner:
                    continue
                real_holders.append({
                    "owner": owner,
                    "ui_amount": float(acc.get("uiAmount", 0) or 0),
                })
            except Exception as e:
                logger.debug(f"Skip account: {e}")
                continue

        if not real_holders:
            return {}

        # Get total supply dari mint
        total_supply = 0
        try:
            async with session.post(
                f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}",
                json={"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                d = await r.json()
                total_supply = float(d.get("result", {}).get("value", {}).get("uiAmount", 0) or 0)
        except:
            pass
        if total_supply == 0:
            total_supply = sum(h["ui_amount"] for h in real_holders)
        if total_supply == 0:
            return {}

        top1 = real_holders[0]["ui_amount"] / total_supply * 100
        top5 = sum(h["ui_amount"] for h in real_holders[:5]) / total_supply * 100
        top10 = sum(h["ui_amount"] for h in real_holders[:10]) / total_supply * 100


        return {
            "total_holders_sample": len(real_holders),
            "top1_pct": round(top1, 1),
            "top5_pct": round(top5, 1),
            "top10_pct": round(top10, 1),
            "real_holders": len(real_holders),
            "whale_risk": "HIGH" if top1 > 20 else "MEDIUM" if top1 > 10 else "LOW",
            "top_holders": [
                {"owner": h["owner"][:8]+"...", "pct": round(h["ui_amount"]/total_supply*100, 1)}
                for h in real_holders[:5]
            ]
        }
    except Exception as e:
        logger.error(f"Holder analysis error: {e}")
        return {}


async def get_onchain_metrics(mint: str, session: aiohttp.ClientSession) -> dict:
    """On-chain metrics dari DexScreener — gratis, no key needed. Fallback pump.fun kalau belum bonding."""
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            pairs = data.get("pairs", [])
            # Kalau ada pairs tapi liquidity None/0 — estimasi dari mcap (prebond token)
            if pairs:
                p = sorted(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd", 0) or 0), reverse=True)[0]
                liq = float((p.get("liquidity") or {}).get("usd", 0) or 0)
                if liq == 0:
                    # Prebond: liquidity = virtual SOL di bonding curve
                    # Estimasi: mcap * 0.1 sebagai lower bound, atau baca dari pair
                    mcap_est = float(p.get("marketCap", 0) or p.get("fdv", 0) or 0)
                    if mcap_est > 0:
                        # Pump.fun bonding curve: liquidity ~= mcap * bonding_progress%
                        # Tapi kita ga tau progress — pakai fixed formula pump.fun
                        # Initial virtual_sol = 30 SOL, target = 85 SOL
                        # Estimasi SOL di curve = 30 + (mcap/100000 * 55) SOL
                        sol_price = 87.0
                        try:
                            async with session.get(
                                "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                                timeout=aiohttp.ClientTimeout(total=3)
                            ) as sr2:
                                sd2 = await sr2.json()
                                sol_price = float(sd2.get("pair",{}).get("priceUsd", 87) or 87)
                        except: pass
                        est_sol = 30 + (mcap_est / 100000 * 55)
                        liq = min(est_sol, 85) * sol_price
                        logger.debug(f"Estimated liquidity from mcap: ${liq:.0f} (mcap=${mcap_est:.0f})")
            if not pairs:
                # Fallback pump.fun untuk token yang belum bonding
                try:
                    async with session.get(
                        f"https://frontend-api.pump.fun/coins/{mint}",
                        timeout=aiohttp.ClientTimeout(total=8)
                    ) as pr:
                        if pr.status == 200:
                            pd = await pr.json()
                            sol_price = 87.0
                            try:
                                async with session.get(
                                    "https://api.dexscreener.com/latest/dex/pairs/solana/83v8iPyZihDEjDdY8RdZddyZNyUtXngz69Lgo9Kt5d6Q",
                                    timeout=aiohttp.ClientTimeout(total=4)
                                ) as sr:
                                    sd = await sr.json()
                                    sol_price = float(sd.get("pair",{}).get("priceUsd", 87) or 87)
                            except: pass
                            virt_sol = pd.get("virtual_sol_reserves", 0) / 1e9
                            virt_tokens = pd.get("virtual_token_reserves", 0) / 1e6
                            total_supply = pd.get("total_supply", 0) / 1e6
                            price_per_token = (virt_sol / virt_tokens) if virt_tokens > 0 else 0
                            mcap = price_per_token * total_supply * sol_price
                            liq = virt_sol * sol_price
                            bonding_pct = pd.get("bonding_curve_percentage", 0) or (
                                (pd.get("real_sol_reserves", 0) / 85_000_000_000) * 100
                                if pd.get("real_sol_reserves") else 0
                            )
                            return {
                                "volume_1h": 0, "volume_6h": 0, "volume_24h": 0,
                                "volume_trend": "N/A (pump.fun belum bonding)",
                                "price_change_1h": 0, "price_change_6h": 0, "price_change_24h": 0,
                                "buys_24h": 0, "sells_24h": 0, "buys_1h": 0, "sells_1h": 0,
                                "buy_ratio_24h": 0,
                                "liquidity": round(liq, 2),
                                "mcap": round(mcap, 2),
                                "unique_wallets_24h": 0,
                                "is_pumpfun_prebond": True,
                                "bonding_progress": round(bonding_pct, 1),
                            }
                except Exception as pfe:
                    logger.debug(f"pump.fun fallback error: {pfe}")
                return {}
            p = sorted(pairs, key=lambda x: float((x.get("liquidity") or {}).get("usd", 0) or 0), reverse=True)[0]
            v1h = float((p.get("volume") or {}).get("h1", 0) or 0)
            v6h = float((p.get("volume") or {}).get("h6", 0) or 0)
            v24h = float((p.get("volume") or {}).get("h24", 0) or 0)
            vol_trend = "INCREASING" if v1h > (v6h/6 if v6h > 0 else 0) else "DECREASING"
            buys_24h = int((p.get("txns") or {}).get("h24", {}).get("buys", 0) or 0)
            sells_24h = int((p.get("txns") or {}).get("h24", {}).get("sells", 0) or 0)
            buys_1h = int((p.get("txns") or {}).get("h1", {}).get("buys", 0) or 0)
            sells_1h = int((p.get("txns") or {}).get("h1", {}).get("sells", 0) or 0)
            total_txns = buys_24h + sells_24h
            buy_ratio = (buys_24h / total_txns * 100) if total_txns > 0 else 0
            # Pakai liq yang sudah diestimasi kalau DexScreener return None/0
            _raw_liq = float((p.get("liquidity") or {}).get("usd", 0) or 0)
            if _raw_liq > 0:
                liq = _raw_liq
            # else: liq sudah di-set dari estimasi bonding curve di atas
            mcap = float(p.get("marketCap", 0) or 0)
            return {
                "volume_1h": v1h,
                "volume_6h": v6h,
                "volume_24h": v24h,
                "volume_trend": vol_trend,
                "price_change_1h": float((p.get("priceChange") or {}).get("h1", 0) or 0),
                "price_change_6h": float((p.get("priceChange") or {}).get("h6", 0) or 0),
                "price_change_24h": float((p.get("priceChange") or {}).get("h24", 0) or 0),
                "buys_24h": buys_24h,
                "sells_24h": sells_24h,
                "buys_1h": buys_1h,
                "sells_1h": sells_1h,
                "buy_ratio_24h": round(buy_ratio, 1),
                "liquidity": liq,
                "mcap": mcap,
                "unique_wallets_24h": 0,
            }
    except Exception as e:
        logger.error(f"On-chain metrics error: {e}")
        return {}


async def get_dexscreener_data(mint: str, session: aiohttp.ClientSession) -> dict:
    """Ambil data dari DexScreener termasuk social links."""
    try:
        async with session.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            data = await r.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return {}
            p = sorted(pairs, key=lambda x: float(x.get("liquidity", {}).get("usd", 0) or 0), reverse=True)[0]
            info = p.get("info", {})
            socials = {s.get("type"): s.get("url") for s in info.get("socials", [])}
            websites = [w.get("url") for w in info.get("websites", [])]
            return {
                "twitter": socials.get("twitter"),
                "telegram": socials.get("telegram"),
                "website": websites[0] if websites else None,
                "dex_paid": bool(info.get("openGraph")),
                "pair_created": p.get("pairCreatedAt"),
                "txns_5m": p.get("txns", {}).get("m5", {}),
                "price_usd": p.get("priceUsd"),
            }
    except Exception as e:
        logger.error(f"DexScreener error: {e}")
        return {}


async def get_pumpfun_info(mint: str, session: aiohttp.ClientSession) -> dict:
    """Info dari pump.fun — replies, creator, description."""
    try:
        async with session.get(
            f"https://frontend-api.pump.fun/coins/{mint}",
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            if r.status != 200:
                return {}
            d = await r.json()
            return {
                "name": d.get("name"),
                "symbol": d.get("symbol"),
                "description": (d.get("description", "") or "")[:200],
                "creator": d.get("creator", "")[:12] + "..." if d.get("creator") else None,
                "reply_count": d.get("reply_count", 0),
                "twitter": d.get("twitter"),
                "telegram": d.get("telegram"),
                "website": d.get("website"),
                "bonding_complete": d.get("complete", False),
                "king_of_the_hill": d.get("king_of_the_hill_timestamp") is not None,
            }
    except Exception as e:
        logger.error(f"Pump.fun info error: {e}")
        return {}


async def get_rugcheck_full(mint: str, session: aiohttp.ClientSession) -> dict:
    """Full rugcheck report."""
    try:
        async with session.get(
            f"https://api.rugcheck.xyz/v1/tokens/{mint}/report",
            timeout=aiohttp.ClientTimeout(total=10)
        ) as r:
            data = await r.json()
            risks = data.get("risks", [])
            return {
                "score": data.get("score", 0),
                "risks": [{"name": r.get("name"), "level": r.get("level"), "score": r.get("score")} for r in risks],
                "mint_authority": data.get("mintAuthority"),
                "freeze_authority": data.get("freezeAuthority"),
                "top_holders": data.get("topHolders", [])[:5],
                "markets": len(data.get("markets", [])),
            }
    except Exception as e:
        logger.error(f"Rugcheck error: {e}")
        return {}


async def deep_research(mint: str, symbol: str = "") -> dict:
    """Full deep research — semua sources digabung."""
    async with aiohttp.ClientSession() as session:
        # Fetch semua parallel
        holder, onchain, dex, pumpfun, rugcheck = await asyncio.gather(
            get_holder_analysis(mint, session),
            get_onchain_metrics(mint, session),
            get_dexscreener_data(mint, session),
            get_pumpfun_info(mint, session),
            get_rugcheck_full(mint, session),
            return_exceptions=True
        )

        # Handle exceptions
        holder = holder if isinstance(holder, dict) else {}
        onchain = onchain if isinstance(onchain, dict) else {}
        dex = dex if isinstance(dex, dict) else {}
        pumpfun = pumpfun if isinstance(pumpfun, dict) else {}
        rugcheck = rugcheck if isinstance(rugcheck, dict) else {}

        return {
            "mint": mint,
            "symbol": symbol or pumpfun.get("symbol", "UNKNOWN"),
            "holder_analysis": holder,
            "onchain_metrics": onchain,
            "dex_data": dex,
            "pumpfun_info": pumpfun,
            "rugcheck": rugcheck,
            "researched_at": datetime.now().isoformat()
        }


async def ai_verdict(research: dict) -> str:
    """Minta AI kasih verdict berdasarkan semua data research."""
    prompt = f"""Kamu adalah crypto degen analyst expert di Solana.
Analisa token ini dan kasih verdict trading yang jelas.

TOKEN: {research.get('symbol')} ({research.get('mint', '')[:16]}...)

HOLDER ANALYSIS:
- Top 1 holder: {research.get('holder_analysis', {}).get('top1_pct', 'N/A')}%
- Top 5 holders: {research.get('holder_analysis', {}).get('top5_pct', 'N/A')}%
- Top 10 holders: {research.get('holder_analysis', {}).get('top10_pct', 'N/A')}%
- Whale risk: {research.get('holder_analysis', {}).get('whale_risk', 'N/A')}

ON-CHAIN METRICS:
- Volume 1h: ${research.get('onchain_metrics', {}).get('volume_1h', 0):,.0f}
- Volume 24h: ${research.get('onchain_metrics', {}).get('volume_24h', 0):,.0f}
- Volume trend: {research.get('onchain_metrics', {}).get('volume_trend', 'N/A')}
- Price 1h: {research.get('onchain_metrics', {}).get('price_change_1h', 0):+.1f}%
- Price 24h: {research.get('onchain_metrics', {}).get('price_change_24h', 0):+.1f}%
- Buy ratio 24h: {research.get('onchain_metrics', {}).get('buy_ratio_24h', 0)}%
- Unique wallets 24h: {research.get('onchain_metrics', {}).get('unique_wallets_24h', 0)}
- MCap: ${research.get('onchain_metrics', {}).get('mcap', 0):,.0f}
- Liquidity: ${research.get('onchain_metrics', {}).get('liquidity', 0):,.0f}

PUMP.FUN INFO:
- Description: {research.get('pumpfun_info', {}).get('description', 'N/A')}
- Reply count: {research.get('pumpfun_info', {}).get('reply_count', 0)}
- King of the hill: {research.get('pumpfun_info', {}).get('king_of_the_hill', False)}
- Bonding complete: {research.get('pumpfun_info', {}).get('bonding_complete', False)}
- Has Twitter: {bool(research.get('pumpfun_info', {}).get('twitter') or research.get('dex_data', {}).get('twitter'))}
- Has Telegram: {bool(research.get('pumpfun_info', {}).get('telegram') or research.get('dex_data', {}).get('telegram'))}

RUGCHECK:
- Score: {research.get('rugcheck', {}).get('score', 0)}/1000
- Risks: {[r['name'] for r in research.get('rugcheck', {}).get('risks', [])]}

PENTING: Kalau data minim (liquidity $0, volume rendah, price flat 0%), langsung verdict SKIP — jangan APE IN hanya karena tidak ada red flag. No data = no confidence = SKIP.

Berikan analisa dalam bahasa Indonesia casual, format:

🎯 VERDICT: [APE IN / WAIT / SKIP]
📊 CONFIDENCE: [HIGH/MEDIUM/LOW]

💡 ALASAN UTAMA (3 poin):
1. ...
2. ...
3. ...

⚠️ RED FLAGS:
- ...

✅ GREEN FLAGS:
- ...

💰 SARAN ENTRY: [kalau APE IN: size berapa, TP target, SL]
"""

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
                json={"model": "mistralai/mistral-small-3.1-24b-instruct", "max_tokens": 600,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as r:
                data = await r.json()
                if "choices" not in data:
                    raise Exception(f"API error: {data.get('error', data)}")
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI verdict error: {e}"


async def full_research_report(mint: str, symbol: str = "") -> str:
    """Return formatted report string untuk dikirim ke Telegram."""
    research = await deep_research(mint, symbol)
    verdict = await ai_verdict(research)

    h = research.get("holder_analysis", {})
    o = research.get("onchain_metrics", {})
    p = research.get("pumpfun_info", {})
    d = research.get("dex_data", {})

    socials = []
    if p.get("twitter") or d.get("twitter"):
        socials.append("🐦 Twitter")
    if p.get("telegram") or d.get("telegram"):
        socials.append("✈️ Telegram")
    if p.get("website") or d.get("website"):
        socials.append("🌐 Website")

    # Cek apakah prebond
    is_prebond = o.get("is_pumpfun_prebond", False)
    bonding_pct = o.get("bonding_progress", 0)
    prebond_note = f"\n⚠️ <b>Token masih di Pump.fun bonding curve ({bonding_pct:.1f}%)</b>\nLP akan muncul setelah bonding 100% dan migrate ke DEX." if is_prebond else ""

    # Holder note — kalau prebond, top holder bisa bonding curve
    holder_note = "\n⚠️ <i>Note: Holder besar mungkin termasuk bonding curve contract</i>" if is_prebond else ""

    report = f"""🔬 <b>DEEP RESEARCH — {research.get('symbol')}</b>{prebond_note}

👥 <b>Holder Distribution:</b>
- Top 1: {h.get('top1_pct', 'N/A')}% | Top 5: {h.get('top5_pct', 'N/A')}% | Top 10: {h.get('top10_pct', 'N/A')}%
- Whale Risk: {h.get('whale_risk', 'N/A')}{holder_note}

📈 <b>On-Chain Metrics:</b>
- Vol 1h: ${o.get('volume_1h', 0):,.0f} | Vol 24h: ${o.get('volume_24h', 0):,.0f}
- Trend: {o.get('volume_trend', 'N/A')} | Buy ratio: {o.get('buy_ratio_24h', 0)}%
- Price 1h: {o.get('price_change_1h', 0):+.1f}% | 24h: {o.get('price_change_24h', 0):+.1f}%
- Unique wallets 24h: {o.get('unique_wallets_24h', 0)}

🪄 <b>Pump.fun:</b>
- Replies: {p.get('reply_count', 0)} | KotH: {'✅' if p.get('king_of_the_hill') else '❌'}
- Bonded: {'✅' if p.get('bonding_complete') else '❌'}
- Socials: {' | '.join(socials) if socials else 'None'}

{verdict}

🔗 https://dexscreener.com/solana/{mint}
🔗 https://pump.fun/{mint}"""

    return report


if __name__ == "__main__":
    import sys
    mint = sys.argv[1] if len(sys.argv) > 1 else "BHvsujaabxvm9SrM9mnHjAubypzz63DVz8qtdDtTpump"
    symbol = sys.argv[2] if len(sys.argv) > 2 else "WRONG"

    async def main():
        report = await full_research_report(mint, symbol)
        print(report)

    asyncio.run(main())
