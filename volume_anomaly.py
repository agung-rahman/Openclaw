import asyncio
import httpx
from datetime import datetime

# Credentials - GANTI INI
HELIUS_API_KEY = os.getenv('HELIUS_API_KEY', '')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = '5664251521'

# Threshold
VOLUME_SPIKE_MULTIPLIER = 2
MIN_LIQUIDITY = 1000
MAX_MARKET_CAP = 200000
MIN_MARKET_CAP = 3000
MAX_TOKEN_AGE_DAYS = 365
MIN_TOKEN_AGE_HOURS = 2

VALID_DEX = ['pumpfun', 'pumpswap', 'raydium', 'orca', 'jupiter']

async def get_tokens():
    async with httpx.AsyncClient() as client:
        all_pairs = []
        urls = [
            # New pairs Solana
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

        # Deduplicate
        seen = set()
        unique_pairs = []
        for p in all_pairs:
            addr = p.get('pairAddress', '')
            if addr and addr not in seen:
                seen.add(addr)
                unique_pairs.append(p)

        return unique_pairs

async def get_token_txns(token_address):
    """Ambil data transaksi dari Helius untuk detect accumulation pattern"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f'https://api.helius.xyz/v0/addresses/{token_address}/transactions',
                params={
                    'api-key': HELIUS_API_KEY,
                    'limit': 50,
                    'type': 'SWAP'
                },
                timeout=20
            )
            return resp.json()
        except:
            return []

def detect_accumulation(txns):
    """Detect pola akumulasi dari transaksi"""
    if not txns or not isinstance(txns, list):
        return None

    buys = 0
    sells = 0
    total_buy_amount = 0
    total_sell_amount = 0
    unique_buyers = set()

    for tx in txns[:50]:
        try:
            token_transfers = tx.get('tokenTransfers', [])
            for transfer in token_transfers:
                amount = float(transfer.get('tokenAmount', 0))
                from_addr = transfer.get('fromUserAccount', '')
                to_addr = transfer.get('toUserAccount', '')

                if amount > 0:
                    if to_addr and len(to_addr) > 10:
                        buys += 1
                        total_buy_amount += amount
                        unique_buyers.add(to_addr)
                    elif from_addr and len(from_addr) > 10:
                        sells += 1
                        total_sell_amount += amount
        except:
            continue

    total_txns = buys + sells
    if total_txns == 0:
        return None

    buy_ratio = buys / total_txns if total_txns > 0 else 0

    return {
        'buys': buys,
        'sells': sells,
        'buy_ratio': round(buy_ratio * 100, 1),
        'unique_buyers': len(unique_buyers),
        'total_txns': total_txns
    }

async def analyze_token(pair):
    try:
        dex_id = pair.get('dexId', '').lower()
        token_address = pair.get('baseToken', {}).get('address', '')
        token_name = pair.get('baseToken', {}).get('name', '')
        token_symbol = pair.get('baseToken', {}).get('symbol', '')

        volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
        volume_6h = float(pair.get('volume', {}).get('h6', 0) or 0)
        volume_1h = float(pair.get('volume', {}).get('h1', 0) or 0)

        price_change_24h = float(pair.get('priceChange', {}).get('h24', 0) or 0)
        price_change_6h = float(pair.get('priceChange', {}).get('h6', 0) or 0)
        price_change_1h = float(pair.get('priceChange', {}).get('h1', 0) or 0)

        liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
        market_cap = float(pair.get('marketCap', 0) or 0)

        # Txns data
        txns_buys_24h = pair.get('txns', {}).get('h24', {}).get('buys', 0)
        txns_sells_24h = pair.get('txns', {}).get('h24', {}).get('sells', 0)
        txns_buys_1h = pair.get('txns', {}).get('h1', {}).get('buys', 0)
        txns_sells_1h = pair.get('txns', {}).get('h1', {}).get('sells', 0)

        created_at = pair.get('pairCreatedAt', 0)
        age_hours = (datetime.now().timestamp() - created_at / 1000) / 3600 if created_at else 0

        # Filter DEX
        if not any(dex in dex_id for dex in VALID_DEX):
            return None

        # Skip empty
        if not token_symbol or market_cap == 0:
            return None

        # Filter dasar
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

        # Hitung spike
        avg_hourly = volume_24h / 24 if volume_24h > 0 else 0
        spike = volume_1h / avg_hourly if avg_hourly > 0 else 0

        # Hitung buy ratio
        total_txns_1h = txns_buys_1h + txns_sells_1h
        buy_ratio_1h = (txns_buys_1h / total_txns_1h * 100) if total_txns_1h > 0 else 0

        # Price range tight (akumulasi) = harga bergerak < 5% dalam 6 jam
        price_tight = abs(price_change_6h) < 5

        print(f"{token_symbol} [{dex_id}]: spike={round(spike,2)}x | price_1h={price_change_1h}% | price_6h={price_change_6h}% | buyratio={round(buy_ratio_1h,1)}% | mcap=${market_cap:,.0f} | age={round(age_hours,1)}h")

        # Kondisi anomali:
        # 1. Volume spike 2x+ dari normal
        # 2. Harga masih flat/pelan (tidak sudah pump kencang)
        # 3. Buy ratio tinggi (>55%)
        is_volume_anomaly = spike >= VOLUME_SPIKE_MULTIPLIER and price_change_1h < 15
        is_accumulation = price_tight and buy_ratio_1h > 55 and txns_buys_1h > 3
        is_stealth_pump = spike >= 1.5 and abs(price_change_1h) < 5 and txns_buys_1h > txns_sells_1h

        if is_volume_anomaly or is_accumulation or is_stealth_pump:
            signal_type = []
            if is_volume_anomaly:
                signal_type.append("VOLUME SPIKE")
            if is_accumulation:
                signal_type.append("ACCUMULATION")
            if is_stealth_pump:
                signal_type.append("STEALTH BUY")

            return {
                'name': token_name,
                'symbol': token_symbol,
                'address': token_address,
                'dex': dex_id,
                'signal': ' + '.join(signal_type),
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
        print(f"Error analyzing: {e}")
    return None

async def send_alert(token):
    age_str = f"{token['age_hours']}h" if token['age_hours'] < 48 else f"{round(token['age_hours']/24, 1)}d"
    graduated = "✅ Graduated" if token['dex'] in ['raydium', 'orca'] else "🆕 Pump.fun"

    message = f"""🎯 {token['signal']}

🪙 {token['name']} (${token['symbol']})
🏦 {token['dex']} | {graduated}
⏰ Age: {age_str}
💧 Liquidity: ${token['liquidity']:,.0f}
📊 Market Cap: ${token['market_cap']:,.0f}

📈 Volume Spike: {token['volume_spike']}x normal
💰 Volume 1h: ${token['volume_1h']:,.0f}

📊 Txns 1h: {token['txns_buys_1h']} buys / {token['txns_sells_1h']} sells ({token['buy_ratio_1h']}% buys)

📉 Price 1h: {token['price_change_1h']}%
📉 Price 6h: {token['price_change_6h']}%
📉 Price 24h: {token['price_change_24h']}%

🔗 {token['dexscreener_url']}"""

    analysis_prompt = f"""Analyze this Solana token signal:

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
DexScreener: {token['dexscreener_url']}

Analyze:
1. Is this genuine accumulation or wash trading?
2. Buy/sell ratio — is smart money accumulating quietly?
3. Price still flat = good entry opportunity?
4. Risk level (rug potential, liquidity depth)?

Verdict: WORTH APE / SKIP — with reason + suggested entry (max $20)."""

    async with httpx.AsyncClient() as client:
        await client.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={
                'chat_id': CHAT_ID,
                'text': message,
                'disable_web_page_preview': False
            }
        )
        await asyncio.sleep(1)
        await client.post(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            json={
                'chat_id': CHAT_ID,
                'text': analysis_prompt
            }
        )

async def main():
    print("🔍 Solana Accumulation Detector started...")
    print(f"Signals: Volume Spike | Accumulation | Stealth Buy")
    print(f"Filter: mcap ${MIN_MARKET_CAP:,}-${MAX_MARKET_CAP:,} | liq min ${MIN_LIQUIDITY:,}\n")
    alerted_tokens = set()

    while True:
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanning...")
            pairs = await get_tokens()
            solana_pairs = [p for p in pairs if isinstance(p, dict) and p.get('chainId') == 'solana']
            print(f"Unique Solana pairs: {len(solana_pairs)}\n")

            for pair in solana_pairs:
                result = await analyze_token(pair)
                if result and result['address'] not in alerted_tokens:
                    alerted_tokens.add(result['address'])
                    await send_alert(result)
                    await asyncio.sleep(2)

            if len(alerted_tokens) > 1000:
                alerted_tokens.clear()

        except Exception as e:
            print(f"Error main: {e}")

        await asyncio.sleep(300)

asyncio.run(main())
