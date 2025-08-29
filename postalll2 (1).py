import logging
import re
import json
import asyncio
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from telegram.constants import ParseMode, ChatType

# --- CONFIGURATION & SETUP ---
# Replace with your bot's token from BotFather
BOT_TOKEN = "7247516860:AAGqJJMC1wexY-PKefKC2ZvMPVpu8uj9kfI"
# Replace with your Telegram User ID (get it from @userinfobot)
OWNER_ID = 7507183871

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define ConversationHandler states
(
    SET_CHANNEL,
    POST_TYPE,
    TEXT_CONTENT,
    PHOTO_CONTENT,
    ADD_BUTTONS,
    BUTTON_TEXT,
    BUTTON_URL,
    CONFIRM_POST,
    BROADCAST_TYPE,
    BROADCAST_CONTENT,
    BROADCAST_BUTTONS_INPUT,
    BROADCAST_CONFIRM,
    USER_MGMT_PROMPT,
    FORCE_CHANNEL_PROMPT,
) = range(14)

# --- GLOBAL DATA STORES (PERSISTENT) ---
user_channels: Dict[int, Union[str, int]] = {}
admin_ids: set = set()
banned_users: set = set()
forced_channels: set = set()
user_stats: Dict[int, Dict[str, Any]] = {}
MAINTENANCE_MODE = False
CONTACT_OWNER_URL = "https://t.me/patelkrish_99"
BUY_CODE_URL = "https://t.me/patelkrish_99"


# --- UTILITY FUNCTIONS FOR DATA PERSISTENCE ---
def load_data():
    """Loads bot data from a JSON file."""
    global admin_ids, banned_users, forced_channels, user_channels, user_stats, MAINTENANCE_MODE
    try:
        with open('bot_data.json', 'r') as f:
            data = json.load(f)
            # Convert lists to sets for proper functionality
            admin_ids = set(data.get('admin_ids', []))
            banned_users = set(data.get('banned_users', []))
            forced_channels = set(data.get('forced_channels', []))
            # Keys in JSON must be strings, so we convert them back to integers
            user_channels = {int(k): v for k, v in data.get('user_channels', {}).items()}
            user_stats_raw = data.get('user_stats', {})
            user_stats = {
                int(k): {
                    'username': v.get('username'),
                    'joined_at': datetime.fromisoformat(v.get('joined_at')),
                    'is_bot_blocked': v.get('is_bot_blocked')
                }
                for k, v in user_stats_raw.items()
            }
            MAINTENANCE_MODE = data.get('maintenance_mode', False)
        logger.info("Data loaded successfully from bot_data.json.")
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("bot_data.json not found or corrupted. Starting with an empty database.")
        admin_ids.add(OWNER_ID)

def save_data():
    """Saves bot data to a JSON file."""
    # Convert datetime objects to ISO format strings for JSON serialization
    user_stats_for_save = {
        str(k): {
            'username': v.get('username'),
            'joined_at': v.get('joined_at').isoformat(),
            'is_bot_blocked': v.get('is_bot_blocked')
        }
        for k, v in user_stats.items()
    }
    
    data = {
        'admin_ids': list(admin_ids),
        'banned_users': list(banned_users),
        'forced_channels': list(forced_channels),
        'user_channels': {str(k): v for k, v in user_channels.items()},
        'user_stats': user_stats_for_save,
        'maintenance_mode': MAINTENANCE_MODE
    }
    with open('bot_data.json', 'w') as f:
        json.dump(data, f, indent=4)
    logger.info("Data saved successfully to bot_data.json.")


# --- UTILITY FUNCTIONS ---
def get_user_role(user_id: int) -> str:
    """Determine the user's role based on their ID."""
    if user_id == OWNER_ID:
        return "owner"
    elif user_id in admin_ids:
        return "admin"
    else:
        return "user"

async def _build_join_channels_message(context: ContextTypes.DEFAULT_TYPE, channels: List[Union[str, int]]) -> tuple[str, InlineKeyboardMarkup]:
    """Builds a single message with buttons for all channels a user needs to join."""
    text = "⚠️ <b>Please join the following channels to use this bot:</b>"
    keyboard = []
    
    for channel in channels:
        try:
            invite_link = await context.bot.export_chat_invite_link(chat_id=channel)
            button_text = "Join Private Channel"
            keyboard.append(InlineKeyboardButton(button_text, url=invite_link))
        except Exception:
            if isinstance(channel, int):
                continue
            
            button_text = f"Join {channel}"
            keyboard.append(InlineKeyboardButton(button_text, url=f"https://t.me/{channel.strip('@')}"))

    return text, InlineKeyboardMarkup.from_row(keyboard)

async def check_user_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check for maintenance mode, banned status, and forced channel joins."""
    user_id = update.effective_user.id
    user_role = get_user_role(user_id)
    
    if MAINTENANCE_MODE and user_role not in ["owner", "admin"]:
        await update.effective_message.reply_text("⛔️ The bot is currently in maintenance mode. Please try again later.")
        return False
    
    if user_id in banned_users:
        await update.effective_message.reply_text("🚫 You have been banned from using this bot.")
        return False

    if forced_channels and user_role == "user":
        missing_channels = []
        for channel in forced_channels:
            try:
                chat_member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
                if chat_member.status in ["left", "kicked"]:
                    missing_channels.append(channel)
            except Exception as e:
                logger.error(f"Failed to check membership for {channel}: {e}")
                missing_channels.append(channel)
        
        if missing_channels:
            text, reply_markup = await _build_join_channels_message(context, missing_channels)
            await update.effective_message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            return False
    
    return True

# --- UI & MENU FUNCTIONS ---
def get_main_menu_keyboard(role: str) -> InlineKeyboardMarkup:
    """Generates the main menu inline keyboard based on user role."""
    keyboard = []
    
    keyboard.append([InlineKeyboardButton("📝 Create Post", callback_data="create_post")])
    keyboard.append([InlineKeyboardButton("⚙️ Set Channel", callback_data="set_channel")])
    
    if role in ["admin", "owner"]:
        keyboard.append([InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_menu")])
        keyboard.append([InlineKeyboardButton("👥 User Management", callback_data="user_management_menu")])
    
    if role == "owner":
        keyboard.append([InlineKeyboardButton("👑 Owner Controls", callback_data="owner_controls_menu")])
    
    keyboard.append([
        InlineKeyboardButton("❓ Contact Owner", url=CONTACT_OWNER_URL),
        InlineKeyboardButton("💻 Buy Bot Code", url=BUY_CODE_URL)
    ])
    
    return InlineKeyboardMarkup(keyboard)

def get_user_management_keyboard(role: str) -> InlineKeyboardMarkup:
    """Generates the user management menu for admins and owners."""
    keyboard = []
    if role == "owner":
        keyboard.append([
            InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"),
            InlineKeyboardButton("➖ Remove Admin", callback_data="remove_admin")
        ])
    
    keyboard.append([
        InlineKeyboardButton("🚫 Ban User", callback_data="ban_user"),
        InlineKeyboardButton("✅ Unban User", callback_data="unban_user")
    ])
    
    keyboard.append([
        InlineKeyboardButton("➕ Add Forced Channel", callback_data="add_forced_channel"),
        InlineKeyboardButton("➖ Remove Forced Channel", callback_data="remove_forced_channel")
    ])

    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_owner_controls_keyboard() -> InlineKeyboardMarkup:
    """Generates the owner-specific controls menu."""
    status = "ON" if MAINTENANCE_MODE else "OFF"
    keyboard = [
        [InlineKeyboardButton(f"🛠 Maintenance Mode ({status})", callback_data="toggle_maintenance_mode")],
        [InlineKeyboardButton("📊 Show Statistics", callback_data="show_stats")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends a welcome message and the appropriate menu."""
    user = update.effective_user
    if user.id not in user_stats:
        user_stats[user.id] = {"username": user.username, "joined_at": datetime.now(), "is_bot_blocked": False}
        logger.info(f"New user joined: {user.full_name} ({user.id})")
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"<b>New User Alert!</b>\n\nName: <code>{user.full_name}</code>\nID: <code>{user.id}</code>\nUsername: <code>@{user.username}</code>\nTotal Users: <code>{len(user_stats)}</code>",
            parse_mode=ParseMode.HTML
        )
        save_data()

    user_role = get_user_role(user.id)
    if not await check_user_access(update, context):
        return ConversationHandler.END

    await update.message.reply_text(
        f"Hello, {user.full_name}! 👋\nWelcome to your channel management bot. "
        f"You are a <b>{user_role.upper()}</b>.\n\n"
        "Please use the menu below to get started.",
        reply_markup=get_main_menu_keyboard(user_role),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

async def handle_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles main menu button clicks."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_role = get_user_role(user_id)
    
    if not await check_user_access(update, context):
        return ConversationHandler.END

    if query.data == "main_menu":
        await query.edit_message_text(
            f"Hello, {query.from_user.full_name}! 👋\nWelcome to your channel management bot. "
            f"You are a <b>{user_role.upper()}</b>.\n\n"
            "Please use the menu below to get started.",
            reply_markup=get_main_menu_keyboard(user_role),
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END

    if query.data == "set_channel":
        await query.edit_message_text(
            "Please send your channel's username (e.g., `@mychannel`) or its ID (e.g., `-100123456789`)."
        )
        return SET_CHANNEL

    if query.data == "create_post":
        channel_username = user_channels.get(user_id)
        if not channel_username:
            await query.edit_message_text("❌ Please set your channel first using the 'Set Channel' button.")
            return ConversationHandler.END
        
        keyboard = [
            [
                InlineKeyboardButton("Text Only", callback_data="post_type_text"),
                InlineKeyboardButton("Photo with Caption", callback_data="post_type_photo"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "What kind of post would you like to create?",
            reply_markup=reply_markup
        )
        return POST_TYPE

    if query.data == "broadcast_menu":
        if user_role in ["admin", "owner"]:
            keyboard = [
                [
                    InlineKeyboardButton("📢 To Users", callback_data="broadcast_users"),
                    InlineKeyboardButton("📢 To Channels", callback_data="broadcast_channels")
                ],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                "Please choose your broadcast type:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return BROADCAST_TYPE
        
    if query.data == "user_management_menu":
        if user_role in ["admin", "owner"]:
            await query.edit_message_text(
                "👥 User Management Panel:",
                reply_markup=get_user_management_keyboard(user_role)
            )
            return ConversationHandler.END

    if query.data == "owner_controls_menu":
        if user_role == "owner":
            await query.edit_message_text(
                "👑 Owner Exclusive Panel:",
                reply_markup=get_owner_controls_keyboard()
            )
            return ConversationHandler.END
    
    if query.data == "toggle_maintenance_mode":
        if user_role == "owner":
            global MAINTENANCE_MODE
            MAINTENANCE_MODE = not MAINTENANCE_MODE
            status = "ON" if MAINTENANCE_MODE else "OFF"
            keyboard = get_owner_controls_keyboard()
            await query.edit_message_text(
                f"🛠 Maintenance Mode is now <code>{status}</code>.",
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML
            )
            save_data()
            return ConversationHandler.END

    if query.data == "show_stats":
        if user_role in ["admin", "owner"]:
            total_users = len(user_stats)
            active_users = total_users - len(banned_users)
            banned_count = len(banned_users)
            
            stats_text = (
                f"<b>Bot Statistics</b>\n"
                f"Total Users: <code>{total_users}</code>\n"
                f"Active Users: <code>{active_users}</code>\n"
                f"Banned Users: <code>{banned_count}</code>\n"
                f"Forced Channels: <code>{len(forced_channels)}</code>\n"
                f"Admins: <code>{len(admin_ids)}</code>"
            )
            await query.edit_message_text(stats_text, parse_mode=ParseMode.HTML)
            return ConversationHandler.END
    
    if query.data in ["add_admin", "remove_admin", "ban_user", "unban_user", "add_forced_channel", "remove_forced_channel"]:
        context.user_data["action"] = query.data
        if query.data in ["add_admin", "remove_admin", "ban_user", "unban_user"]:
            await query.edit_message_text("Please send the user's ID or username.")
            return USER_MGMT_PROMPT
        elif query.data in ["add_forced_channel", "remove_forced_channel"]:
            await query.edit_message_text("Please send the channel's username or id(e.g., `@mychannel`,-100345788643).")
            return FORCE_CHANNEL_PROMPT

    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Generic cancel function for conversations."""
    await update.effective_message.reply_text("❌ Action cancelled. Returning to main menu.", reply_markup=get_main_menu_keyboard(get_user_role(update.effective_user.id)))
    return ConversationHandler.END

# --- SET CHANNEL CONVERSATION ---
async def start_set_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for setting a channel."""
    if not await check_user_access(update, context): return ConversationHandler.END
    await update.message.reply_text("Please send your channel's username (e.g., `@mychannel`) or its ID (e.g., `-100123456789`).")
    return SET_CHANNEL

async def receive_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and validates the channel username or ID."""
    user_id = update.effective_user.id
    channel_input = update.message.text.strip()
    
    try:
        channel_id = int(channel_input)
        if channel_id > -100:
            raise ValueError
        user_channels[user_id] = channel_id
        await update.message.reply_text(
            f"✅ Channel set to ID <code>{channel_id}</code>.\n\n"
            "<b>IMPORTANT:</b> Please make sure the bot is an admin in this channel to publish posts. "
            "I need the permission to post messages.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(get_user_role(user_id))
        )
        save_data()
        return ConversationHandler.END
    except (ValueError, TypeError):
        if not re.match(r"^@\w+$", channel_input):
            await update.message.reply_text("❌ Invalid channel username or ID. Please try again or use /cancel.")
            return SET_CHANNEL
        
        user_channels[user_id] = channel_input
        await update.message.reply_text(
            f"✅ Channel set to username <code>{channel_input}</code>.\n\n"
            "<b>IMPORTANT:</b> Please make sure the bot is an admin in this channel to publish posts. "
            "I need the permission to post messages.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu_keyboard(get_user_role(user_id))
        )
        save_data()
        return ConversationHandler.END

# --- POST CREATION CONVERSATION ---
async def start_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for post creation via command."""
    if not await check_user_access(update, context): return ConversationHandler.END
    
    user_id = update.effective_user.id
    channel_username = user_channels.get(user_id)
    if not channel_username:
        await update.message.reply_text("❌ Please set your channel first using the 'Set Channel' button.")
        return ConversationHandler.END
    
    keyboard = [
        [
            InlineKeyboardButton("Text Only", callback_data="post_type_text"),
            InlineKeyboardButton("Photo with Caption", callback_data="post_type_photo"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "What kind of post would you like to create?",
        reply_markup=reply_markup
    )
    return POST_TYPE

async def handle_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the post type selection."""
    query = update.callback_query
    await query.answer()
    
    context.user_data["post_data"] = {"content_type": query.data.split('_')[-1], "buttons": []}
    
    if context.user_data["post_data"]["content_type"] == "text":
        await query.edit_message_text("Please send the text for your post.")
        return TEXT_CONTENT
    elif context.user_data["post_data"]["content_type"] == "photo":
        await query.edit_message_text("Please send the photo for your post, with an optional caption.")
        return PHOTO_CONTENT
    
    return ConversationHandler.END

async def receive_text_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the text content for the post."""
    context.user_data["post_data"]["text"] = update.message.text
    
    keyboard = [[InlineKeyboardButton("➕ Add Button", callback_data="add_button_yes"),
                 InlineKeyboardButton("✅ Finish", callback_data="add_button_no")]]
    await update.message.reply_text("Text received. Would you like to add inline buttons?", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_BUTTONS

async def receive_photo_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the photo and caption for the post."""
    if not update.message.photo:
        await update.message.reply_text("❌ Invalid input. Please send a photo.")
        return PHOTO_CONTENT
    
    context.user_data["post_data"]["photo_file_id"] = update.message.photo[-1].file_id
    context.user_data["post_data"]["caption"] = update.message.caption or ""
    
    keyboard = [[InlineKeyboardButton("➕ Add Button", callback_data="add_button_yes"),
                 InlineKeyboardButton("✅ Finish", callback_data="add_button_no")]]
    await update.message.reply_text("Photo received. Would you like to add inline buttons?", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_BUTTONS

async def add_buttons_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice to add buttons."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_button_yes":
        await query.edit_message_text("Please send the button text (max 20 chars).")
        return BUTTON_TEXT
    else:
        return await preview_post(update, context)

async def receive_button_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and validates button text."""
    button_text = update.message.text.strip()
    if len(button_text) > 20:
        await update.message.reply_text("❌ Button text is too long (max 20 chars). Please try again.")
        return BUTTON_TEXT
    
    context.user_data["temp_button_text"] = button_text
    await update.message.reply_text("Please send the button URL (must start with http:// or https://).")
    return BUTTON_URL

async def receive_button_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and validates button URL."""
    url = update.message.text.strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ Invalid URL. It must start with <code>http://</code> or <code>https://</code>. Please try again.", parse_mode=ParseMode.HTML)
        return BUTTON_URL
    
    button_text = context.user_data.pop("temp_button_text", None)
    if button_text:
        context.user_data["post_data"]["buttons"].append(InlineKeyboardButton(button_text, url=url))
    
    keyboard = [[InlineKeyboardButton("➕ Add Another Button", callback_data="add_button_yes"),
                 InlineKeyboardButton("✅ Finish and Preview", callback_data="add_button_no")]]
    await update.message.reply_text("Button added! What next?", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_BUTTONS

async def preview_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays a preview of the post."""
    post_data = context.user_data.get("post_data")
    buttons = post_data.get("buttons", [])
    reply_markup = InlineKeyboardMarkup.from_row(buttons) if buttons else None
    
    preview_keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="publish_post")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_post")]
    ]
    preview_markup = InlineKeyboardMarkup(preview_keyboard)
    
    try:
        if post_data["content_type"] == "text":
            text_content = f"<b>Preview Post</b>\n\n{post_data.get('text', '')}"
            await update.effective_message.reply_text(
                text_content,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await update.effective_message.reply_photo(
                photo=post_data.get("photo_file_id"),
                caption=f"<b>Preview Post</b>\n\n{post_data.get('caption', '')}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        await update.effective_message.reply_text("Does this look right?", reply_markup=preview_markup)
        return CONFIRM_POST
    except Exception as e:
        logger.error(f"Error showing preview: {e}")
        await update.effective_message.reply_text("❌ Failed to create a preview. Please try again.")
        return ConversationHandler.END

async def publish_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Publishes the post to the user's channel."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    post_data = context.user_data.pop("post_data", None)
    
    if not post_data:
        await query.edit_message_text("❌ Post session expired. Please start over.")
        return ConversationHandler.END
    
    channel_id = user_channels.get(user_id)
    if not channel_id:
        await query.edit_message_text("❌ Your channel is not set. Please use /setchannel.")
        return ConversationHandler.END
        
    buttons = post_data["buttons"]
    reply_markup = InlineKeyboardMarkup.from_row(buttons) if buttons else None

    try:
        if post_data["content_type"] == "text":
            await context.bot.send_message(
                chat_id=channel_id,
                text=post_data.get("text", ""),
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await context.bot.send_photo(
                chat_id=channel_id,
                photo=post_data.get("photo_file_id"),
                caption=post_data.get("caption", ""),
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        await query.edit_message_text("✅ Post published successfully!")
    except Exception as e:
        logger.error(f"Failed to publish post to {channel_id}: {e}")
        await query.edit_message_text(f"❌ Failed to publish post. Please make sure the bot is an admin in the channel with permission to post messages.")
    
    return ConversationHandler.END

# --- BROADCAST CONVERSATION (ADMIN/OWNER ONLY) ---
async def start_broadcast_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the broadcast conversation."""
    query = update.callback_query
    await query.answer()
    
    context.user_data["broadcast_target"] = query.data
    
    await query.edit_message_text(
        "Please send the content to broadcast (text, photo, video, or voice). "
        "You can add an optional caption to media."
    )
    return BROADCAST_CONTENT

async def receive_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives and stores the content for the broadcast."""
    message = update.message
    
    broadcast_data = {
        "text": message.text,
        "caption": message.caption,
        "photo": message.photo[-1].file_id if message.photo else None,
        "video": message.video.file_id if message.video else None,
        "voice": message.voice.file_id if message.voice else None,
        "buttons": []
    }
    
    context.user_data["broadcast_data"] = broadcast_data
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Button", callback_data="add_broadcast_button_yes")],
        [InlineKeyboardButton("✅ Finish and Preview", callback_data="add_broadcast_button_no")]
    ]
    await message.reply_text(
        "Content received. Do you want to add inline buttons? ",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return BROADCAST_BUTTONS_INPUT

async def handle_broadcast_buttons_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's choice to add broadcast buttons."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "add_broadcast_button_yes":
        await query.edit_message_text("Please send button text and URL in the format <code>[text](url)</code>. Or press /cancel to skip.", parse_mode=ParseMode.HTML)
        return BROADCAST_BUTTONS_INPUT

    return await preview_broadcast(update, context)

async def handle_broadcast_buttons_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the text input for broadcast buttons."""
    message = update.message.text
    match = re.search(r"\[(.+?)\]\((.+?)\)", message)
    if not match:
        await update.message.reply_text("❌ Invalid format. Please use <code>[text](url)</code>. Try again.", parse_mode=ParseMode.HTML)
        return BROADCAST_BUTTONS_INPUT
    
    text, url = match.groups()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("❌ Invalid URL. It must start with <code>http://</code> or <code>https://</code>. Try again.", parse_mode=ParseMode.HTML)
        return BROADCAST_BUTTONS_INPUT

    context.user_data["broadcast_data"]["buttons"].append(InlineKeyboardButton(text, url=url))
    
    keyboard = [
        [InlineKeyboardButton("➕ Add Another Button", callback_data="add_broadcast_button_yes")],
        [InlineKeyboardButton("✅ Finish and Preview", callback_data="add_broadcast_button_no")]
    ]
    await update.message.reply_text("Button added. Add another or finish.", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROADCAST_BUTTONS_INPUT

async def preview_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows a preview of the broadcast message."""
    broadcast_data = context.user_data.get("broadcast_data")
    buttons = broadcast_data.get("buttons", [])
    reply_markup = InlineKeyboardMarkup.from_row(buttons) if buttons else None
    
    preview_keyboard = [
        [InlineKeyboardButton("✅ Confirm Broadcast", callback_data="execute_broadcast")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]
    ]
    preview_markup = InlineKeyboardMarkup(preview_keyboard)
    
    message_sent = False
    try:
        if broadcast_data.get("text"):
            await update.effective_message.reply_text(
                f"<b>Broadcast Preview</b>\n\n{broadcast_data['text']}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            message_sent = True
        elif broadcast_data.get("photo"):
            await update.effective_message.reply_photo(
                photo=broadcast_data["photo"],
                caption=f"<b>Broadcast Preview</b>\n\n{broadcast_data.get('caption', '')}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            message_sent = True
        elif broadcast_data.get("video"):
            await update.effective_message.reply_video(
                video=broadcast_data["video"],
                caption=f"<b>Broadcast Preview</b>\n\n{broadcast_data.get('caption', '')}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            message_sent = True
        elif broadcast_data.get("voice"):
            await update.effective_message.reply_voice(
                voice=broadcast_data["voice"],
                caption=f"<b>Broadcast Preview</b>\n\n{broadcast_data.get('caption', '')}",
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            message_sent = True

        if message_sent:
            await update.effective_message.reply_text("Does this look right?", reply_markup=preview_markup)
            return BROADCAST_CONFIRM
        else:
            await update.effective_message.reply_text("❌ No content found. Broadcast cancelled.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error showing broadcast preview: {e}")
        await update.effective_message.reply_text("❌ Failed to create a broadcast preview. Please try again.")
        return ConversationHandler.END

async def execute_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Executes the broadcast to the selected targets."""
    query = update.callback_query
    await query.answer()
    
    broadcast_data = context.user_data.pop("broadcast_data", None)
    target_type = context.user_data.pop("broadcast_target", None)
    
    if not broadcast_data or not target_type:
        await query.edit_message_text("❌ Broadcast data not found. Please start over.")
        return ConversationHandler.END

    if target_type == "broadcast_users":
        target_list = list(user_stats.keys())
    else: # broadcast_channels
        target_list = list(user_channels.values()) + list(forced_channels)
    
    total_targets = len(target_list)
    sent_count = 0
    failed_count = 0
    
    await query.edit_message_text(f"🚀 Starting broadcast to {total_targets} targets...")

    for target_id in target_list:
        try:
            if broadcast_data.get("text"):
                await context.bot.send_message(
                    chat_id=target_id,
                    text=broadcast_data["text"],
                    reply_markup=InlineKeyboardMarkup.from_row(broadcast_data["buttons"]),
                    parse_mode=ParseMode.HTML
                )
            elif broadcast_data.get("photo"):
                await context.bot.send_photo(
                    chat_id=target_id,
                    photo=broadcast_data["photo"],
                    caption=broadcast_data["caption"],
                    reply_markup=InlineKeyboardMarkup.from_row(broadcast_data["buttons"]),
                    parse_mode=ParseMode.HTML
                )
            elif broadcast_data.get("video"):
                await context.bot.send_video(
                    chat_id=target_id,
                    video=broadcast_data["video"],
                    caption=broadcast_data["caption"],
                    reply_markup=InlineKeyboardMarkup.from_row(broadcast_data["buttons"]),
                    parse_mode=ParseMode.HTML
                )
            elif broadcast_data.get("voice"):
                await context.bot.send_voice(
                    chat_id=target_id,
                    voice=broadcast_data["voice"],
                    caption=broadcast_data["caption"],
                    reply_markup=InlineKeyboardMarkup.from_row(broadcast_data["buttons"]),
                    parse_mode=ParseMode.HTML
                )
            sent_count += 1
            await asyncio.sleep(0.1) # Respect rate limits
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to send broadcast to {target_id}: {e}")

    await query.message.reply_text(
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"Total Targets: <code>{total_targets}</code>\n"
        f"Successful: <code>{sent_count}</code>\n"
        f"Failed: <code>{failed_count}</code>",
        parse_mode=ParseMode.HTML
    )
    
    return ConversationHandler.END

# --- ADMIN/OWNER CONTROL HANDLERS ---
async def manage_user_or_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input for various admin management tasks."""
    user_input = update.message.text.strip()
    action = context.user_data.get("action")
    
    try:
        user_id = int(user_input)
    except (ValueError, TypeError):
        user_id = None
        
    if action == "add_admin":
        if user_id:
            admin_ids.add(user_id)
            await update.message.reply_text(f"✅ User <code>{user_id}</code> is now an admin.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Please send a valid user ID (number).")
    
    elif action == "remove_admin":
        if user_id and user_id != OWNER_ID:
            if user_id in admin_ids:
                admin_ids.remove(user_id)
                await update.message.reply_text(f"✅ User <code>{user_id}</code> is no longer an admin.", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"❌ User <code>{user_id}</code> is not an admin.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Please provide a valid user ID. Cannot remove the owner.")

    elif action == "ban_user":
        if user_id and user_id != OWNER_ID and user_id not in admin_ids:
            banned_users.add(user_id)
            await update.message.reply_text(f"✅ User <code>{user_id}</code> has been banned.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Cannot ban this user. Please provide a valid, non-admin user ID.")

    elif action == "unban_user":
        if user_id:
            if user_id in banned_users:
                banned_users.remove(user_id)
                await update.message.reply_text(f"✅ User <code>{user_id}</code> has been unbanned.", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"❌ User <code>{user_id}</code> is not currently banned.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Please provide a valid user ID.")
    
    save_data()
    return ConversationHandler.END

async def manage_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the input for managing forced join channels."""
    channel_input = update.message.text.strip()
    action = context.user_data.get("action")
    
    try:
        channel_id = int(channel_input)
        if action == "add_forced_channel":
            forced_channels.add(channel_id)
            await update.message.reply_text(f"✅ Channel ID <code>{channel_id}</code> has been added to the forced join list.", parse_mode=ParseMode.HTML)
        elif action == "remove_forced_channel":
            if channel_id in forced_channels:
                forced_channels.remove(channel_id)
                await update.message.reply_text(f"✅ Channel ID <code>{channel_id}</code> has been removed from the forced join list.", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"❌ Channel ID <code>{channel_id}</code> is not on the forced join list.", parse_mode=ParseMode.HTML)
    except (ValueError, TypeError):
        if not re.match(r"^@\w+$", channel_input):
            await update.message.reply_text("❌ Invalid channel username or ID. It must start with `@` or be a numeric ID.")
            return FORCE_CHANNEL_PROMPT
        
        if action == "add_forced_channel":
            forced_channels.add(channel_input)
            await update.message.reply_text(f"✅ Channel <code>{channel_input}</code> has been added to the forced join list.", parse_mode=ParseMode.HTML)
        elif action == "remove_forced_channel":
            if channel_input in forced_channels:
                forced_channels.remove(channel_input)
                await update.message.reply_text(f"✅ Channel <code>{channel_input}</code> has been removed from the forced join list.", parse_mode=ParseMode.HTML)
            else:
                await update.message.reply_text(f"❌ Channel <code>{channel_input}</code> is not on the forced join list.", parse_mode=ParseMode.HTML)
    
    save_data()
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and send a message to the owner."""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"<b>Error Alert!</b>\n\n<code>Update: {update.to_dict()}</code>\n\n<code>Error: {context.error}</code>",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Failed to send error message to owner: {e}")

# --- MAIN FUNCTION ---
def main() -> None:
    """Start the bot."""
    load_data()
    application = Application.builder().token(BOT_TOKEN).build()
    
    set_channel_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("setchannel", start_set_channel),
            CallbackQueryHandler(handle_main_menu_callback, pattern="^set_channel$"),
        ],
        states={
            SET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    post_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("create_post", start_post),
            CallbackQueryHandler(handle_main_menu_callback, pattern="^create_post$"),
        ],
        states={
            POST_TYPE: [CallbackQueryHandler(handle_post_type, pattern="^post_type_.*$")],
            TEXT_CONTENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text_content)],
            PHOTO_CONTENT: [MessageHandler(filters.PHOTO, receive_photo_content)],
            ADD_BUTTONS: [CallbackQueryHandler(add_buttons_prompt, pattern="^add_button_.*$")],
            BUTTON_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_button_text)],
            BUTTON_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_button_url)],
            CONFIRM_POST: [CallbackQueryHandler(publish_post, pattern="^publish_post$"),
                           CallbackQueryHandler(cancel_conv, pattern="^cancel_post$")]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    broadcast_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_main_menu_callback, pattern="^broadcast_menu$"),
        ],
        states={
            BROADCAST_TYPE: [CallbackQueryHandler(start_broadcast_conv, pattern="^broadcast_.*$")],
            BROADCAST_CONTENT: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE, receive_broadcast_content)],
            BROADCAST_BUTTONS_INPUT: [
                CallbackQueryHandler(handle_broadcast_buttons_prompt, pattern="^add_broadcast_button_.*$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_buttons_text)
            ],
            BROADCAST_CONFIRM: [
                CallbackQueryHandler(execute_broadcast, pattern="^execute_broadcast$"),
                CallbackQueryHandler(cancel_conv, pattern="^cancel_broadcast$")
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_main_menu_callback, pattern="^(add_admin|remove_admin|ban_user|unban_user)$"),
            CallbackQueryHandler(handle_main_menu_callback, pattern="^(add_forced_channel|remove_forced_channel)$"),
        ],
        states={
            USER_MGMT_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manage_user_or_channel)],
            FORCE_CHANNEL_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, manage_channel)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(set_channel_conv_handler)
    application.add_handler(post_conv_handler)
    application.add_handler(broadcast_conv_handler)
    application.add_handler(admin_conv_handler)
    application.add_handler(CallbackQueryHandler(handle_main_menu_callback))
    application.add_error_handler(error_handler)

    logger.info("Bot started and polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
