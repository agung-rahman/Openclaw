import os, time, sys, requests
from dotenv import load_dotenv
from web3 import Web3
from loguru import logger

load_dotenv()
logger.remove()
logger.add("logs/sniper.log", rotation="10 MB")
logger.add(sys.stdout, colorize=True,
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")

RPC_URL        = os.getenv("TEMPO_RPC_URL")
CHAIN_ID       = int(os.getenv("TEMPO_CHAIN_ID"))
PRIVATE_KEY    = os.getenv("PRIVATE_KEY")
WALLET         = Web3.to_checksum_address(os.getenv("WALLET_ADDRESS"))
TIMECOIN       = Web3.to_checksum_address(os.getenv("TIMECOIN_CA"))
PATH_USD       = Web3.to_checksum_address(os.getenv("PATH_USD"))
DEX            = Web3.to_checksum_address(os.getenv("DEX_ADDRESS"))
BUY_AMOUNT_USD = float(os.getenv("BUY_AMOUNT_USD", "5.0"))
SLIPPAGE       = float(os.getenv("SLIPPAGE_PERCENT", "5.0")) / 100
POLL_INTERVAL  = int(os.getenv("POLL_INTERVAL_SEC", "3"))
DRY_RUN        = os.getenv("DRY_RUN", "true").lower() == "true"
TG_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")
PNL_INTERVAL   = int(os.getenv("PNL_INTERVAL_SEC", "60"))

w3 = Web3(Web3.HTTPProvider(RPC_URL))
assert w3.is_connected(), "Gagal connect ke Tempo RPC!"
logger.success(f"Connected ke Tempo | Chain ID: {w3.eth.chain_id}")

DEX_ABI = [
    {"name":"quoteSwapExactAmountIn","type":"function","stateMutability":"view",
     "inputs":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"amountIn","type":"uint128"}],
     "outputs":[{"name":"amountOut","type":"uint128"}]},
    {"name":"swapExactAmountIn","type":"function","stateMutability":"nonpayable",
     "inputs":[{"name":"tokenIn","type":"address"},{"name":"tokenOut","type":"address"},{"name":"amountIn","type":"uint128"},{"name":"minAmountOut","type":"uint128"}],
     "outputs":[{"name":"amountOut","type":"uint128"}]}
]
ERC20_ABI = [
    {"name":"approve","type":"function","stateMutability":"nonpayable",
     "inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "outputs":[{"name":"","type":"bool"}]},
    {"name":"balanceOf","type":"function","stateMutability":"view",
     "inputs":[{"name":"account","type":"address"}],
     "outputs":[{"name":"","type":"uint256"}]}
]

dex     = w3.eth.contract(address=DEX, abi=DEX_ABI)
pathusd = w3.eth.contract(address=PATH_USD, abi=ERC20_ABI)
timecoin_contract = w3.eth.contract(address=TIMECOIN, abi=ERC20_ABI)

# ─── Telegram ──────────────────────────────────────────────────────────────
def tg(msg: str):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Telegram error: {e}")

# ─── Helpers ───────────────────────────────────────────────────────────────
def check_liquidity():
    try:
        out = dex.functions.quoteSwapExactAmountIn(
            PATH_USD, TIMECOIN, int(0.01 * 10**6)).call()
        return out > 0
    except:
        return False

def get_current_price_usd() -> float:
    """Harga 1 TIMECOIN dalam USD saat ini."""
    try:
        one_token = 10**6
        cost = dex.functions.quoteSwapExactAmountIn(
            TIMECOIN, PATH_USD, one_token).call()
        return cost / 10**6
    except:
        return 0.0

def get_quote():
    amt_in  = int(BUY_AMOUNT_USD * 10**6)
    out     = dex.functions.quoteSwapExactAmountIn(PATH_USD, TIMECOIN, amt_in).call()
    min_out = int(out * (1 - SLIPPAGE))
    price   = BUY_AMOUNT_USD / (out / 10**6) if out > 0 else 0
    logger.info(f"Quote: \${BUY_AMOUNT_USD} -> {out/10**6:.4f} TIMECOIN @ \${price:.6f}/token")
    return amt_in, min_out, out, price

def execute_snipe(amt_in, min_out):
    acct  = w3.eth.account.from_key(PRIVATE_KEY)
    nonce = w3.eth.get_transaction_count(WALLET)

    logger.info("Step 1: Approving pathUSD...")
    tx = pathusd.functions.approve(DEX, amt_in).build_transaction(
        {"chainId":CHAIN_ID,"from":WALLET,"nonce":nonce,
         "gas":100_000,"gasPrice":w3.eth.gas_price})
    r = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction), timeout=60)
    if r.status != 1:
        logger.error("Approve FAILED!")
        return None
    logger.success("Approve OK!")

    logger.info("Step 2: Swapping...")
    nonce += 1
    tx2 = dex.functions.swapExactAmountIn(
        PATH_USD, TIMECOIN, amt_in, min_out).build_transaction(
        {"chainId":CHAIN_ID,"from":WALLET,"nonce":nonce,
         "gas":200_000,"gasPrice":w3.eth.gas_price})
    r2 = w3.eth.wait_for_transaction_receipt(
        w3.eth.send_raw_transaction(acct.sign_transaction(tx2).raw_transaction), timeout=60)
    if r2.status != 1:
        logger.error("Swap FAILED!")
        return None

    h = r2.transactionHash.hex()
    logger.success(f"SNIPE BERHASIL! https://explore.tempo.xyz/tx/{h}")
    return h

# ─── PnL Loop ──────────────────────────────────────────────────────────────
def pnl_loop(buy_price: float, tokens_received: float, spent_usd: float):
    logger.info(f"PnL monitor aktif | beli @ \${buy_price:.6f} | {tokens_received:.4f} TIMECOIN")
    tg(
        f"📊 <b>PnL Monitor Aktif</b>\n"
        f"Beli: {tokens_received:.4f} TIMECOIN\n"
        f"Harga beli: <code>\${buy_price:.6f}</code>\n"
        f"Modal: <code>\${spent_usd:.2f}</code>\n"
        f"Update tiap {PNL_INTERVAL}s"
    )
    while True:
        time.sleep(PNL_INTERVAL)
        try:
            current_price = get_current_price_usd()
            if current_price <= 0:
                logger.warning("Gagal ambil harga saat ini")
                continue

            current_value = tokens_received * current_price
            pnl_usd       = current_value - spent_usd
            pnl_pct       = (pnl_usd / spent_usd) * 100
            multiplier    = current_value / spent_usd

            emoji = "🟢" if pnl_usd >= 0 else "🔴"
            direction = "▲" if pnl_usd >= 0 else "▼"

            msg = (
                f"{emoji} <b>PnL Update — TIMECOIN</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Harga beli : <code>\${buy_price:.6f}</code>\n"
                f"Harga skrg : <code>\${current_price:.6f}</code>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Modal      : <code>\${spent_usd:.2f}</code>\n"
                f"Nilai skrg : <code>\${current_value:.2f}</code>\n"
                f"PnL        : <code>{direction}\${abs(pnl_usd):.2f} ({pnl_pct:+.1f}%)</code>\n"
                f"Multiplier : <code>{multiplier:.2f}x</code>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Hold: {tokens_received:.4f} TIMECOIN"
            )

            logger.info(f"PnL: {direction}\${abs(pnl_usd):.2f} ({pnl_pct:+.1f}%) | {multiplier:.2f}x")
            tg(msg)

        except Exception as e:
            logger.error(f"PnL error: {e}")

# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 50)
    logger.info(f"TIMECOIN SNIPER | \${BUY_AMOUNT_USD} | Slippage: {SLIPPAGE*100}% | DRY_RUN: {DRY_RUN}")
    logger.info("=" * 50)

    if DRY_RUN:
        logger.warning("DRY RUN MODE — ubah DRY_RUN=false di .env untuk eksekusi")

    bal = pathusd.functions.balanceOf(WALLET).call() / 10**6
    logger.info(f"Balance: \${bal:.4f} pathUSD")
    if bal < BUY_AMOUNT_USD:
        logger.error(f"Balance kurang! Punya \${bal:.2f}, butuh \${BUY_AMOUNT_USD}")
        sys.exit(1)

    tg(
        f"🤖 <b>Timecoin Sniper Aktif</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Target  : <code>TIMECOIN</code>\n"
        f"Modal   : <code>\${BUY_AMOUNT_USD}</code>\n"
        f"Balance : <code>\${bal:.2f} pathUSD</code>\n"
        f"Mode    : {🔵
