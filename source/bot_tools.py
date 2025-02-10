from pymongo import MongoClient
import requests
from datetime import datetime
import source.config as config
import logging
from typing import Tuple, List, Optional

# Set up logging
logging.basicConfig(
    filename='bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
MONGODB_URI = config.MONGODB_URI
BOT_TOKEN = config.BOT_TOKEN
HELIUS_KEY = config.HELIUS_KEY
HELIUS_WEBHOOK_URL = config.HELIUS_WEBHOOK_URL
HELIUS_WEBHOOK_ID = config.HELIUS_WEBHOOK_ID

# Database setup
client = MongoClient(MONGODB_URI)
db = client.sol_wallets
wallets_collection = db.wallets_test

def get_webhook(webhook_id: str) -> Tuple[bool, Optional[str], Optional[List[str]]]:
    """
    Fetches the current webhook configuration from Helius.
    Args:
        webhook_id (str): The ID of the webhook to fetch.
    Returns:
        Tuple[bool, Optional[str], Optional[List[str]]]: A tuple containing:
            - Success status (bool)
            - Webhook ID (str or None)
            - List of account addresses (List[str] or None)
    """
    try:
        url = f"https://api.helius.xyz/v0/webhooks/{webhook_id}?api-key={HELIUS_KEY}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return True, data['webhookID'], data['accountAddresses']
    except Exception as e:
        logger.error(f"Error getting webhook: {str(e)}", exc_info=True)
        return False, None, None

def add_webhook(user_id: int, user_wallet: str, webhook_id: str, addresses: List[str]) -> bool:
    """
    Adds a wallet address to the Helius webhook.
    Args:
        user_id (int): The ID of the user adding the wallet.
        user_wallet (str): The wallet address to add.
        webhook_id (str): The ID of the webhook to update.
        addresses (List[str]): The current list of addresses in the webhook.
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    if user_wallet in addresses:
        logger.info('Wallet already exists in webhook, returning true')
        return True

    addresses.append(user_wallet)
    data = {
        "webhookURL": HELIUS_WEBHOOK_URL,
        "accountAddresses": addresses,
        "transactionTypes": ["Any"],
        "webhookType": "enhanced",
    }

    try:
        url = f"https://api.helius.xyz/v0/webhooks/{webhook_id}?api-key={HELIUS_KEY}"
        r = requests.put(url, json=data, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error adding wallet to webhook: {str(e)}", exc_info=True)
        return False

def delete_webhook(user_id: int, user_wallet: str, webhook_id: str, addresses: List[str]) -> bool:
    """
    Removes a wallet address from the Helius webhook.
    Args:
        user_id (int): The ID of the user deleting the wallet.
        user_wallet (str): The wallet address to remove.
        webhook_id (str): The ID of the webhook to update.
        addresses (List[str]): The current list of addresses in the webhook.
    Returns:
        bool: True if the update was successful, False otherwise.
    """
    if user_wallet not in addresses:
        logger.info('Wallet not found in webhook, returning true')
        return True

    addresses.remove(user_wallet)
    data = {
        "webhookURL": HELIUS_WEBHOOK_URL,
        "accountAddresses": addresses,
        "transactionTypes": ["Any"],
        "webhookType": "enhanced",
    }

    try:
        url = f"https://api.helius.xyz/v0/webhooks/{webhook_id}?api-key={HELIUS_KEY}"
        r = requests.put(url, json=data, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Error deleting wallet from webhook: {str(e)}", exc_info=True)
        return False

def is_solana_wallet_address(address: str) -> bool:
    """
    Validates a Solana wallet address.
    Args:
        address (str): The address to validate.
    Returns:
        bool: True if the address is valid, False otherwise.
    """
    base58_chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    return len(address) == 44 and all(char in base58_chars for char in address)

def wallet_count_for_user(user_id: int) -> int:
    """
    Counts the number of active wallets for a user.
    Args:
        user_id (int): The ID of the user.
    Returns:
        int: The number of active wallets.
    """
    return wallets_collection.count_documents({"user_id": str(user_id), "status": "active"})

def check_wallet_transactions(wallet: str) -> Tuple[bool, float]:
    """
    Checks the transaction rate of a wallet.
    Args:
        wallet (str): The wallet address to check.
    Returns:
        Tuple[bool, float]: A tuple containing:
            - True if the wallet is valid (transaction rate <= 50/day), False otherwise.
            - The calculated transaction rate per day.
    """
    try:
        url = f'https://api.helius.xyz/v0/addresses/{wallet}/raw-transactions?api-key={HELIUS_KEY}'
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        transactions = r.json()

        if len(transactions) < 10:
            return True, 0

        latest_tx_time = datetime.utcfromtimestamp(transactions[-1]['blockTime'])
        time_diff = (datetime.utcnow() - latest_tx_time).total_seconds()

        if time_diff == 0:
            return True, 0

        daily_rate = len(transactions) / time_diff * 86400
        return daily_rate <= 50, round(daily_rate, 1)

    except Exception as e:
        logger.error(f"Error checking wallet transactions: {str(e)}", exc_info=True)
        return True, 0
