"""
ai_filter.py — AI decision layer untuk degen_hunter
Tanya Claude via OpenRouter sebelum eksekusi buy
"""

import aiohttp
import json
import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = "anthropic/claude-sonnet-4-5"

SYSTEM_PROMPT = """Kamu adalah AI trading filter untuk Solana memecoin copytrading.
Tugasmu: analisa data token dan putuskan BUY atau SKIP.

Jawab HANYA dalam format JSON ini, tidak ada teks lain:
{
  "decision": "BUY" atau "SKIP",
  "confidence": 1-10,
  "reason": "alasan singkat max 1 kalimat"
}

Kriteria BUY yang bagus:
- Volume spike tinggi (>3x) dengan price change moderat (<20%)
- Buy ratio tinggi (>60%) menandakan akumulasi
- Liquidity cukup (>5000 USD) untuk exit yang aman
- Market cap kecil-menengah ($5K-$500K) = masih ada ruang naik
- Token baru (<48 jam) = early entry
- Wallet source terpercaya (whale, top trader)

Kriteria SKIP:
- Price sudah pump besar (>30% dalam 1 jam) = terlambat masuk
- Liquidity sangat rendah (<3000) = susah exit
- Buy ratio rendah (<45%) = distribusi
- Token terlalu tua (>7 hari) = sudah lewat momentum
- Wallet source tidak dikenal atau kosong
- Tanda-tanda rug: liquidity sangat kecil, holder terkonsentrasi
"""

async def ai_should_buy(token_data: dict, wallet_source: str = "") -> dict:
    if not OPENROUTER_API_KEY:
        return {"decision": "BUY", "confidence": 5, "reason": "OpenRouter key tidak ada, fallback ke logic lama"}

    prompt = f"""Analisa token Solana ini dan putuskan BUY atau SKIP:

Token: {token_data.get('symbol')} ({token_data.get('name')})
Signal: {token_data.get('signal')}
Wallet source: {wallet_source or 'tidak diketahui'}

Data market:
- Volume spike: {token_data.get('volume_spike')}x vs rata-rata
- Price change 1h: {token_data.get('price_change_1h')}%
- Price change 6h: {token_data.get('price_change_6h')}%
- Buy ratio 1h: {token_data.get('buy_ratio_1h')}%
- Transaksi 1h: {token_data.get('txns_buys_1h')} buy / {token_data.get('txns_sells_1h')} sell
- Liquidity: ${token_data.get('liquidity'):,.0f}
- Market cap: ${token_data.get('market_cap'):,.0f}
- Umur token: {token_data.get('age_hours')} jam
- DEX: {token_data.get('dex')}

Rugcheck score: {token_data.get('rugcheck_score', 'tidak ada')}
Rugcheck verdict: {token_data.get('rugcheck_verdict', 'tidak ada')}"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/degen-hunter",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 150,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"[AI] OpenRouter error {resp.status}: {text[:200]}")
                    return {"decision": "BUY", "confidence": 5, "reason": f"API error {resp.status}, fallback"}

                data = await resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                if "```" in content:
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]

                result = json.loads(content)

                if result.get("decision") not in ("BUY", "SKIP"):
                    result["decision"] = "SKIP"

                print(f"[AI] {token_data.get('symbol')}: {result['decision']} (conf={result.get('confidence')}/10) — {result.get('reason')}")
                return result

    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}")
        return {"decision": "SKIP", "confidence": 1, "reason": "gagal parse response AI"}
    except aiohttp.ClientTimeout:
        print(f"[AI] Timeout untuk {token_data.get('symbol')}, fallback SKIP")
        return {"decision": "SKIP", "confidence": 1, "reason": "AI timeout"}
    except Exception as e:
        print(f"[AI] Error: {e}")
        return {"decision": "BUY", "confidence": 5, "reason": f"error: {e}, fallback"}
