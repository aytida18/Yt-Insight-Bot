import re
import requests
import html
import asyncio
import os
import time
import sqlite3
import asyncpg
from dotenv import load_dotenv
load_dotenv()
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
import isodate
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import Forbidden, BadRequest

BOT_TOKEN = os.getenv("BOT_TOKEN")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ADMIN_ID = 1721427995
# Force Subscribe Configuration
FORCE_CHANNEL_USERNAME = "@aditya_labs"
FORCE_CHANNEL_ID = -1003644491983
VERIFY_URL = "https://adityalabs.short.gy/Yt-Verify"
VERIFY_DURATION = 24 * 60 * 60
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = None
BOT_ID = 9

conn = sqlite3.connect("verified_users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS verified_users (
    user_id INTEGER PRIMARY KEY,
    verified_at INTEGER
)
""")
conn.commit()

# ================= VERIFICATION CORE =================
def is_verified(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True

    cursor.execute(
        "SELECT verified_at FROM verified_users WHERE user_id=?",
        (user_id,)
    )
    row = cursor.fetchone()

    if not row:
        return False

    return (time.time() - row[0]) < VERIFY_DURATION


def mark_verified(user_id: int):
    cursor.execute(
        "REPLACE INTO verified_users (user_id, verified_at) VALUES (?, ?)",
        (user_id, int(time.time()))
    )
    conn.commit()

# ================= /start (VERIFY ONLY) =================
async def ensure_verified(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False

    if not is_verified(user.id):
        buttons = [
            [InlineKeyboardButton("👉 Click to Verify", url=VERIFY_URL)],
            [InlineKeyboardButton("❓ How to Verify", url="https://t.me/+SReToBAyE9MwNjUx")]
        ]

        await update.message.reply_text(
            "🔒 <b>Access Restricted</b>\n\n"
            "<b>➤ To use this bot, please complete verification below.</b>\n\n",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return False

    return True

async def check_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(
            chat_id=FORCE_CHANNEL_ID,
            user_id=user_id
        )
        return member.status in ["member", "administrator", "creator"]
    except:
        # ❌ Error aaye to NOT JOINED maanenge
        return False

async def force_verify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if await check_membership(user.id, context):
        return True

    buttons = [
        [InlineKeyboardButton(
            "🔔 Join Channel",
            url="https://t.me/aditya_labs"
        )],
        [InlineKeyboardButton(
            "✅ I've Joined",
            callback_data="check_subscription"
        )]
    ]

    text = (
        "🔒 <b>Access Restricted</b>\n\n"
        "Please join our official channel to use this bot."
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
    elif update.callback_query:
        await update.callback_query.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    return False

async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    # 1️⃣ ALWAYS channel check first
    if not await check_membership(update.effective_user.id, context):
        await force_verify(update, context)
        return False

    # 2️⃣ THEN verify check
    if not await ensure_verified(update, context):
        return False

    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    await save_user(user)

    # ✅ VERIFY VIA LANDING PAGE REDIRECT
    if context.args and context.args[0] == "verify":
        mark_verified(user_id)

        await update.message.reply_text(
            "✅ <b>Verified!</b>\n\n"
            "<b>You can now use this bot.</b>\n"
            "<b>Access is valid for 24 hours.</b>",
            parse_mode="HTML"
        )
        return

   # 🔒 Channel join check ONLY on /start
    if not await force_verify(update, context):
        return

    msg = """
<b>🚀 WELCOME TO YOUTUBE CREATOR TOOL</b>

<b>Get complete YouTube video and channel insights instantly.</b>

<b>📩 Just Send:</b>
<blockquote><b>• YouTube Video Link</b>
<b>• YouTube Channel Link</b></blockquote>

<b>🖼 You'll also get Video Thumbnail, Channel Banner & Profile Photo.</b>

━━━━━━━━━━━━━━━━━━
<b>🤖 Powered by @aditya_labs</b>
━━━━━━━━━━━━━━━━━━
"""
    await update.message.reply_text(msg, parse_mode="HTML")

async def save_user(user):
    async with db_pool.acquire() as conn:

        # users table
        await conn.execute(
        """
        INSERT INTO users (user_id, username, first_name, blocked)
        VALUES ($1, $2, $3, FALSE)
        ON CONFLICT (user_id)
        DO UPDATE SET username = EXCLUDED.username, first_name = EXCLUDED.first_name, blocked = FALSE, last_active = now()
        """,
            user.id,
            user.username,
            user.first_name
        )

        # user_bot_map table
        await conn.execute(
        """
            INSERT INTO user_bot_map (user_id, bot_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
            """,
            user.id,
            BOT_ID
        )

# ================= /admin PANEL =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    buttons = [
        [
            InlineKeyboardButton("📊 Statistics", callback_data="stats"),
            InlineKeyboardButton("📣 Broadcast", callback_data="broadcast")
        ]
    ]

    await update.message.reply_text(
        "🛠️ **Admin Panel**",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ================= CALLBACK ROUTER =================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    # ================= VERIFY BUTTON =================
    if data == "check_subscription":
        user_joined = await check_membership(user_id, context)

        # ---------- NOT JOINED ----------
        if not user_joined:
            await query.answer("❌ You haven't joined yet!", show_alert=True)

            failed_msg = await query.message.reply_text(
                "❌ <b>Verification Failed!</b>\n\n"
                "Please join the channel and try again.",
                parse_mode="HTML"
            )

            # store ALL failed message ids
            failed_ids = context.user_data.get("failed_verify_msg_ids", [])
            failed_ids.append(failed_msg.message_id)
            context.user_data["failed_verify_msg_ids"] = failed_ids
            return

        # ---------- JOINED ----------
        await query.answer("✅ Verified!")

        # delete verify button message
        try:
            await query.message.delete()
        except:
            pass

        # delete ALL failed verification messages
        failed_ids = context.user_data.get("failed_verify_msg_ids", [])
        for mid in failed_ids:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=mid
                )
            except:
                pass

        context.user_data.pop("failed_verify_msg_ids", None)

        await query.message.reply_text(
            "✅ **Verified!**\nNow you can use the bot.",
            parse_mode="Markdown"
        )
        return

    await query.answer()

    # ================= ADMIN ONLY =================
    if (data.startswith("broadcast") or data == "stats") and user_id != ADMIN_ID:
        return

    # ================= STATISTICS =================
    if data == "stats":
        async with db_pool.acquire() as conn:

            total = await conn.fetchval(
                "SELECT COUNT(*) FROM user_bot_map WHERE bot_id = $1",
                BOT_ID
            )

            active = await conn.fetchval(
                """
                SELECT COUNT(*) FROM users u
                JOIN user_bot_map m ON u.user_id = m.user_id
                WHERE m.bot_id = $1 AND u.blocked = FALSE
                """,
                BOT_ID
            )


        await query.message.reply_text(
            f"📊 **Statistics**\n\n"
            f"👥 Total Users: {total}\n"
            f"✅ Active Users: {active}",
            parse_mode="Markdown"
        )
        return

    # ================= BROADCAST START =================
    if data == "broadcast":
        context.user_data["awaiting_broadcast"] = True
        await query.message.reply_text(
            "✍️ Send the broadcast message.\n"
            "You will be asked to confirm before sending."
        )
        return

    # ================= BROADCAST CONFIRM =================
    if data == "broadcast_confirm":
        try:
            await query.message.delete()
        except:
            pass

        sent = failed = 0

        async with db_pool.acquire() as conn:

            rows = await conn.fetch(
                """
                SELECT u.user_id 
                FROM users u 
                JOIN user_bot_map m ON u.user_id = m.user_id 
                WHERE m.bot_id = $1 AND u.blocked = FALSE
                """,
                BOT_ID
            )

            total_users = len(rows)

            progress_msg = await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=(
                    f"<b>📡 Sending Broadcast...</b>\n\n"
                    f"📤 Sent: 0 / {total_users}\n"
                    f"❌ Failed: 0"
                ),
                parse_mode="HTML"
            )

            for index, r in enumerate(rows, start=1):
                uid = r["user_id"]

                try:
                    # Forward if message was forwarded
                    if context.user_data.get("is_forward"):
                        await context.bot.forward_message(
                            chat_id=uid,
                            from_chat_id=context.user_data["broadcast_chat_id"],
                            message_id=context.user_data["broadcast_message_id"]
                        )
                    else:
                        await context.bot.copy_message(
                            chat_id=uid,
                            from_chat_id=context.user_data["broadcast_chat_id"],
                            message_id=context.user_data["broadcast_message_id"]
                        )

                    sent += 1
                    await asyncio.sleep(0.07)

                except Forbidden:
                    failed += 1
                    await conn.execute(
                        "UPDATE users SET blocked = TRUE WHERE user_id = $1",
                        uid
                    )

                except BadRequest:
                    failed += 1
                except Exception as e:
                    print("Broadcast error:", e)
                    failed += 1

                # 🔥 Proper progress update
                if index % 5 == 0 or index == total_users:
                    try:
                        await progress_msg.edit_text(
                            f"<b>📡 Sending Broadcast...</b>\n\n"
                            f"📤 Sent: {sent} / {total_users}\n"
                            f"❌ Failed: {failed}",
                            parse_mode="HTML"
                        )
                    except:
                        pass

        try:
            await progress_msg.delete()
        except:
            pass

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                f"✅ **Broadcast Completed**\n\n"
                f"📤 Sent: {sent}\n"
                f"❌ Failed: {failed}"
            ),
            parse_mode="Markdown"
        )

        context.user_data.clear()
        return

    # ================= BROADCAST CANCEL =================
    if data == "broadcast_cancel":
        # delete confirm message
        try:
            await query.message.delete()
        except:
            pass

        context.user_data.clear()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Broadcast cancelled."
        )
        return
    
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.user_data.get("awaiting_broadcast"):
        return

    # Store full message object info
    context.user_data["broadcast_message_id"] = update.message.message_id
    context.user_data["broadcast_chat_id"] = update.message.chat_id
    is_forward = update.message.forward_origin is not None
    context.user_data["is_forward"] = is_forward

    buttons = [
        [
            InlineKeyboardButton("✅ Confirm", callback_data="broadcast_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="broadcast_cancel")
        ]
    ]

    await update.message.reply_text(
        "⚠️ <b>Confirm Broadcast</b>\n\nThis message will be sent as it is.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

    context.user_data["awaiting_broadcast"] = False
    
# ================= REGISTER (PLUG & PLAY) =================

def register_core_panel(app):
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(
        CallbackQueryHandler(
            callback_router,
            pattern="^(check_subscription|stats|broadcast|broadcast_confirm|broadcast_cancel)"
        )
    )

def extract_url(text):
    match = re.search(r"https?://[^\s]+", text)
    if match:
        url = match.group(0)
        return url.split("?")[0]  # remove ?si tracking
    return None

# extract video id
def get_video_id(url):
    patterns = [
        r"v=([0-9A-Za-z_-]{11})",
        r"youtu\.be\/([0-9A-Za-z_-]{11})",
        r"shorts\/([0-9A-Za-z_-]{11})",
        r"embed\/([0-9A-Za-z_-]{11})"
    ]
    for p in patterns:
        match = re.search(p, url)
        if match:
            return match.group(1)
    return None

# extract channel id
def get_channel_id(url):

    url = url.split("?")[0]

    # channel id link
    match = re.search(r"youtube\.com/channel/([A-Za-z0-9_-]+)", url)
    if match:
        return match.group(1)

    # handle link
    handle_match = re.search(r"youtube\.com/@([A-Za-z0-9._-]+)", url)

    if handle_match:
        handle = handle_match.group(1)

        api = f"https://www.googleapis.com/youtube/v3/channels?part=id&forHandle={handle}&key={YOUTUBE_API_KEY}"

        r = requests.get(api, timeout=10).json()

        if "items" in r and len(r["items"]) > 0:
            return r["items"][0]["id"]

    return None

def get_latest_videos(playlist_id):
    api = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=3&playlistId={playlist_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(api).json()

    videos = []

    for item in r.get("items", []):
        title = item["snippet"]["title"]
        vid = item["snippet"]["resourceId"]["videoId"]

        stats = requests.get(
            f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={vid}&key={YOUTUBE_API_KEY}"
        ).json()

        views = stats["items"][0]["statistics"].get("viewCount", "0")

        videos.append((title, views))

    return videos
  
def format_number(n):

    n = int(n)

    if n < 1000:
        return str(n)

    elif n < 1_000_000:
        return f"{n/1000:.2f}".rstrip("0").rstrip(".") + "K"

    elif n < 1_000_000_000:
        return f"{n/1_000_000:.2f}".rstrip("0").rstrip(".") + "M"

    else:
        return f"{n/1_000_000_000:.2f}".rstrip("0").rstrip(".") + "B"
 
def format_views(n):

    n = int(n)

    if n < 1000:
        return str(n)

    short = format_number(n)

    return f"{n} ({short})"
   
def get_top_video(playlist_id):

    api = f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=50&playlistId={playlist_id}&key={YOUTUBE_API_KEY}"
    r = requests.get(api).json()

    video_ids = []
    titles = {}

    for item in r.get("items", []):
        vid = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]

        video_ids.append(vid)
        titles[vid] = title

    if not video_ids:
        return "N/A", 0

    ids = ",".join(video_ids)

    stats_api = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={ids}&key={YOUTUBE_API_KEY}"
    stats = requests.get(stats_api).json()

    best_views = 0
    best_title = "N/A"

    for item in stats.get("items", []):
        vid = item["id"]
        views = int(item["statistics"].get("viewCount", 0))

        if views > best_views:
            best_views = views
            best_title = titles.get(vid, "N/A")

    return best_title, best_views

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return

    msg = await update.message.reply_text(
        "<b>🔍 Fetching YouTube details...</b>",
        parse_mode="HTML"
    )

    url = extract_url(update.message.text)
    
    if not url:
        await msg.delete()
        await update.message.reply_text(
            "<b>❌ No valid YouTube link found.</b>",
            parse_mode="HTML"
        )
        return

    # VIDEO
    video_id = get_video_id(url)

    if video_id:
        api = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id={video_id}&key={YOUTUBE_API_KEY}"
        r = requests.get(api).json()

        if not r["items"]:
            await msg.delete()
            return

        data = r["items"][0]
        
        upload_date = data["snippet"]["publishedAt"][:10]

        title = data["snippet"]["title"]
        channel = data["snippet"]["channelTitle"]
        desc = data["snippet"]["description"][:400]
        tags = ", ".join(data["snippet"].get("tags", [])[:10])

        views_raw = data["statistics"].get("viewCount", "0")
        views = format_views(views_raw)
        likes = data["statistics"].get("likeCount", "0")
        comments = data["statistics"].get("commentCount", "0")

        duration = str(isodate.parse_duration(data["contentDetails"]["duration"]))

        thumb = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

        # dislike API
        d = requests.get(
            f"https://returnyoutubedislikeapi.com/votes?videoId={video_id}"
        ).json()

        dislikes = d.get("dislikes", "N/A")

        caption = f"""
<b>╔══════════════════════════╗
           🎬 𝙔𝙊𝙐𝙏𝙐𝘽𝙀 𝙑𝙄𝘿𝙀𝙊 𝘿𝙀𝙏𝘼𝙄𝙇𝙎
╚══════════════════════════╝</b>

<b>📌 Title:</b> {title}

<b>👤 Channel:</b> {channel}

<b>📅 Upload Date:</b> {upload_date}

<b>⏱ Duration:</b> {duration}

<b>👀 Views:</b> {views}

<b>👍 Likes:</b> {likes}

<b>💬 Comments:</b> {comments}

<b>🏷 Tags:</b> {tags}

<b>📝 Description:</b>
{desc}

<b>👎 Estimated Dislikes:</b> {dislikes}
<i>(Source: Return YouTube Dislike)</i>

━━━━━━━━━━━━━━━━━━
<b>🤖 Powered by @aditya_labs</b>
━━━━━━━━━━━━━━━━━━
"""

        await msg.delete()

        await update.message.reply_photo(
            photo=thumb,
            caption=caption,
            parse_mode="HTML"
        )
        
        await asyncio.sleep(5)
        # downloader promotion
        await update.message.reply_text(
            """
<b>╔══════════════════════════╗
        ⬇️ 𝘿𝙊𝙒𝙉𝙇𝙊𝘼𝘿 𝙔𝙊𝙐𝙏𝙐𝘽𝙀 𝙑𝙄𝘿𝙀𝙊𝙎
╚══════════════════════════╝</b>

<b>✦ Want to download this video?</b>

🚀 Use our fast YouTube downloader bot.

<b>➤ Simply send the YouTube link and download instantly.</b>

<b>🤖 Downloader Bot:</b> @YtProSaverBot

⚡ Fast • Easy • Free
""",
            parse_mode="HTML"
        )

        return

    # CHANNEL
    channel_id = get_channel_id(url)

    if channel_id:

        api = f"https://www.googleapis.com/youtube/v3/channels?part=snippet,statistics,brandingSettings,contentDetails,topicDetails&id={channel_id}&key={YOUTUBE_API_KEY}"
        r = requests.get(api).json()

        if not r["items"]:
            await msg.delete()
            return

        data = r["items"][0]
        
        name = data["snippet"]["title"]
        desc = data["snippet"]["description"]
        subs_raw = data["statistics"].get("subscriberCount", "Hidden")
        subs = format_number(subs_raw) if subs_raw != "Hidden" else "Hidden"
        videos = data["statistics"]["videoCount"]
        views = format_views(data["statistics"]["viewCount"])
        handle = data["snippet"].get("customUrl", "N/A").replace("@", "")
        created = data["snippet"]["publishedAt"][:10]
        created_dt = datetime.strptime(created, "%Y-%m-%d")
        age_days = (datetime.now() - created_dt).days
        years = age_days // 365
        months = (age_days % 365) // 30
        days = (age_days % 365) % 30
        if years > 0:
            channel_age = f"{years} Year {months} Months"
        elif months > 0:
            channel_age = f"{months} Months"
        else:
            channel_age = f"{days} Days"
        channel_link = f"https://youtube.com/@{handle}"
        uploads_playlist = data["contentDetails"]["relatedPlaylists"]["uploads"]
        latest = get_latest_videos(uploads_playlist)
        views_list = [int(v) for _, v in latest]
        avg_views = sum(views_list) // len(views_list) if views_list else 0
        avg_views_display = format_views(avg_views)
        engagement_rate = round((avg_views / int(subs_raw)) * 100, 2) if subs_raw != "Hidden" else 0
        engagement_rate = min(engagement_rate, 100)
        if subs_raw != "Hidden" and int(subs_raw) > 0:
            growth_score = round((avg_views / int(subs_raw)) * 100, 2)
            if growth_score > 10:
                growth_score = 10
        else:
            growth_score = 0
        if growth_score >= 8:
            growth_msg = "🔥 Channel Growing Fast"
        elif growth_score >= 4:
            growth_msg = "📈 Decent Growth"
        elif growth_score >= 1:
            growth_msg = "⚠️ Slow Growth"
        else:
            growth_msg = "❌ Very Low Growth"
        pfp = data["snippet"]["thumbnails"]["high"]["url"]
        banner = data.get("brandingSettings",{}).get("image",{}).get("bannerExternalUrl", pfp)
        category = data.get("topicDetails", {}).get("topicCategories", ["Unknown"])[0].split("/")[-1]
        latest_title1, latest_views1 = latest[0] if len(latest) > 0 else ("N/A", "0")
        latest_title2, latest_views2 = latest[1] if len(latest) > 1 else ("N/A", "0")
        latest_title3, latest_views3 = latest[2] if len(latest) > 2 else ("N/A", "0")
        top_video_title, top_video_views = get_top_video(uploads_playlist)

        region = data.get("brandingSettings",{}).get("channel",{}).get("country")
        if not region:
            region = "Unknown"

        caption = f"""
<b>╔══════════════════════════╗
        📺 𝙔𝙊𝙐𝙏𝙐𝘽𝙀 𝘾𝙃𝘼𝙉𝙉𝙀𝙇 𝘿𝙀𝙏𝘼𝙄𝙇𝙎
╚══════════════════════════╝</b>

<b>📛 Channel Name:</b> {name}

<b>🔗 Handle:</b> {handle}

<b>👥 Subscribers:</b> {subs}

<b>🎥 Total Videos:</b> {videos}

<b>👀 Total Views:</b> {views}

<b>🌍 Region:</b> {region}

<b>📅 Created On:</b> {created}

<b>⏳ Channel Age:</b> {channel_age}

<b>📊 Average Views:</b> {avg_views_display}

<b>🔥 Engagement Rate:</b> {engagement_rate}%

<b>📈 Growth Score:</b> {growth_score}/10
{growth_msg}

<b>📚 Category:</b> {category}

<b>🔗 Channel Link:</b>
{channel_link}

<b>🎬 Latest Videos</b>

1️⃣ {latest_title1}  
👀 Views: {format_views(latest_views1)}

2️⃣ {latest_title2}  
👀 Views: {format_views(latest_views2)}

3️⃣ {latest_title3}  
👀 Views: {format_views(latest_views3)}

<b>🏆 Highest Viewed Video (Last 50 Uploads)</b>

🎬 {top_video_title}  
👀 Views: {format_views(top_video_views)}

━━━━━━━━━━━━━━━━━━
<b>🤖 Powered by @aditya_labs</b>
━━━━━━━━━━━━━━━━━━
"""

        await msg.delete()
        
        await update.message.reply_photo(photo=banner)

        await update.message.reply_photo(
            photo=pfp,
            caption=caption,
            parse_mode="HTML"
        )
        await update.message.reply_text(
            f"<b>📝 Description</b>\n\n{desc}",
            parse_mode="HTML"
        )
        return
        await msg.delete()
        await update.message.reply_text(
            "<b>❌ Could not fetch channel or video details.</b>",
            parse_mode="HTML"
        )
async def main():
    global db_pool

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5
    )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    register_core_panel(app)

    app.add_handler(
        MessageHandler(
            ~filters.COMMAND & filters.User(ADMIN_ID),
            broadcast_message
        )
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    print("Bot running...")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # 👇 bot ko alive rakhega
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())       
