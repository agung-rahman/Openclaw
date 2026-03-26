"""
narrative_manager.py - Kasih context narasi ke AI sebelum analisa token
1. Baca narratives.txt yang lo update manual
2. Scrape Nitter untuk cek buzz token di Twitter
"""

import asyncio
import aiohttp
import logging
import re
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

NARRATIVES_FILE = Path("/root/narratives.txt")

# Nitter instances (public, no API key needed)
BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "")
AXIOM_REFRESH_TOKEN = os.getenv("AXIOM_REFRESH_TOKEN", "")

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]

# Default narratives kalau file belum ada
DEFAULT_NARRATIVES = """# Narratives yang lagi hot - update manual kapan aja
# Format: satu narasi per baris, mulai dengan # untuk komen

## AI & Autonomous Agents
ai agent
autonomous ai
agentic
openai
claude
deepseek
grok
llm
agi

## Meme Coin Trending
dog
cat
pepe
wojak
based
degen
gigachad
trump
maga

## Solana Ecosystem
solana
sol
pump.fun
pumpswap
raydium
jupiter
bonk
jito

## Politik & Presiden
trump
elon
musk
doge
vivek
rfk
maga
usa

## Keywords Pompom
100x
gem
ape
moon
soon
launch
stealth
narrative
"""


def ensure_narratives_file():
    """Buat file narratives.txt kalau belum ada."""
    if not NARRATIVES_FILE.exists():
        NARRATIVES_FILE.write_text(DEFAULT_NARRATIVES)
        logger.info(f"Created narratives file: {NARRATIVES_FILE}")


def load_narratives() -> list[str]:
    """Load dan parse narratives dari file."""
    ensure_narratives_file()
    lines = NARRATIVES_FILE.read_text().lower().splitlines()
    narratives = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            narratives.append(line)
    return narratives


def check_token_narrative_match(token_name: str, token_symbol: str) -> dict:
    """
    Cek apakah nama/symbol token nyambung ke narasi yang lagi hot.
    Return: {matched: bool, matches: list, score: int}
    """
    narratives = load_narratives()
    token_lower = f"{token_name} {token_symbol}".lower()

    matches = []
    for narrative in narratives:
        if narrative in token_lower or token_lower in narrative:
            matches.append(narrative)

    # Partial match juga
    token_words = re.findall(r'\w+', token_lower)
    for word in token_words:
        if len(word) >= 3:  # min 3 huruf
            for narrative in narratives:
                if word in narrative and narrative not in matches:
                    matches.append(f"{narrative} (partial)")

    score = min(len(matches) * 2, 10)  # max score 10

    return {
        "matched": len(matches) > 0,
        "matches": matches[:5],  # max 5 matches
        "score": score,
        "summary": f"Matches {len(matches)} active narratives: {', '.join(matches[:3])}" if matches else "No narrative match found"
    }




async def get_dexscreener_top100() -> list:
    """Ambil top 100 token Solana dari berbagai endpoint DexScreener."""
    tokens = []
    seen = set()
    urls = [
        "https://api.dexscreener.com/token-boosts/top/v1",
        "https://api.dexscreener.com/token-profiles/latest/v1",
        "https://api.dexscreener.com/latest/dex/search?q=solana+new",
        "https://api.dexscreener.com/latest/dex/search?q=sol+meme",
        "https://api.dexscreener.com/latest/dex/search?q=pumpswap",
        "https://api.dexscreener.com/latest/dex/search?q=raydium+new",
    ]
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    items = data if isinstance(data, list) else data.get("pairs", [])
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        if item.get("chainId") != "solana":
                            continue
                        mint = item.get("tokenAddress") or item.get("baseToken", {}).get("address", "")
                        if not mint or mint in seen:
                            continue
                        seen.add(mint)
                        tokens.append({
                            "mint": mint,
                            "symbol": item.get("symbol") or item.get("baseToken", {}).get("symbol", ""),
                            "boost": item.get("totalAmount", 0),
                            "volume_24h": float(item.get("volume", {}).get("h24", 0) or 0),
                            "price_change_24h": float(item.get("priceChange", {}).get("h24", 0) or 0),
                            "description": item.get("description", "")[:100]
                        })
                        if len(tokens) >= 100:
                            return tokens
            except Exception as e:
                logger.debug(f"DexScreener top100 error: {e}")
    return tokens[:100]

async def get_birdeye_trending(api_key: str) -> list:
    """Ambil trending tokens dari Birdeye."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://public-api.birdeye.so/defi/token_trending?sort_by=rank&sort_type=asc&limit=100&chain=solana",
                headers={"X-API-KEY": api_key, "X-Chain": "solana"},
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                tokens = data.get("data", {}).get("tokens", [])
                return [{"mint": t.get("address",""), "symbol": t.get("symbol",""), "name": t.get("name",""), "rank": t.get("rank",0), "price_change_24h": t.get("price24hChangePercent",0)} for t in tokens]
    except Exception as e:
        logger.debug(f"Birdeye error: {e}")
        return []

async def scrape_nitter_buzz(token_symbol: str, token_name: str) -> dict:
    """
    Scrape Nitter untuk cek buzz token di Twitter.
    Return: {found: bool, tweet_count: int, recent_tweets: list, sentiment: str}
    """
    query = f"${token_symbol} OR {token_name} solana"
    results = {
        "found": False,
        "tweet_count": 0,
        "recent_tweets": [],
        "sentiment": "unknown",
        "source": "nitter"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for instance in NITTER_INSTANCES:
        try:
            url = f"{instance}/search?q={query}&f=tweets"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8),
                    ssl=False
                ) as resp:
                    if resp.status != 200:
                        continue

                    html = await resp.text()

                    # Parse tweet count
                    tweet_matches = re.findall(
                        r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>',
                        html,
                        re.DOTALL
                    )

                    # Clean HTML tags
                    tweets = []
                    for t in tweet_matches[:5]:
                        clean = re.sub(r'<[^>]+>', '', t).strip()
                        if clean and len(clean) > 10:
                            tweets.append(clean[:200])

                    if tweets:
                        results["found"] = True
                        results["tweet_count"] = len(tweet_matches)
                        results["recent_tweets"] = tweets

                        # Simple sentiment check
                        all_text = ' '.join(tweets).lower()
                        bullish_words = ['moon', '100x', 'gem', 'ape', 'buy', 'pump', 'launch', 'soon', '🚀', '💎', '🔥']
                        bearish_words = ['rug', 'scam', 'dump', 'sell', 'dead', 'exit', 'warning', '⚠️']

                        bull_count = sum(1 for w in bullish_words if w in all_text)
                        bear_count = sum(1 for w in bearish_words if w in all_text)

                        if bull_count > bear_count:
                            results["sentiment"] = "bullish"
                        elif bear_count > bull_count:
                            results["sentiment"] = "bearish"
                        else:
                            results["sentiment"] = "neutral"

                        logger.info(f"Nitter: found {len(tweets)} tweets for {token_symbol}, sentiment: {results['sentiment']}")
                        return results

        except Exception as e:
            logger.debug(f"Nitter {instance} failed: {e}")
            continue

    logger.info(f"Nitter: no results for {token_symbol} (all instances failed or no tweets)")
    return results


async def get_full_narrative_context(token_name: str, token_symbol: str, token_mint: str = '') -> str:
    """
    Gabungin narrative match + twitter buzz jadi context string untuk AI.
    """
    # 1. Check narrative match (instant, no network)
    narrative_result = check_token_narrative_match(token_name, token_symbol)

    # 2. Scrape Twitter buzz (async, ~3-8 detik)
    twitter_result = await scrape_nitter_buzz(token_symbol, token_name)

    # 3. Build context string
    context_parts = []

    # Narrative section
    if narrative_result["matched"]:
        context_parts.append(
            f"NARRATIVE MATCH: ✅ Token name/symbol matches active narratives!\n"
            f"Matched: {narrative_result['summary']}\n"
            f"Narrative score: {narrative_result['score']}/10"
        )
    else:
        context_parts.append(
            f"NARRATIVE MATCH: ❌ No match with current hot narratives\n"
            f"(AI agent, meme, solana ecosystem, politik)"
        )

    # Twitter section
    if twitter_result["found"]:
        tweets_preview = '\n'.join([f"  - {t[:100]}" for t in twitter_result["recent_tweets"][:3]])
        context_parts.append(
            f"\nTWITTER BUZZ: ✅ Found {twitter_result['tweet_count']} recent tweets\n"
            f"Sentiment: {twitter_result['sentiment'].upper()}\n"
            f"Recent tweets:\n{tweets_preview}"
        )
    else:
        context_parts.append(
            f"\nTWITTER BUZZ: ❌ No significant Twitter activity found"
        )

    # Overall narrative score
    narrative_score = narrative_result["score"]
    twitter_boost = 2 if twitter_result["found"] and twitter_result["sentiment"] == "bullish" else 0
    twitter_penalty = -2 if twitter_result["found"] and twitter_result["sentiment"] == "bearish" else 0
    total_narrative_score = min(narrative_score + twitter_boost + twitter_penalty, 10)

    context_parts.append(
        f"\nOVERALL NARRATIVE SCORE: {total_narrative_score}/10\n"
        f"(Higher = stronger narrative alignment)"
    )

    # 3. DexScreener top100 check
    if token_mint:
        dex_tokens = await get_dexscreener_top100()
        dex_hit = next((t for t in dex_tokens if t["mint"].lower() == token_mint.lower()), None)
        if dex_hit:
            context_parts.append(
                f"\nDEXSCREENER: ✅ Token masuk top 100 DexScreener!"
                f"\nBoost: ${dex_hit['boost']} | 24h: {dex_hit['price_change_24h']:.1f}%"
                f"\n{dex_hit['description']}"
            )
        else:
            context_parts.append("\nDEXSCREENER: ❌ Tidak masuk top 100 DexScreener")

    # 4. Birdeye trending check
    if token_mint:
        birdeye_tokens = await get_birdeye_trending(BIRDEYE_API_KEY)
        birdeye_hit = next((t for t in birdeye_tokens if t["mint"].lower() == token_mint.lower()), None)
        if birdeye_hit:
            context_parts.append(
                f"\nBIRDEYE TRENDING: ✅ Masuk Birdeye top trending!"
                f"\nRank: #{birdeye_hit['rank']} | 24h: +{birdeye_hit['price_change_24h']:.1f}%"
            )
        else:
            context_parts.append("\nBIRDEYE TRENDING: ❌ Tidak ada di top 20 Birdeye")

    return '\n'.join(context_parts)


if __name__ == "__main__":
    # Test
    async def test():
        print("Testing narrative system...\n")

        # Test narrative match
        test_tokens = [
            ("AI Agent Bot", "AIBOT"),
            ("Trump Pump", "TRUMP"),
            ("Random Token", "RAND"),
            ("Pepe Solana", "PEPE"),
        ]

        for name, symbol in test_tokens:
            print(f"\n{'='*50}")
            print(f"Token: {name} (${symbol})")
            context = await get_full_narrative_context(name, symbol)
            print(context)

    asyncio.run(test())
