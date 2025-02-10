import warnings
from cryptography.utils import CryptographyDeprecationWarning
warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from pymongo import MongoClient
from datetime import datetime
import source.config as config
from source.bot_tools import *

# Configuration
MONGODB_URI = config.MONGODB_URI
BOT_TOKEN = config.BOT_TOKEN
HELIUS_KEY = config.HELIUS_KEY
HELIUS_WEBHOOK_ID = config.HELIUS_WEBHOOK_ID

# Database setup
client = MongoClient(MONGODB_URI)
db = client.sol_wallets
wallets_collection = db.wallets_test

# Conversation states
ADDING_WALLET, DELETING_WALLET = range(2)

# Configure logging
logging.basicConfig(
    filename='bot.log',
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def welcome_message() -> str:
    return (
        "🤖 Ahoy there, Solana Wallet Wrangler! Welcome to Solana Wallet Xray Bot! 🤖\n\n"
        "I'm your trusty sidekick, here to help you juggle those wallets and keep an eye on transactions.\n"
        "Once you've added your wallets, you can sit back and relax, as I'll swoop in with a snappy notification and a brief transaction summary every time your wallet makes a move on Solana. 🚀\n"
        "Have a blast using the bot! 😄\n\n"
        "Ready to rumble? Use the commands below and follow the prompts:"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("✨ Add", callback_data="addWallet"),
            InlineKeyboardButton("🗑️ Delete", callback_data="deleteWallet"),
            InlineKeyboardButton("👀 Show", callback_data="showWallets"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(welcome_message(), reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(
            "The world is your oyster! Choose an action and let's embark on this thrilling journey! 🌍",
            reply_markup=reply_markup
        )

def create_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ Add", callback_data="addWallet"),
            InlineKeyboardButton("🗑️ Delete", callback_data="deleteWallet"),
            InlineKeyboardButton("👀 Show", callback_data="showWallets"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back")]
    ])

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if query.data == "addWallet":
        await add_wallet_start(update, context)
    elif query.data == "deleteWallet":
        await delete_wallet_start(update, context)
    elif query.data == "showWallets":
        await show_wallets(update, context)
    elif query.data == "back":
        await back(update, context)

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("No worries! Let's head back to the main menu for more fun! 🎉")
    await start(update, context)
    return ConversationHandler.END

async def add_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back")]]
    await update.callback_query.edit_message_text(
        "Alright, ready to expand your wallet empire? Send me the wallet address you'd like to add! 🎩",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADDING_WALLET

async def add_wallet_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    wallet_address = update.message.text
    user_id = update.effective_user.id
    keyboard = create_keyboard()

    if not wallet_address:
        await update.message.reply_text("Oops! Looks like you forgot the wallet address. Send it over so we can get things rolling! 📨")
        return ADDING_WALLET

    if not is_solana_wallet_address(wallet_address):
        await update.message.reply_text("Uh-oh! That Solana wallet address seems a bit fishy. Double-check it and send a valid one, please! 🕵️‍♂️")
        return ADDING_WALLET

    check_res, check_num_tx = check_wallet_transactions(wallet_address)
    if not check_res:
        await update.message.reply_text(f"Whoa, slow down Speedy Gonzales! 🏎️ We can only handle wallets with under 50 transactions per day. Your wallet's at {round(check_num_tx, 1)}. Let's pick another, shall we? 😉")
        return ADDING_WALLET

    if wallet_count_for_user(user_id) >= 5:
        await update.message.reply_text("Oops! You've reached the wallet limit! It seems you're quite the collector, but we can only handle up to 5 wallets per user. Time to make some tough choices! 😄")
        return ADDING_WALLET

    existing_wallet = wallets_collection.find_one({
        "user_id": str(user_id),
        "address": wallet_address,
        "status": "active"
    })

    if existing_wallet:
        await update.message.reply_text("Hey there, déjà vu! You've already added this wallet. Time for a different action, perhaps? 🔄", reply_markup=keyboard)
        return ConversationHandler.END

    success, webhook_id, addresses = get_webhook(HELIUS_WEBHOOK_ID)
    r_success = add_webhook(user_id, wallet_address, webhook_id, addresses)

    if success and r_success:
        wallets_collection.insert_one({
            "user_id": str(user_id),
            "address": wallet_address,
            "datetime": datetime.now(),
            "status": 'active',
        })
        await update.message.reply_text("Huzzah! Your wallet has been added with a flourish! 🎉 Now you can sit back, relax, and enjoy your Solana experience as I keep an eye on your transactions. What's your next grand plan?", reply_markup=keyboard)
    else:
        await update.message.reply_text("Bummer! We hit a snag while saving your wallet. Let's give it another whirl, shall we? 🔄", reply_markup=keyboard)

    return ConversationHandler.END

async def delete_wallet_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back")]]
    await update.callback_query.edit_message_text(
        "Time for some spring cleaning? Send the wallet address you'd like to sweep away! 🧹",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return DELETING_WALLET

async def delete_wallet_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    wallet_address = update.message.text
    user_id = update.effective_user.id
    keyboard = create_keyboard()

    wallets_exist = wallets_collection.find({"address": wallet_address, "status": "active"})
    r_success = True

    if len(list(wallets_exist.clone())) == 1:
        logger.info('Deleting unique address')
        success, webhook_id, addresses = get_webhook(HELIUS_WEBHOOK_ID)
        r_success = delete_webhook(user_id, wallet_address, webhook_id, addresses)

    if r_success:
        result = wallets_collection.delete_one({"user_id": str(user_id), "address": wallet_address})
        if result.deleted_count == 0:
            await update.message.reply_text("Hmm, that wallet's either missing or not yours. Let's try something else, okay? 🕵️‍♀️", reply_markup=keyboard)
        else:
            await update.message.reply_text("Poof! Your wallet has vanished into thin air! Now, what other adventures await? ✨", reply_markup=keyboard)
    else:
        await update.message.reply_text("Yikes, we couldn't delete the wallet. Don't worry, we'll get it next time! Try again, please. 🔄", reply_markup=keyboard)

    return ConversationHandler.END

async def show_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    keyboard = create_keyboard()

    user_wallets = list(wallets_collection.find({
        "user_id": str(user_id),
        "status": "active"
    }))

    if not user_wallets:
        await update.callback_query.edit_message_text(
            "Whoa, no wallets here! Let's add some, or pick another action to make things exciting! 🎢",
            reply_markup=keyboard
        )
    else:
        wallet_list = "\n".join([wallet["address"] for wallet in user_wallets])
        await update.callback_query.edit_message_text(
            f"Feast your eyes upon your wallet collection! 🎩\n\n{wallet_list}\n\nNow, what's your next move, my friend? 🤔",
            reply_markup=keyboard
        )

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback)],
        states={
            ADDING_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_wallet_finish)],
            DELETING_WALLET: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_wallet_finish)],
        },
        fallbacks=[CallbackQueryHandler(back, pattern='^back$')],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
