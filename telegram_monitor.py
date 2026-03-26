from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
import asyncio
import httpx
import os

API_ID = 39237948  # ganti
API_HASH = '1e2b86fa6dcc13d5f07ca86feecb2b4c'  # ganti

CHANNELS = [
    'AirdropAnalyst',
    'airdropfind',
    'airdropcloudJP',
    'AirdropUmbrellaX',
    'airdropdaydua',
    'PegazusEcosystem',
    'AIRDROPSATSETT',
    'IndonesiaAirdropzReborn',
]

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = '5664251521'  # ganti chat id pribadi kamu

client = TelegramClient('degen_session', API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event):
    chat = await event.get_chat()
    channel_name = chat.title
    message = event.message.message or ''
    
    print(f"[{channel_name}] {message[:100]}")
    
    caption = f"🚨 [{channel_name}]\n\n{message}"
    
    async with httpx.AsyncClient() as http:
        # Kalau ada foto
        if event.message.media and isinstance(event.message.media, MessageMediaPhoto):
            # Download foto
            path = await client.download_media(event.message, '/tmp/airdrop_img.jpg')
            
            # Kirim foto ke Telegram
            with open(path, 'rb') as f:
                await http.post(
                    f'https://api.telegram.org/bot{os.getenv("TELEGRAM_BOT_TOKEN")}/sendPhoto',
                    data={'chat_id': CHAT_ID, 'caption': caption},
                    files={'photo': f}
                )
            os.remove(path)
        
        # Kalau cuma text
        else:
            await http.post(
                f'https://api.telegram.org/bot{os.getenv("TELEGRAM_BOT_TOKEN")}/sendMessage',
                json={'chat_id': CHAT_ID, 'text': caption}
            )

async def main():
    await client.start()
    print("Monitoring channels...")
    await client.run_until_disconnected()

asyncio.run(main())
