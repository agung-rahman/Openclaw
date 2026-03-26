import asyncio
import httpx
from datetime import datetime
from telethon import TelegramClient, events

# ============================================
# CREDENTIALS - GANTI INI
# ============================================
TELEGRAM_API_ID = 39237948
TELEGRAM_API_HASH = '1e2b86fa6dcc13d5f07ca86feecb2b4c'
BOT_USERNAME = '@retarddegenmaxxingdisc_bot'
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = '5664251521'
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')

# ============================================
# AIRDROP CHANNELS (disabled)
# ============================================
AIRDROP_CHANNELS = [
    'AirdropAnalyst',
    'airdropfind',
    'airdropcloudJP',
    'AirdropUmbrellaX',
    'airdropdaydua',
    'PegazusEcosystem',
    'AIRDROPSATSETT',
    'IndonesiaAirdropzReborn',
]

# ============================================
# SETTINGS
# ============================================
VOLUME_SPIKE_MULTIPLIER = 1.5
MIN_LIQUIDITY = 1000
MAX_MARKET_CAP = 200000
MIN_MARKET_CAP = 3000
MAX_TOKEN_AGE_DAYS = 365
MIN_TOKEN_AGE_HOURS = 2
VALID_DEX = ['pumpfun', 'pumpswap', 'raydium', 'orca', 'jupiter']

# Bundle threshold
MAX_BUNDLE_PCT = 30   # skip kalau bundle > 30%
WARN_BUNDLE_PCT = 15  # warning kalau bundle 15-30%

# ============================================
# TELEGRAM CLIENT
# ============================================
tg_client = TelegramClient('degen_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)

# ============================================
# HELPERS
# ============================================
async def send_to_bot(text):
    # Simpan ke queue, jangan kirim otomatis
    try:
        import sys
        sys.path.insert(0, '/root')
        from signal_queue import add_signal
        add_signal({"text": text})
    except Exception as e:
        print(f"Queue error: {e}")

async def send_alert_direct(text):
    # Simpan ke queue dengan mint + token extracted
    try:
        import sys, re
        sys.path.insert(0, '/root')
        from signal_queue import add_signal
        # Extract mint dari dexscreener URL
        _mint = ""
        _token = ""
        _m = re.search(r'dexscreener\.com/solana/([A-Za-z0-9]{30,})', text)
        if _m:
            _mint = _m.group(1)
        # Extract symbol dari baris "🪙 NAME ($SYMBOL)"
        _s = re.search(r'\(\$([^)]+)\)', text)
        if not _s:
            _s = re.search(r'\$([A-Z]{2,10})\b', text)
        if _s:
            _token = _s.group(1)
        add_signal({"text": text, "type": "scanner", "mint": _mint, "token": _token})
    except Exception as e:
        print(f"Queue error: {e}")

# ============================================
# RUGCHECK
# ============================================
async def check_rugcheck(token_address):
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f'https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary',
                timeout=15
            )
            data = resp.json()

            score = data.get('score', 0)
            risks = data.get('risks', [])
            risk_names = [r.get('name', '') for r in risks]
            high_risks = [r.get('name', '') for r in risks if r.get('level') == 'danger']

            # Cek bundle percentage dari risks
            bundle_pct = 0
            for r in risks:
                name = r.get('name', '').lower()
                if 'bundle' in name or 'cluster' in name:
                    # Coba ambil value dari description
                    desc = r.get('description', '')
                    # Parse persentase dari description kalau ada
                    import re
                    pct_match = re.search(r'(\d+(?:\.\d+)?)\s*%', desc)
                    if pct_match:
                        bundle_pct = float(pct_match.group(1))
                    else:
                        bundle_pct = 50  # default tinggi kalau ada bundle tapi ga ada %

            has_mint = any('mint' in r.lower() for r in risk_names)
            has_freeze = any('freeze' in r.lower() for r in risk_names)

            return {
                'score': score,
                'risk_names': risk_names,
                'high_risks': high_risks,
                'bundle_pct': bundle_pct,
                'has_mint': has_mint,
                'has_freeze': has_freeze,
                'total_risks': len(risks)
            }
        except Exception as e:
            print(f"Rugcheck error: {e}")
            return None

def rug_emoji(score):
    if score >= 700:
        return "🟢"
    elif score >= 400:
        return "🟡"
    else:
        return "🔴"

def bundle_emoji(pct):
    if pct == 0:
        return "✅"
    elif pct < 15:
        return "🟢"
    elif pct < 30:
        return "🟡"
    else:
        return "🔴"

# ============================================
# AIRDROP MONITOR
# ============================================
# @tg_client.on(events.NewMessage(chats=AIRDROP_CHANNELS))
async def airdrop_handler(event):
    try:
        chat = await event.get_chat()
        channel_name = chat.title
        message = event.message.message or ''

        print(f"[AIRDROP] [{channel_name}] {message[:80]}")

        alert = f"🪂 AIRDROP ALERT\n\n📢 [{channel_name}]\n\n{message}"
        await send_alert_direct(alert)

        analysis = f"""New airdrop alert from {channel_name}:

{message}

Is this airdrop legit and worth farming? Analyze:
1. Legitimacy check
2. Effort vs reward estimate
3. Which chains/wallets needed?
4. Verdict: FARM / SKIP"""

        await send_to_bot(analysis)

    except Exception as e:
        print(f"Error airdrop handler: {e}")

# ============================================
# TOKEN FETCHER
# ============================================
async def get_tokens():
    async with httpx.AsyncClient() as client:
        all_pairs = []
        urls = [
            'https://api.dexscreener.com/latest/dex/search?q=solana+new',
            'https://api.dexscreener.com/latest/dex/search?q=sol+meme',
            'https://api.dexscreener.com/latest/dex/search?q=raydium+new',
            'https://api.dexscreener.com/latest/dex/search?q=pumpswap',
            'https://api.dexscreener.com/latest/dex/search?q=orca+solana',
            'https://api.dexscreener.com/token-boosts/top/v1',
            'https://api.dexscreener.com/token-profiles/latest/v1',
        ]
        for url in urls:
            try:
                resp = await client.get(url, timeout=30)
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            if 'pairs' in item:
                                all_pairs.extend(item['pairs'])
                            elif item.get('chainId') == 'solana':
                                all_pairs.append(item)
                elif isinstance(data, dict):
                    if 'pairs' in data:
                        all_pairs.extend(data['pairs'])
            except Exception as e:
                print(f"Error fetching {url}: {e}")

        seen = set()
        unique = []
        for p in all_pairs:
            addr = p.get('pairAddress', '')
            if addr and addr not in seen:
                seen.add(addr)
                unique.append(p)
        return unique

# ============================================
# TOKEN ANALYZER
# ============================================
async def analyze_token(pair):
    try:
        dex_id = pair.get('dexId', '').lower()
        token_address = pair.get('baseToken', {}).get('address', '')
        token_name = pair.get('baseToken', {}).get('name', '')
        token_symbol = pair.get('baseToken', {}).get('symbol', '')

        volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
        volume_1h = float(pair.get('volume', {}).get('h1', 0) or 0)

        price_change_24h = float(pair.get('priceChange', {}).get('h24', 0) or 0)
        price_change_6h = float(pair.get('priceChange', {}).get('h6', 0) or 0)
        price_change_1h = float(pair.get('priceChange', {}).get('h1', 0) or 0)

        liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
        market_cap = float(pair.get('marketCap', 0) or 0)

        txns_buys_1h = pair.get('txns', {}).get('h1', {}).get('buys', 0)
        txns_sells_1h = pair.get('txns', {}).get('h1', {}).get('sells', 0)

        created_at = pair.get('pairCreatedAt', 0)
        age_hours = (datetime.now().timestamp() - created_at / 1000) / 3600 if created_at else 0

        if not any(dex in dex_id for dex in VALID_DEX):
            return None
        if not token_symbol or market_cap == 0:
            return None
        if liquidity < MIN_LIQUIDITY:
            return None
        if market_cap > MAX_MARKET_CAP:
            return None
        if market_cap < MIN_MARKET_CAP:
            return None
        if age_hours < MIN_TOKEN_AGE_HOURS:
            return None
        if age_hours > MAX_TOKEN_AGE_DAYS * 24:
            return None

        avg_hourly = volume_24h / 24 if volume_24h > 0 else 0
        spike = volume_1h / avg_hourly if avg_hourly > 0 else 0

        total_txns_1h = txns_buys_1h + txns_sells_1h
        buy_ratio_1h = (txns_buys_1h / total_txns_1h * 100) if total_txns_1h > 0 else 0

        price_tight = abs(price_change_6h) < 5

        print(f"[TOKEN] {token_symbol} [{dex_id}]: spike={round(spike,2)}x | price_1h={price_change_1h}% | buyratio={round(buy_ratio_1h,1)}% | mcap=${market_cap:,.0f}")

        is_volume_anomaly = spike >= VOLUME_SPIKE_MULTIPLIER and price_change_1h < 15
        is_accumulation = price_tight and buy_ratio_1h > 55 and txns_buys_1h > 3
        is_stealth_buy = spike >= 1.5 and abs(price_change_1h) < 5 and txns_buys_1h > txns_sells_1h

        if is_volume_anomaly or is_accumulation or is_stealth_buy:
            signals = []
            if is_volume_anomaly:
                signals.append("VOLUME SPIKE")
            if is_accumulation:
                signals.append("ACCUMULATION")
            if is_stealth_buy:
                signals.append("STEALTH BUY")

            return {
                'name': token_name,
                'symbol': token_symbol,
                'address': token_address,
                'dex': dex_id,
                'signal': ' + '.join(signals),
                'volume_spike': round(spike, 2),
                'volume_1h': volume_1h,
                'volume_24h': volume_24h,
                'price_change_1h': price_change_1h,
                'price_change_6h': price_change_6h,
                'price_change_24h': price_change_24h,
                'buy_ratio_1h': round(buy_ratio_1h, 1),
                'txns_buys_1h': txns_buys_1h,
                'txns_sells_1h': txns_sells_1h,
                'liquidity': liquidity,
                'market_cap': market_cap,
                'age_hours': round(age_hours, 1),
                'dexscreener_url': pair.get('url', '')
            }
    except Exception as e:
        print(f"Error analyzing token: {e}")
    return None

# ============================================
# SEND TOKEN ALERT
# ============================================
async def send_token_alert(token):
    age_str = f"{token['age_hours']}h" if token['age_hours'] < 48 else f"{round(token['age_hours']/24, 1)}d"
    graduated = "✅ Graduated" if token['dex'] in ['raydium', 'orca'] else "🆕 Pump.fun"

    # Cek rugcheck
    print(f"  Checking rugcheck for {token['symbol']}...")
    rug = await check_rugcheck(token['address'])

    if rug:
        bundle_pct = rug['bundle_pct']

        # Skip kalau bundle > 30%
        if bundle_pct > MAX_BUNDLE_PCT:
            print(f"  SKIPPED {token['symbol']} — bundle {bundle_pct}% > {MAX_BUNDLE_PCT}%")
            return

        b_emoji = bundle_emoji(bundle_pct)
        r_emoji = rug_emoji(rug['score'])

        bundle_str = f"{b_emoji} Bundle/Cluster: {bundle_pct}%"
        if bundle_pct >= WARN_BUNDLE_PCT:
            bundle_str += " ⚠️ HIGH"
        elif bundle_pct > 0:
            bundle_str += " (ok)"
        else:
            bundle_str += " (clean)"

        rug_str = f"""{r_emoji} Rugcheck Score: {rug['score']}/1000
{bundle_str}
{'⚠️ MINT ENABLED' if rug['has_mint'] else '✅ No Mint'}
{'⚠️ FREEZE ENABLED' if rug['has_freeze'] else '✅ No Freeze'}"""

        if rug['high_risks']:
            rug_str += f"\n🚨 Dangers: {', '.join(rug['high_risks'][:3])}"

        rug_info_for_analysis = f"""Rugcheck Score: {rug['score']}/1000
Bundle/Cluster: {bundle_pct}% ({'HIGH RISK' if bundle_pct >= WARN_BUNDLE_PCT else 'OK'})
Mint Enabled: {rug['has_mint']}
Freeze Enabled: {rug['has_freeze']}
High Risk Flags: {', '.join(rug['high_risks']) if rug['high_risks'] else 'None'}
All Risks: {', '.join(rug['risk_names'][:5]) if rug['risk_names'] else 'None'}"""

    else:
        rug_str = "⚪ Rugcheck: unavailable"
        rug_info_for_analysis = "Rugcheck: unavailable"

    alert = f"""🎯 {token['signal']}

🪙 {token['name']} (${token['symbol']})
🏦 {token['dex']} | {graduated}
⏰ Age: {age_str}
💧 Liquidity: ${token['liquidity']:,.0f}
📊 Market Cap: ${token['market_cap']:,.0f}

🛡️ Safety Check:
{rug_str}

📈 Volume Spike: {token['volume_spike']}x normal
💰 Volume 1h: ${token['volume_1h']:,.0f}

📊 Txns 1h: {token['txns_buys_1h']} buys / {token['txns_sells_1h']} sells ({token['buy_ratio_1h']}% buys)

📉 Price 1h: {token['price_change_1h']}%
📉 Price 6h: {token['price_change_6h']}%
📉 Price 24h: {token['price_change_24h']}%

🔗 {token['dexscreener_url']}"""

    await send_alert_direct(alert)
    await asyncio.sleep(1)

    analysis = f"""Analyze this Solana token signal for degen play:

Signal: {token['signal']}
Token: {token['name']} (${token['symbol']})
DEX: {token['dex']} ({graduated})
Age: {age_str}
Liquidity: ${token['liquidity']:,.0f}
Market Cap: ${token['market_cap']:,.0f}
Volume Spike: {token['volume_spike']}x normal
Txns 1h: {token['txns_buys_1h']} buys / {token['txns_sells_1h']} sells ({token['buy_ratio_1h']}% buys)
Price 1h: {token['price_change_1h']}%
Price 6h: {token['price_change_6h']}%
Price 24h: {token['price_change_24h']}%

{rug_info_for_analysis}

Note: Bundle/cluster >30% auto-skipped. This token passed (<{MAX_BUNDLE_PCT}% bundle).

DexScreener: {token['dexscreener_url']}

Analyze:
1. Genuine accumulation or wash trading?
2. Smart money signal or noise?
3. Given rugcheck data — what's the real rug risk?
4. Is bundle % acceptable or concerning?
5. Verdict: WORTH APE / SKIP + reason + entry size (max $20)"""

    await send_to_bot(analysis)

# ============================================
# VOLUME SCANNER LOOP
# ============================================
async def volume_scanner():
    print("🔍 Volume scanner started...")
    alerted_tokens = set()

    while True:
        try:
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning tokens...")
            pairs = await get_tokens()
            solana_pairs = [p for p in pairs if isinstance(p, dict) and p.get('chainId') == 'solana']
            print(f"Solana pairs: {len(solana_pairs)}")

            for pair in solana_pairs:
                result = await analyze_token(pair)
                if result and result['address'] not in alerted_tokens:
                    alerted_tokens.add(result['address'])
                    await send_token_alert(result)
                    await asyncio.sleep(2)

            if len(alerted_tokens) > 1000:
                alerted_tokens.clear()

        except Exception as e:
            print(f"Error scanner: {e}")

        await asyncio.sleep(300)

# ============================================
# MAIN
# ============================================
async def main():
    print("🎯 Degen Hunter started!")

    # Start wallet tracker
    try:
        from wallet_tracker import wallet_tracker_loop
        asyncio.create_task(wallet_tracker_loop())
        print("👛 Wallet tracker started — 80 wallets!", flush=True)
    except Exception as e:
        print(f"⚠️ Wallet tracker error: {e}")
    # Start auto trader
    try:
        from auto_trader import auto_trader_loop
        asyncio.create_task(auto_trader_loop())
        print("🤖 Auto trader started!", flush=True)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"Auto trader error: {e}")

    # Start position monitor
    try:
        from position_monitor_v2 import monitor_positions
        asyncio.create_task(monitor_positions())
        print("👁️ Position monitor started!", flush=True)
    except Exception as e:
        print(f"⚠️ Position monitor error: {e}")

    # Start TG commander
    try:
        from tg_commander import commander_loop
        asyncio.create_task(commander_loop())
        print("🤖 TG Commander started!", flush=True)
    except Exception as e:
        print(f"⚠️ TG Commander error: {e}")

    print(f"Bundle filter: skip >{MAX_BUNDLE_PCT}% | warn >{WARN_BUNDLE_PCT}%\n")

    await tg_client.start()
    asyncio.create_task(volume_scanner())
    await tg_client.run_until_disconnected()

asyncio.run(main())
