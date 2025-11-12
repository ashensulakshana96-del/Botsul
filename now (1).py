import sqlite3
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from math import ceil
import logging

# Enable logging
logging.basicConfig(level=logging.INFO)

TOKEN = "8284881402:AAGOa-GdPZxt0jRkmTTOCeBT7p5JWFMVNrM"
ADMINS = [6549635175]
CHANNEL_USERNAME = "AnonEduLK"

bot = telebot.TeleBot(TOKEN)
PAGINATION_SIZE = 5  # Items per page
conn = sqlite3.connect("videos.db", check_same_thread=False)
cursor = conn.cursor()

# Database setup - UPGRADED FOR MULTIPLE FILE TYPES
cursor.execute("""
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    title TEXT,
    file_id TEXT,
    file_type TEXT,
    views INTEGER DEFAULT 0,
    FOREIGN KEY(category_id) REFERENCES categories(id)
)
""")
conn.commit()

# Add file_type column if missing
try:
    cursor.execute("SELECT file_type FROM files LIMIT 1")
except sqlite3.OperationalError:
    cursor.execute("ALTER TABLE files ADD COLUMN file_type TEXT DEFAULT 'video'")
    conn.commit()

# DB Functions - UPDATED FOR FILES
def add_category(name):
    cursor.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,))
    conn.commit()

def add_file(category_name, title, file_id, file_type='video'):
    cursor.execute("SELECT id FROM categories WHERE name=?", (category_name,))
    row = cursor.fetchone()
    if row:
        category_id = row[0]
    else:
        add_category(category_name)
        cursor.execute("SELECT id FROM categories WHERE name=?", (category_name,))
        category_id = cursor.fetchone()[0]
    cursor.execute("INSERT INTO files (category_id, title, file_id, file_type) VALUES (?, ?, ?, ?)",
                   (category_id, title, file_id, file_type))
    conn.commit()

def get_categories():
    cursor.execute("SELECT name FROM categories ORDER BY name")
    return [row[0] for row in cursor.fetchall()]

def get_files(category_name, page=1, file_type=None):
    cursor.execute("SELECT id FROM categories WHERE name=?", (category_name,))
    row = cursor.fetchone()
    if not row:
        return [], 0
    category_id = row[0]

    if file_type:
        cursor.execute("SELECT COUNT(*) FROM files WHERE category_id=? AND file_type=?", (category_id, file_type))
        offset = (page - 1) * PAGINATION_SIZE
        cursor.execute("SELECT id, title, file_id, views, file_type FROM files WHERE category_id=? AND file_type=? ORDER BY title LIMIT ? OFFSET ?",
                       (category_id, file_type, PAGINATION_SIZE, offset))
    else:
        cursor.execute("SELECT COUNT(*) FROM files WHERE category_id=?", (category_id,))
        offset = (page - 1) * PAGINATION_SIZE
        cursor.execute("SELECT id, title, file_id, views, file_type FROM files WHERE category_id=? ORDER BY title LIMIT ? OFFSET ?",
                       (category_id, PAGINATION_SIZE, offset))

    files = cursor.fetchall()
    total_files = cursor.fetchone()[0] if file_type else cursor.execute("SELECT COUNT(*) FROM files WHERE category_id=?", (category_id,)).fetchone()[0]
    total_pages = ceil(total_files / PAGINATION_SIZE)
    return files, total_pages

def get_file_by_id(file_id):
    cursor.execute("SELECT id, title, file_id, views, file_type FROM files WHERE id=?", (file_id,))
    return cursor.fetchone()

def search_files(query, page=1, file_type=None):
    if file_type:
        cursor.execute("SELECT COUNT(*) FROM files f JOIN categories c ON f.category_id = c.id WHERE (f.title LIKE ? OR c.name LIKE ?) AND f.file_type=?",
                       (f"%{query}%", f"%{query}%", file_type))
        offset = (page - 1) * PAGINATION_SIZE
        cursor.execute("""
            SELECT f.id, f.title, f.file_id, f.views, c.name, f.file_type 
            FROM files f 
            JOIN categories c ON f.category_id = c.id 
            WHERE (f.title LIKE ? OR c.name LIKE ?) AND f.file_type=?
            ORDER BY f.title 
            LIMIT ? OFFSET ?
        """, (f"%{query}%", f"%{query}%", file_type, PAGINATION_SIZE, offset))
    else:
        cursor.execute("SELECT COUNT(*) FROM files f JOIN categories c ON f.category_id = c.id WHERE f.title LIKE ? OR c.name LIKE ?",
                       (f"%{query}%", f"%{query}%"))
        offset = (page - 1) * PAGINATION_SIZE
        cursor.execute("""
            SELECT f.id, f.title, f.file_id, f.views, c.name, f.file_type 
            FROM files f 
            JOIN categories c ON f.category_id = c.id 
            WHERE f.title LIKE ? OR c.name LIKE ?
            ORDER BY f.title 
            LIMIT ? OFFSET ?
        """, (f"%{query}%", f"%{query}%", PAGINATION_SIZE, offset))

    results = cursor.fetchall()
    total = cursor.fetchone()[0]
    total_pages = ceil(total / PAGINATION_SIZE)
    return results, total_pages

def delete_file(file_id):
    cursor.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit()

def delete_category(cat_name):
    cursor.execute("SELECT id FROM categories WHERE name=?", (cat_name,))
    cat_id = cursor.fetchone()
    if cat_id:
        cursor.execute("DELETE FROM files WHERE category_id=?", (cat_id[0],))
        cursor.execute("DELETE FROM categories WHERE id=?", (cat_id[0],))
        conn.commit()

def get_category_stats(cat_name):
    cursor.execute("SELECT id FROM categories WHERE name=?", (cat_name,))
    row = cursor.fetchone()
    if not row:
        return 0, 0
    cat_id = row[0]
    cursor.execute("SELECT COUNT(*), SUM(views) FROM files WHERE category_id=?", (cat_id,))
    count, views = cursor.fetchone()
    return count or 0, views or 0

def get_top_categories(limit=5):
    cursor.execute("""
        SELECT c.name, COUNT(f.id), SUM(f.views) 
        FROM categories c 
        LEFT JOIN files f ON c.id = f.category_id 
        GROUP BY c.id 
        ORDER BY SUM(f.views) DESC 
        LIMIT ?
    """, (limit,))
    return cursor.fetchall()

# File type icons and handlers
FILE_TYPES = {
    'video': {'icon': '🎥', 'handler': bot.send_video},
    'photo': {'icon': '🖼️', 'handler': bot.send_photo},
    'document': {'icon': '📄', 'handler': bot.send_document},
    'audio': {'icon': '🎵', 'handler': bot.send_audio}
}

# Memory
pending_files = {}
edit_memory = {}
users_set = set()
broadcast_memory = {}
search_memory = {}

def is_member(user_id):
    try:
        member = bot.get_chat_member("@" + CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'creator', 'administrator']
    except:
        return False

def main_menu(user_id, is_admin=False):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("📁 Categories", callback_data="main:categories"))
    markup.add(InlineKeyboardButton("🔍 Search", callback_data="main:search"))
    if is_admin:
        markup.add(InlineKeyboardButton("⚙️ Admin Panel", callback_data="main:admin"))
        markup.add(InlineKeyboardButton("📊 Stats", callback_data="main:stats"))
    markup.add(InlineKeyboardButton("❓ Help", callback_data="main:help"))
    markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))
    return markup

def admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("📤 Upload File", callback_data="admin:upload"))
    markup.add(InlineKeyboardButton("➕ Add Category", callback_data="admin:addcat"))
    markup.add(InlineKeyboardButton("📝 Edit", callback_data="admin:edit"))
    markup.add(InlineKeyboardButton("🗑️ Delete", callback_data="admin:delete"))
    markup.add(InlineKeyboardButton("📊 Analytics", callback_data="admin:analytics"))
    markup.add(InlineKeyboardButton("📢 Broadcast", callback_data="admin:broadcast"))
    markup.add(InlineKeyboardButton("💾 Backup DB", callback_data="admin:backup"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="main:categories"))
    return markup

def file_type_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("🎥 Video", callback_data="upload_type:video"))
    markup.add(InlineKeyboardButton("🖼️ Photo", callback_data="upload_type:photo"))
    markup.add(InlineKeyboardButton("📄 Document", callback_data="upload_type:document"))
    markup.add(InlineKeyboardButton("🎵 Audio", callback_data="upload_type:audio"))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="close"))
    return markup

def safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=None, call=None):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
        if call:
            bot.answer_callback_query(call.id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            if call:
                bot.answer_callback_query(call.id, "Already up to date!")
        else:
            logging.error(f"Edit message error: {e}")
            if call:
                bot.answer_callback_query(call.id, "Error occurred")

# Handlers
@bot.message_handler(commands=['start'])
def start(message):
    new_user = message.from_user.id not in users_set
    users_set.add(message.from_user.id)
    if not is_member(message.from_user.id):
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}"))
        markup.add(InlineKeyboardButton("🔄 Check Again", callback_data="check_member"))
        bot.send_message(message.chat.id, f"❌ Bot use කිරීමට  channel එකට join වන්න!", reply_markup=markup)
        return
    if new_user:
        bot.send_message(message.chat.id, "⚡ සාදරයෙන් පිළිගනිමු!")

    is_admin = message.from_user.id in ADMINS
    bot.send_message(message.chat.id, "🏠 Main Menu:", reply_markup=main_menu(message.from_user.id, is_admin))

@bot.callback_query_handler(func=lambda call: call.data == "check_member")
def check_membership(call):
    if is_member(call.from_user.id):
        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "✅ Membership confirmed! Redirecting to menu...", call=call)
        bot.send_message(call.message.chat.id, "🏠 Main Menu:", reply_markup=main_menu(call.from_user.id, call.from_user.id in ADMINS))
    else:
        bot.answer_callback_query(call.id, "❌ Still not a member. Please join the channel.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("main:"))
def main_handler(call):
    action = call.data.split(":")[1]
    if action == "categories":
        show_categories(call, 1)
    elif action == "search":
        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "🔍 File හෝ category name එක search කරන්න:", call=call)
        bot.register_next_step_handler(call.message, handle_search_input)
    elif action == "admin" and call.from_user.id in ADMINS:
        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "⚙️ Admin Panel:", reply_markup=admin_menu(), call=call)
    elif action == "stats":
        show_stats(call.message.chat.id, call.message.message_id, call.from_user.id, call)
    elif action == "help":
        show_help(call.message.chat.id, call.message.message_id, call)

def show_help(chat_id, message_id, call=None):
    help_text = """
📚 Bot Help:
• /start - Main menu
• Categories: Browse learning files
• Search: Find files by name
• Admins: Upload, manage content

Supported File Types:
🎥 Videos | 🖼️ Photos | 📄 Documents | 🎵 Audio

Commands:
/search <query> - Quick search
/stats - View stats (admin)
/analytics - Detailed analytics (admin)
/broadcast - Send message to all (admin)
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Main Menu", callback_data="main:categories"))
    markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))
    if message_id:
        safe_edit_message_text(bot, chat_id, message_id, help_text, reply_markup=markup, call=call)
    else:
        bot.send_message(chat_id, help_text, reply_markup=markup)

def show_stats(chat_id, message_id, user_id, call=None):
    cursor.execute("SELECT COUNT(*) FROM categories")
    cats = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM files")
    files = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(views) FROM files")
    total_views = cursor.fetchone()[0] or 0
    users = len(users_set)

    # File type breakdown
    cursor.execute("SELECT file_type, COUNT(*) FROM files GROUP BY file_type")
    type_stats = cursor.fetchall()
    type_text = "\n".join([f"{FILE_TYPES.get(row[0], {'icon': '📁'})['icon']} {row[0]}: {row[1]}" for row in type_stats])

    text = f"📊 Quick Stats:\nCategories: {cats}\nFiles: {files}\nTotal Views: {total_views}\nUsers: {users}\n\nFile Types:\n{type_text}"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🏠 Main Menu", callback_data="main:categories"))
    markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))
    if message_id:
        safe_edit_message_text(bot, chat_id, message_id, text, reply_markup=markup, call=call)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

def show_categories(message_or_call, page=1):
    cats = get_categories()
    if not cats:
        text = "📂 Database එක හිස්ය. Admins ට පමණක් files upload කිරීමට හැකිය."
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🏠 Main Menu", callback_data="main:categories"))
        if isinstance(message_or_call, telebot.types.CallbackQuery):
            safe_edit_message_text(bot, message_or_call.message.chat.id, message_or_call.message.message_id, text, reply_markup=markup, call=message_or_call)
        else:
            bot.send_message(message_or_call.chat.id, text, reply_markup=markup)
        return
    total_pages = ceil(len(cats) / PAGINATION_SIZE)
    start_idx = (page - 1) * PAGINATION_SIZE
    end_idx = min(start_idx + PAGINATION_SIZE, len(cats))
    page_cats = cats[start_idx:end_idx]

    markup = InlineKeyboardMarkup(row_width=1)
    for c in page_cats:
        markup.add(InlineKeyboardButton(f"📂 {c}", callback_data=f"cat:{c}:1"))
    nav_row = []
    if total_pages > 1:
        if page > 1:
            nav_row.append(InlineKeyboardButton("🔙 Prev", callback_data=f"cats:{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"cats:{page+1}"))
        if nav_row:
            markup.row(*nav_row)
    markup.add(InlineKeyboardButton("🔍 Search", callback_data="main:search"))
    markup.add(InlineKeyboardButton("🏠 Main Menu", callback_data="main:categories"))
    markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))

    text = f"📁 Categories (Page {page}/{total_pages}):"
    if isinstance(message_or_call, telebot.types.CallbackQuery):
        safe_edit_message_text(bot, message_or_call.message.chat.id, message_or_call.message.message_id, text, reply_markup=markup, call=message_or_call)
    else:
        bot.send_message(message_or_call.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cats:"))
def cat_pagination(call):
    page = int(call.data.split(":")[1])
    show_categories(call, page)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat:"))
def show_category(call):
    try:
        parts = call.data.split(":")
        category = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 1
        files, total_pages = get_files(category, page)

        if not files:
            bot.answer_callback_query(call.id, "❌ මෙම category එකේ files නොමැත")
            return

        markup = InlineKeyboardMarkup(row_width=1)
        for file_data in files:
            f_id, title, file_id, views, f_type = file_data
            icon = FILE_TYPES.get(f_type, {'icon': '📁'})['icon']
            display_title = title[:50] + "..." if len(title) > 50 else title
            markup.add(InlineKeyboardButton(f"{icon} {display_title} 👁️{views}", callback_data=f"file:{f_id}"))

        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("🔙 Prev", callback_data=f"cat:{category}:{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"cat:{category}:{page+1}"))
        if nav_row:
            markup.row(*nav_row)

        markup.add(InlineKeyboardButton("🔙 Back to Categories", callback_data="back_cat"))
        markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))

        file_count, total_views = get_category_stats(category)
        text = f"📁 {category}\n\nFiles: {file_count} | Total Views: {total_views}\n\nFiles (Page {page}/{total_pages}):"
        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, text, reply_markup=markup, call=call)
    except Exception as e:
        logging.error(f"Error in show_category: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred")

@bot.callback_query_handler(func=lambda call: call.data.startswith("file:"))
def show_file(call):
    try:
        file_id = int(call.data.split(":", 1)[1])
        file_data = get_file_by_id(file_id)

        if not file_data:
            bot.answer_callback_query(call.id, "❌ File එක හිමු නොවීය!")
            return

        f_id, title, file_id, views, f_type = file_data
        icon = FILE_TYPES.get(f_type, {'icon': '📁'})['icon']

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton(f"{icon} View File", callback_data=f"view:{f_id}"))
        if call.from_user.id in ADMINS:
            markup.add(InlineKeyboardButton("🗑️ Delete File", callback_data=f"del:{f_id}"))
            markup.add(InlineKeyboardButton("📝 Edit Title", callback_data=f"editfile:{f_id}"))
        markup.row(InlineKeyboardButton("🔙 Back", callback_data="back_cat"))
        markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))

        bot.edit_message_text(f"{icon} {title}\n👁️ Views: {views}\n\nOption එකක් select කරන්න:",
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup)
        bot.answer_callback_query(call.id)
    except Exception as e:
        logging.error(f"Error in show_file: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred")

@bot.callback_query_handler(func=lambda call: call.data.startswith("view:"))
def view_file(call):
    try:
        file_id = int(call.data.split(":", 1)[1])
        file_data = get_file_by_id(file_id)

        if file_data:
            f_id, title, file_id, views, f_type = file_data
            cursor.execute("UPDATE files SET views=? WHERE id=?", (views+1, f_id))
            conn.commit()

            try:
                handler = FILE_TYPES.get(f_type, {}).get('handler')
                if handler:
                    if f_type == 'video':
                        handler(call.message.chat.id, file_id, caption=f"{title}\n👁️ Views: {views+1}", supports_streaming=True, protect_content=True)
                    else:
                        handler(call.message.chat.id, file_id, caption=f"{title}\n👁️ Views: {views+1}")
                    bot.answer_callback_query(call.id, f"✅ {f_type.capitalize()} sent!")
                else:
                    bot.send_message(call.message.chat.id, f"❌ Unsupported file type: {f_type}")
            except Exception as e:
                logging.error(f"Error sending {f_type}: {e}")
                bot.send_message(call.message.chat.id, f"❌ මෙම {f_type} file එක unavailable ය.")
                bot.answer_callback_query(call.id, f"❌ {f_type.capitalize()} unavailable")
    except Exception as e:
        logging.error(f"Error in view_file: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred")

@bot.callback_query_handler(func=lambda call: call.data.startswith("del:"))
def delete_file_handler(call):
    if call.from_user.id not in ADMINS:
        bot.answer_callback_query(call.id, "❌ Admins only!")
        return
    file_id = int(call.data.split(":", 1)[1])
    try:
        cursor.execute("SELECT title FROM files WHERE id=?", (file_id,))
        title = cursor.fetchone()[0]
        delete_file(file_id)
        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"🗑️ File '{title}' deleted successfully!", call=call)
    except Exception as e:
        logging.error(f"Error deleting file: {e}")
        bot.answer_callback_query(call.id, "❌ Error deleting")

@bot.callback_query_handler(func=lambda call: call.data == "back_cat")
def back_categories(call):
    try:
        show_categories(call)
    except Exception as e:
        logging.error(f"Error in back_categories: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "close")
def close_message(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass

# Search Functionality
@bot.message_handler(commands=['search'])
def search_start(message):
    if not is_member(message.from_user.id):
        bot.reply_to(message, f"❌ Bot use කිරීමට  channel එකට join වන්න!")
        return
    query = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""
    if query:
        handle_search(message, query)
    else:
        bot.reply_to(message, "🔍 File හෝ category name එක search කරන්න:")

def handle_search_input(message):
    if not is_member(message.from_user.id):
        return
    query = message.text.strip()
    if query:
        handle_search(message, query)
    else:
        bot.reply_to(message, "❌ Empty query. Try again.")
        bot.send_message(message.chat.id, "🔍 Search:", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔍 Search", callback_data="main:search")))

def handle_search(message, query):
    results, total_pages = search_files(query, 1)
    if not results:
        bot.reply_to(message, f"❌ No results for '{query}'")
        return

    search_memory[message.from_user.id] = query
    markup = InlineKeyboardMarkup(row_width=1)
    for f_id, title, file_id, views, cat, f_type in results:
        icon = FILE_TYPES.get(f_type, {'icon': '📁'})['icon']
        display_title = title[:40] + "..." if len(title) > 40 else title
        markup.add(InlineKeyboardButton(f"{icon} {display_title} ({cat}) 👁️{views}", callback_data=f"file:{f_id}"))

    if total_pages > 1:
        markup.row(InlineKeyboardButton("Next ➡️", callback_data=f"search_next:{query}:2"))

    markup.add(InlineKeyboardButton("🔙 Main Menu", callback_data="main:categories"))
    markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))

    bot.reply_to(message, f"🔍 Results for '{query}' (Page 1/{total_pages}):\n\nSelect a file:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("search_next:"))
def search_pagination(call):
    try:
        parts = call.data.split(":", 2)
        query = parts[2].split(":", 1)[0] if len(parts[2].split(":")) > 1 else parts[2]
        page = int(call.data.split(":")[-1])
        results, total_pages = search_files(query, page)
        if not results:
            bot.answer_callback_query(call.id, "❌ No more results")
            return

        markup = InlineKeyboardMarkup(row_width=1)
        for f_id, title, file_id, views, cat, f_type in results:
            icon = FILE_TYPES.get(f_type, {'icon': '📁'})['icon']
            display_title = title[:40] + "..." if len(title) > 40 else title
            markup.add(InlineKeyboardButton(f"{icon} {display_title} ({cat}) 👁️{views}", callback_data=f"file:{f_id}"))

        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("🔙 Prev", callback_data=f"search_next:{query}:{page-1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"search_next:{query}:{page+1}"))
        if nav_row:
            markup.row(*nav_row)

        markup.add(InlineKeyboardButton("🔙 Main Menu", callback_data="main:categories"))
        markup.add(InlineKeyboardButton("❌ Close", callback_data="close"))

        safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"🔍 Results for '{query}' (Page {page}/{total_pages}):\n\nSelect a file:", reply_markup=markup, call=call)
    except Exception as e:
        logging.error(f"Search pagination error: {e}")
        bot.answer_callback_query(call.id, "❌ Error")

# File Upload Handlers - UPDATED FOR MULTIPLE TYPES
@bot.callback_query_handler(func=lambda call: call.data == "admin:upload")
def admin_upload_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "📤 Select file type to upload:", reply_markup=file_type_menu(), call=call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_type:"))
def handle_upload_type(call):
    if call.from_user.id not in ADMINS:
        return
    file_type = call.data.split(":")[1]
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"📤 Upload a {file_type} with caption as title.", call=call)
    pending_files[call.from_user.id] = {"type": file_type, "waiting": True}

# Handle different file types
@bot.message_handler(content_types=['video', 'photo', 'document', 'audio'])
def capture_file(message):
    if message.from_user.id not in ADMINS:
        return

    file_info = pending_files.get(message.from_user.id, {})
    if not file_info.get("waiting"):
        return

    file_type = file_info["type"]
    file_id = None
    title = message.caption or "Untitled"

    if file_type == 'video' and message.video:
        file_id = message.video.file_id
    elif file_type == 'photo' and message.photo:
        file_id = message.photo[-1].file_id  # Highest resolution
    elif file_type == 'document' and message.document:
        file_id = message.document.file_id
    elif file_type == 'audio' and message.audio:
        file_id = message.audio.file_id

    if not file_id:
        bot.reply_to(message, f"❌ Please send a {file_type} file.")
        return

    pending_files[message.from_user.id] = {"file_id": file_id, "title": title, "type": file_type}

    markup = InlineKeyboardMarkup(row_width=1)
    for c in get_categories():
        markup.add(InlineKeyboardButton(c, callback_data=f"assign:{c}"))
    markup.add(InlineKeyboardButton("➕ New Category", callback_data="assign_new"))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="close"))

    icon = FILE_TYPES.get(file_type, {'icon': '📁'})['icon']
    bot.reply_to(message, f"{icon} Assign {file_type} '{title}' to category:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("assign:"))
def assign_category(call):
    user_id = call.from_user.id
    if user_id not in pending_files or "file_id" not in pending_files[user_id]:
        bot.answer_callback_query(call.id, "❌ No pending file")
        return

    file_data = pending_files.pop(user_id)
    file_id = file_data["file_id"]
    title = file_data["title"]
    file_type = file_data["type"]
    category = call.data.split(":", 1)[1]

    add_file(category, title, file_id, file_type)
    icon = FILE_TYPES.get(file_type, {'icon': '📁'})['icon']
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"✅ {icon} '{title}' added to '{category}'!", call=call)
    bot.send_message(call.message.chat.id, "🏠 Main Menu:", reply_markup=main_menu(user_id, True))

@bot.callback_query_handler(func=lambda call: call.data == "assign_new")
def assign_new_category(call):
    user_id = call.from_user.id
    if user_id not in pending_files or "file_id" not in pending_files[user_id]:
        bot.answer_callback_query(call.id, "❌ No pending file")
        return

    file_data = pending_files[user_id]
    pending_files[user_id] = {**file_data, "waiting_category": True}

    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "📝 Enter new category name:", call=call)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, save_new_category)

@bot.message_handler(func=lambda m: m.from_user.id in pending_files and 
                   pending_files.get(m.from_user.id, {}).get("waiting_category"))
def save_new_category(message):
    if message.from_user.id not in pending_files:
        return
    file_data = pending_files.pop(message.from_user.id)
    file_id = file_data["file_id"]
    title = file_data["title"]
    file_type = file_data["type"]
    category = message.text.strip()

    if not category:
        bot.send_message(message.chat.id, "❌ Category name cannot be empty!")
        return

    add_file(category, title, file_id, file_type)
    icon = FILE_TYPES.get(file_type, {'icon': '📁'})['icon']
    bot.send_message(message.chat.id, f"✅ New category '{category}' created and {icon} '{title}' added!")
    bot.send_message(message.chat.id, "🏠 Main Menu:", reply_markup=main_menu(message.from_user.id, True))

# Rest of the admin functions remain the same (just updated variable names from video->file)
@bot.callback_query_handler(func=lambda call: call.data == "admin:addcat")
def add_category_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "➕ Enter new category name:", call=call)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, add_category_handler)

def add_category_handler(message):
    if message.from_user.id not in ADMINS:
        return
    cat_name = message.text.strip()
    if not cat_name:
        bot.send_message(message.chat.id, "❌ Name cannot be empty!")
        return
    add_category(cat_name)
    bot.send_message(message.chat.id, f"✅ Category '{cat_name}' added!")
    bot.send_message(message.chat.id, "⚙️ Admin Panel:", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "admin:backup")
def backup_db_handler(call):
    if call.from_user.id not in ADMINS:
        return
    try:
        with open("videos.db", "rb") as f:
            bot.send_document(call.message.chat.id, f, caption="📊 Database Backup")
        bot.answer_callback_query(call.id, "✅ Backup sent!")
    except Exception as e:
        logging.error(f"Backup error: {e}")
        bot.answer_callback_query(call.id, "❌ Backup failed")

@bot.callback_query_handler(func=lambda call: call.data == "admin:analytics")
def show_analytics(call):
    if call.from_user.id not in ADMINS:
        return
    cursor.execute("SELECT COUNT(*) FROM categories")
    cats = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM files")
    files = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(views) FROM files")
    total_views = cursor.fetchone()[0] or 0
    users = len(users_set)

    cursor.execute("SELECT file_type, COUNT(*) FROM files GROUP BY file_type")
    type_stats = cursor.fetchall()
    type_text = "\n".join([f"{FILE_TYPES.get(row[0], {'icon': '📁'})['icon']} {row[0]}: {row[1]}" for row in type_stats])

    top_cats = get_top_categories(5)
    top_cats_text = "\n".join([f"📂 {row[0]}: {row[1]} files, {row[2] or 0} views" for row in top_cats])

    text = f"📊 Analytics:\nCategories: {cats}\nFiles: {files}\nTotal Views: {total_views}\nUsers: {users}\n\nFile Types:\n{type_text}\n\nTop Categories:\n{top_cats_text}"
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, text, call=call)

@bot.callback_query_handler(func=lambda call: call.data == "admin:broadcast")
def broadcast_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "📢 Broadcast message:", call=call)
    broadcast_memory[call.from_user.id] = {"waiting": True}
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, broadcast_handler)

def broadcast_handler(message):
    if message.from_user.id not in ADMINS:
        return
    text = message.text
    if not text:
        bot.send_message(message.chat.id, "❌ Empty message")
        return

    broadcast_memory[message.from_user.id] = {"text": text, "sent": 0, "failed": 0}
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Confirm", callback_data="broadcast_confirm"))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="close"))
    bot.send_message(message.chat.id, f"📢 Send to {len(users_set)} users?\n\n{text}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "broadcast_confirm")
def broadcast_confirm(call):
    if call.from_user.id not in ADMINS or call.from_user.id not in broadcast_memory:
        return
    data = broadcast_memory[call.from_user.id]
    text = data["text"]
    sent = 0
    failed = 0

    for user_id in users_set:
        try:
            bot.send_message(user_id, f"📢 Announcement:\n\n{text}")
            sent += 1
        except:
            failed += 1

    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}", call=call)
    if call.from_user.id in broadcast_memory:
        del broadcast_memory[call.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "admin:edit")
def edit_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for c in get_categories():
        markup.add(InlineKeyboardButton(f"📂 {c}", callback_data=f"editcat:{c}"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="main:admin"))
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "📝 Select category to edit:", reply_markup=markup, call=call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editcat:"))
def edit_category(call):
    if call.from_user.id not in ADMINS:
        return
    cat_name = call.data.split(":", 1)[1]
    files, _ = get_files(cat_name)
    if not files:
        bot.answer_callback_query(call.id, "❌ No files in this category")
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for file_data in files:
        f_id, title, file_id, views, f_type = file_data
        icon = FILE_TYPES.get(f_type, {'icon': '📁'})['icon']
        markup.add(InlineKeyboardButton(f"{icon} {title}", callback_data=f"editfile:{f_id}"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="admin:edit"))
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"📝 Select file to edit in '{cat_name}':", reply_markup=markup, call=call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editfile:"))
def edit_file_title(call):
    if call.from_user.id not in ADMINS:
        return
    file_id = int(call.data.split(":", 1)[1])
    edit_memory[call.from_user.id] = {"file_id": file_id, "waiting": True}
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "📝 Enter new title:", call=call)
    bot.register_next_step_handler_by_chat_id(call.message.chat.id, save_edit_title)

def save_edit_title(message):
    if message.from_user.id not in edit_memory:
        return
    data = edit_memory.pop(message.from_user.id)
    file_id = data["file_id"]
    new_title = message.text.strip()
    if not new_title:
        bot.send_message(message.chat.id, "❌ Title cannot be empty!")
        return

    cursor.execute("UPDATE files SET title=? WHERE id=?", (new_title, file_id))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Title updated to '{new_title}'!")
    bot.send_message(message.chat.id, "⚙️ Admin Panel:", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "admin:delete")
def delete_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for c in get_categories():
        markup.add(InlineKeyboardButton(f"📂 {c}", callback_data=f"delcat:{c}"))
    markup.add(InlineKeyboardButton("🔙 Back", callback_data="main:admin"))
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, "🗑️ Select category to delete:", reply_markup=markup, call=call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delcat:"))
def delete_category_prompt(call):
    if call.from_user.id not in ADMINS:
        return
    cat_name = call.data.split(":", 1)[1]
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Confirm Delete", callback_data=f"confirm_delcat:{cat_name}"))
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data="admin:delete"))
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"🗑️ Delete category '{cat_name}' and all its files?", reply_markup=markup, call=call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delcat:"))
def delete_category_confirm(call):
    if call.from_user.id not in ADMINS:
        return
    cat_name = call.data.split(":", 1)[1]
    delete_category(cat_name)
    safe_edit_message_text(bot, call.message.chat.id, call.message.message_id, f"✅ Category '{cat_name}' and all its files deleted!", call=call)

# Run bot
if __name__ == "__main__":
    print("Bot started...")
    bot.infinity_polling()
