import warnings
from cryptography.utils import CryptographyDeprecationWarning
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

from flask import Flask, request
from telegram.ext import Application
from telegram.constants import ParseMode
import pytz  # Import pytz for timezone handling

from PIL import Image
from io import BytesIO
import re
import source.config as config
import logging
from datetime import datetime
import requests
import asyncio

from pymongo import MongoClient

# Configuration
MONGODB_URI = config.MONGODB_URI
BOT_TOKEN = config.BOT_TOKEN
HELIUS_KEY = config.HELIUS_KEY

# Database setup
client = MongoClient(MONGODB_URI)
db = client.sol_wallets
wallets_collection = db.wallets

# Set up logging
logging.basicConfig(
    filename='wallet.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Telegram application with explicit timezone
application = Application.builder().token(BOT_TOKEN).arbitrary_callback_data(True).build()

# Explicitly configure the job queue's timezone
application.job_queue.scheduler.configure(timezone=pytz.UTC)

async def send_message_to_user(user_id, message):
    await application.bot.send_message(
        chat_id=user_id,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )

async def send_image_to_user(user_id, message, image_url):
    image_bytes = get_image(image_url)
    await application.bot.send_photo(
        chat_id=user_id,
        photo=image_bytes,
        caption=message,
        parse_mode=ParseMode.MARKDOWN
    )

def get_image(url):
    response = requests.get(url).content
    image = Image.open(BytesIO(response))
    image = image.convert('RGB')
    max_size = (800, 800)
    
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:
        resample = Image.ANTIALIAS
        
    image.thumbnail(max_size, resample)
    image_bytes = BytesIO()
    image.save(image_bytes, 'JPEG', quality=85)
    image_bytes.seek(0)
    return image_bytes

def format_wallet_address(match_obj):
    wallet_address = match_obj.group(0)
    return wallet_address[:4] + "..." + wallet_address[-4:]

def get_compressed_image(asset_id):
    url = f'https://rpc.helius.xyz/?api-key={HELIUS_KEY}'
    r_data = {
        "jsonrpc": "2.0",
        "id": "my-id",
        "method": "getAsset",
        "params": [asset_id]
    }
    r = requests.post(url, json=r_data)
    url_meta = r.json()['result']['content']['json_uri']
    r = requests.get(url=url_meta)
    return r.json()['image']

def check_image(data):
    token_mint = ''
    for token in data[0]['tokenTransfers']:
        if 'NonFungible' in token['tokenStandard']:
            token_mint = token['mint']

    if len(token_mint) > 0:
        url = f"https://api.helius.xyz/v0/token-metadata?api-key={HELIUS_KEY}"
        nft_addresses = [token_mint]
        r_data = {
            "mintAccounts": nft_addresses,
            "includeOffChain": True,
            "disableCache": False,
        }

        r = requests.post(url=url, json=r_data)
        j = r.json()
        return j[0]['offChainMetadata']['metadata'].get('image', '')
    else:
        if 'compressed' in data[0]['events']:
            if 'assetId' in data[0]['events']['compressed'][0]:
                asset_id = data[0]['events']['compressed'][0]['assetId']
                try:
                    return get_compressed_image(asset_id)
                except Exception:
                    return ''
        return ''

def create_message(data):
    tx_type = data[0]['type'].replace("_", " ")
    tx = data[0]['signature']
    source = data[0]['source']
    description = data[0]['description']

    accounts = []
    for inst in data[0]["instructions"]:
        accounts += inst["accounts"]
        
    if len(data[0]['tokenTransfers']) > 0:
        for token in data[0]['tokenTransfers']:
            accounts.extend([token['fromUserAccount'], token['toUserAccount']])
        accounts = list(set(accounts))

    image = check_image(data)
    
    found_docs = list(wallets_collection.find(
        {"address": {"$in": accounts}, "status": "active"}
    ))
    found_users = {i['user_id'] for i in found_docs}
    
    messages = []
    for user in found_users:
        message = f'*{tx_type}*' + (f' on {source}' if source != "SYSTEM_PROGRAM" else '')
        if description:
            message += f'\n\n{description}'

            user_wallets = [i['address'] for i in found_docs if i['user_id'] == user]
            for wallet in user_wallets:
                if wallet in message:
                    formatted = f'*YOUR WALLET* ({wallet[:4]}...{wallet[-4:]})'
                    message = message.replace(wallet, formatted)

        formatted_text = re.sub(r'[A-Za-z0-9]{32,44}', format_wallet_address, message)
        formatted_text += f'\n[XRAY](https://xray.helius.xyz/tx/{tx}) | [Solscan](https://solscan.io/tx/{tx})'
        formatted_text = formatted_text.replace("#", "").replace("_", " ")
        messages.append({'user': user, 'text': formatted_text, 'image': image})
    return messages

app = Flask(__name__)

@app.route('/wallet', methods=['POST'])
def handle_webhook():
    data = request.json
    messages = create_message(data)

    for message in messages:
        db_entry = {
            "user": message['user'],
            "message": message['text'],
            "datetime": datetime.now()
        }
        db.messages.insert_one(db_entry)
        logger.info(message)

        try:
            if message['image']:
                asyncio.run(send_image_to_user(message['user'], message['text'], message['image']))
            else:
                asyncio.run(send_message_to_user(message['user'], message['text']))
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            asyncio.run(send_message_to_user(message['user'], message['text']))

    logger.info('ok event')
    return 'OK'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5002)
