# bot.py - Final, with dynamic rules and free play toggle
import logging, re, json, asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest, Forbidden
import db, config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Keyboards ---
MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["🎮 Play 1v1", "💰 My Wallet"], 
    ["📋 Profile", "📜 Rules"], 
    ["🏆 Leaderboard", "🔗 Share & Earn"]
], resize_keyboard=True)
CANCEL_KEYBOARD = ReplyKeyboardMarkup([["❌ Cancel"]], resize_keyboard=True)

# --- Core Functions (Unaltered) ---
async def ensure_user(update: Update, referrer_id: int = None):
    user_obj = update.effective_user
    if not user_obj: return None
    if not await db.get_user(user_obj.id):
        await db.create_user_if_not_exists(user_obj.id, user_obj.username or user_obj.first_name, referrer_id)
    return await db.get_user(user_obj.id)
async def check_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if user_id in config.ADMINS: return True
    try:
        member = await context.bot.get_chat_member(config.CHANNEL_ID, user_id)
        if member.status in ('left', 'kicked'):
            kb = [[InlineKeyboardButton('Join Channel', url=f'https://t.me/{config.CHANNEL_USERNAME}')]]
            await update.effective_message.reply_text('বটটি ব্যবহার করতে, অনুগ্রহ করে আমাদের চ্যানেলে যোগ দিন।', reply_markup=InlineKeyboardMarkup(kb))
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking channel membership for {user_id}: {e}")
        return False

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; args = context.args
    referrer_id = int(args[0].split('_')[1]) if args and args[0].startswith('ref_') else None
    db_user = await ensure_user(update, referrer_id)
    if not db_user: return await update.message.reply_text("দুঃখিত, আপনার প্রোফাইল তৈরি করতে একটি সমস্যা হয়েছে।")
    if not await check_channel_member(update, context): return
    if db_user.get('is_registered'): await update.message.reply_text('আপনাকে স্বাগতম!', reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text('স্বাগতম! আপনার eFootball ইন-গেম নাম (IGN) পাঠান:', reply_markup=CANCEL_KEYBOARD)
        await db.set_user_state(db_user['user_id'], 'awaiting_ign')

async def main_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not user: return await update.message.reply_text("আপনার একাউন্টে সমস্যা। /start কমান্ড দিন।")
    
    txt = update.message.text.strip()
    
    if txt == "📜 Rules":
        return await rules_command(update, context)

    state, state_data = user.get('state'), user.get('state_data')
    if txt == "❌ Cancel":
        await db.set_user_state(user['user_id'], None)
        queue_entry = await db.get_from_queue(user['user_id'])
        if queue_entry:
            await db.remove_from_queue(user['user_id'])
            try: await context.bot.delete_message(config.LOBBY_CHANNEL_ID, queue_entry['lobby_message_id'])
            except Exception: pass
        return await update.message.reply_text("বাতিল করা হয়েছে।", reply_markup=MAIN_KEYBOARD)
    
    # ... (Registration, room code, withdrawal logic is unaltered) ...
    if state == 'awaiting_ign':
        await db.update_user_fields(user['user_id'], {'ingame_name': txt})
        await db.set_user_state(user['user_id'], 'awaiting_phone')
        return await update.message.reply_text('ধন্যবাদ! এখন আপনার ফোন নম্বর পাঠান:')
    if state == 'awaiting_phone':
        await db.update_user_fields(user['user_id'], {'phone_number': txt, 'is_registered': 1})
        if not user.get('welcome_given'):
            await db.adjust_balance(user['user_id'], 10.0, 'welcome_bonus', 'Welcome bonus')
            await db.update_user_fields(user['user_id'], {'welcome_given': 1})
            await update.message.reply_text('রেজিস্ট্রেশন সম্পন্ন! আপনি 10.0 টাকা বোনাস পেয়েছেন।', reply_markup=MAIN_KEYBOARD)
        else: await update.message.reply_text('রেজিস্ট্রেশন সম্পন্ন!', reply_markup=MAIN_KEYBOARD)
        referrer_id = user.get('referrer_id')
        if referrer_id and referrer_id != user['user_id']: 
            await db.adjust_balance(referrer_id, config.REFERRAL_BONUS, 'referral_bonus', f"Bonus for referring {user['user_id']}")
            try: await context.bot.send_message(referrer_id, f"🎉 অভিনন্দন! আপনার বন্ধু রেজিস্ট্রেশন করেছে। আপনি {config.REFERRAL_BONUS:.2f} TK বোনাস পেয়েছেন।")
            except Exception as e: logger.warning(f"Could not send ref bonus notification to {referrer_id}: {e}")
        return await db.set_user_state(user['user_id'], None)
    if state == 'awaiting_room_code':
        match_id = state_data
        match = await db.get_match(match_id)
        if match and match['player1_id'] == user['user_id'] and match['status'] == 'waiting_for_code':
            opponent_id = match['player2_id']; room_code = txt
            await db.set_room_code(match_id, room_code)
            match_start_text_opponent = (f"⚔️ **ম্যাচ শুরু!** ⚔️\nRoom Code: `{room_code}`\n\nখেলা শেষে, জেতার স্ক্রিনশট দিয়ে `/result {match_id}` কমান্ডটি ব্যবহার করুন।\n**সময়:** ১৫ মিনিট.")
            match_start_text_provider = (f"রুম কোড `{room_code}` প্রতিপক্ষকে পাঠানো হয়েছে। শুভকামনা!\n\nখেলা শেষে, জেতার স্ক্রিনশট দিয়ে `/result {match_id}` কমান্ডটি ব্যবহার করুন।")
            await context.bot.send_message(user['user_id'], match_start_text_provider, reply_markup=MAIN_KEYBOARD, parse_mode='Markdown')
            await context.bot.send_message(opponent_id, match_start_text_opponent, parse_mode='Markdown')
            context.job_queue.run_once(check_match_timeout, timedelta(minutes=15), data={'match_id': match_id}, name=f"timeout_{match_id}")
            return await db.set_user_state(user['user_id'], None)
    if state == 'awaiting_withdraw_amount':
        try:
            amount = float(txt); balance = user['balance']
            if amount < config.MINIMUM_WITHDRAWAL: return await update.message.reply_text(f'ন্যূনতম উইথড্র {config.MINIMUM_WITHDRAWAL:.2f} TK।')
            if amount > balance: return await update.message.reply_text(f'অপর্যাপ্ত ব্যালেন্স।')
            kb = [[InlineKeyboardButton('Bkash', callback_data='w_method_bkash')], [InlineKeyboardButton('Nagad', callback_data='w_method_nagad')]]
            await db.set_user_state(user['user_id'], 'awaiting_withdraw_method', json.dumps({'amount': amount}))
            return await update.message.reply_text('মাধ্যম নির্বাচন করুন:', reply_markup=InlineKeyboardMarkup(kb))
        except ValueError: return await update.message.reply_text('সঠিক সংখ্যা লিখুন।')
    if state == 'awaiting_withdraw_account':
        data = json.loads(state_data)
        await db.adjust_balance(user['user_id'], -data['amount'], 'withdrawal_request', f"Withdrawal request")
        req_id = await db.create_withdrawal_request(user['user_id'], data['amount'], data['method'], txt)
        await update.message.reply_text('আপনার উইথড্র অনুরোধ গ্রহণ করা হয়েছে।', reply_markup=MAIN_KEYBOARD)
        for aid in config.ADMINS:
            try: await context.bot.send_message(aid, (f"새로운 인출 요청! (ID: {req_id})\nUser: {user['user_id']} ({user.get('ingame_name')})\nAmount: {data['amount']} TK\nMethod: {data['method']}\nNumber: {txt}\n/approve_withdrawal {req_id}\n/reject_withdrawal {req_id}"))
            except Exception: pass
        return await db.set_user_state(user['user_id'], None)

    # --- Menu Button Actions (Unaltered) ---
    if txt == "🎮 Play 1v1": return await play_1v1_menu(update, context)
    if txt == "💰 My Wallet": return await wallet_menu(update, context)
    if txt == "📋 Profile": return await show_profile(update, context)
    if txt == "🏆 Leaderboard": return await show_leaderboard(update, context)
    if txt == "🔗 Share & Earn": return await share_menu(update, context)

    # ... (Deposit logic is unaltered) ...
    m = re.match(r'^([A-Za-z0-9]+)\s+(\d+(?:\.\d{1,2})?)$', txt)
    if m:
        if not await check_channel_member(update, context): return
        txid, amt = m.group(1), float(m.group(2))
        if amt < config.MINIMUM_DEPOSIT: return await update.message.reply_text(f"ন্যূনতম ডিপোজিট {config.MINIMUM_DEPOSIT:.2f} TK।")
        req_id = await db.create_deposit_request(user['user_id'], txid, amt)
        await update.message.reply_text('আপনার ডিপোজিট অনুরোধ গ্রহণ করা হয়েছে।')
        for aid in config.ADMINS:
            try: await context.bot.send_message(aid, (f"নতুন ডিপোজিট অনুরোধ! (ID: {req_id})\nUser: {user['user_id']} ({user.get('ingame_name')})\nTxID: {txid}\nAmount: {amt} TK\n/approve_deposit {req_id}"))
            except Exception: pass

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Unaltered) ...
    user = await ensure_user(update);
    if not user: return
    state, state_data = user.get('state'), user.get('state_data')
    if state == 'awaiting_screenshot':
        match_id = state_data; screenshot_id = update.message.photo[-1].file_id
        updated_match = await db.submit_screenshot(match_id, user['user_id'], screenshot_id)
        await update.message.reply_text("আপনার স্ক্রিনশট গ্রহণ করা হয়েছে।", reply_markup=MAIN_KEYBOARD)
        await db.set_user_state(user['user_id'], None)
        p1_id = updated_match['player1_id']; p2_id = updated_match['player2_id']
        opponent_id = p2_id if user['user_id'] == p1_id else p1_id
        await context.bot.send_message(opponent_id, "আপনার প্রতিপক্ষ ফলাফল জমা দিয়েছে।")
        if updated_match.get('p1_screenshot_id') and updated_match.get('p2_screenshot_id'):
            p1 = await db.get_user(p1_id); p2 = await db.get_user(p2_id)
            for admin_id in config.ADMINS:
                try:
                    kb = [[InlineKeyboardButton(f"{p1['ingame_name']} Wins", callback_data=f"admin_res_{match_id}_{p1_id}"), InlineKeyboardButton(f"{p2['ingame_name']} Wins", callback_data=f"admin_res_{match_id}_{p2_id}")]]
                    await context.bot.send_message(admin_id, f"ম্যাচ #{match_id} এর ফলাফল পর্যালোচনার জন্য প্রস্তুত।")
                    await context.bot.send_photo(admin_id, updated_match['p1_screenshot_id'], caption=f"P1 ({p1.get('ingame_name', p1_id)}) এর স্ক্রিনশট:")
                    await context.bot.send_photo(admin_id, updated_match['p2_screenshot_id'], caption=f"P2 ({p2.get('ingame_name', p2_id)}) এর স্ক্রিনশট:", reply_markup=InlineKeyboardMarkup(kb))
                except Exception as e: logger.error(f"Failed to send screenshots to admin {admin_id}: {e}")
            await context.bot.send_message(p1_id, "উভয় স্ক্রিনশট জমা হয়েছে।")
            await context.bot.send_message(p2_id, "উভয় স্ক্রিনশট জমা হয়েছে।")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Unaltered) ...
    query = update.callback_query; await query.answer(); data = query.data; user_id = query.from_user.id
    if data.startswith('play_fee_'): await handle_play_request(update, context)
    elif data.startswith('cancel_'): await cancel_search(update, context)
    elif data.startswith('admin_res_'): await admin_resolve_match(update, context)
    elif data == 'deposit': await query.message.reply_text(f"ন্যূনতম ডিপোজিট {config.MINIMUM_DEPOSIT:.2f} TK।\n\nBkash/Nagad (Send Money): `{config.BKASH_NUMBER}`\nটাকা পাঠিয়ে Transaction ID সহ এভাবে লিখুন:\n`TX123ABC 500`", parse_mode='Markdown')
    elif data == 'withdraw':
        user = await db.get_user(user_id)
        if user['balance'] < config.MINIMUM_WITHDRAWAL: return await query.message.reply_text(f'ন্যূনতম উইথড্র {config.MINIMUM_WITHDRAWAL:.2f} টাকা।')
        await db.set_user_state(user_id, 'awaiting_withdraw_amount')
        await query.message.reply_text('আপনি কত টাকা উইথড্র করতে চান?', reply_markup=CANCEL_KEYBOARD)
    elif data.startswith('w_method_'):
        user = await db.get_user(user_id)
        if user and user.get('state') == 'awaiting_withdraw_method':
            method = data.split('_')[-1]
            saved_data = json.loads(user['state_data'])
            saved_data['method'] = method
            await db.set_user_state(user_id, 'awaiting_withdraw_account', json.dumps(saved_data))
            await query.message.edit_text(f'আপনার {method.capitalize()} নম্বরটি পাঠান।')

async def handle_play_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (Unaltered matchmaking logic) ...
    query = update.callback_query; fee = float(query.data.split('_')[-1]); player1_id = query.from_user.id
    player1 = await db.get_user(player1_id)
    if not player1 or not await check_channel_member(update, context) or not player1.get('is_registered'): return await query.message.reply_text("ম্যাচ খেলার আগে /start করে রেজিস্ট্রেশন করুন ও চ্যানেলে যোগ দিন।")
    if fee > 0 and player1['balance'] < fee: return await query.message.reply_text('অপর্যাপ্ত ব্যালেন্স।')
    if await db.get_from_queue(player1_id): return await query.message.reply_text("আপনি ইতিমধ্যে একটি ম্যাচ খুঁজছেন।")
    async with db._lock:
        opponent = await db.find_opponent_in_queue(fee, player1_id)
        if opponent:
            player2_id = opponent['user_id']; await db.remove_from_queue(player2_id)
            match_id = await db.create_match(player1_id, player2_id, fee)
            player2 = await db.get_user(player2_id)
            try: await context.bot.delete_message(config.LOBBY_CHANNEL_ID, opponent['lobby_message_id'])
            except: pass
            p1_msg = f"প্রতিপক্ষ পাওয়া গেছে! আপনার ম্যাচ {player2.get('ingame_name')} এর সাথে।\n\nঅনুগ্রহ করে eFootball গেমে একটি Friend Match রুম তৈরি করে **রুম কোডটি এখানে পাঠান**।"
            p2_msg = f"প্রতিপক্ষ পাওয়া গেছে! আপনার ম্যাচ {player1.get('ingame_name')} এর সাথে। রুম কোডের জন্য অপেক্ষা করুন।"
            await context.bot.send_message(player1_id, p1_msg, reply_markup=CANCEL_KEYBOARD)
            await db.set_user_state(player1_id, 'awaiting_room_code', match_id)
            await context.bot.send_message(player2_id, p2_msg)
            await query.message.edit_text("✅ প্রতিপক্ষ পাওয়া গেছে! আপনাকে ব্যক্তিগত চ্যাটে বিস্তারিত জানানো হয়েছে।")
        else:
            fee_text = f"**এন্ট্রি ফি:** {fee:.2f} TK" if fee > 0 else "**ধরন:** Fun Match (Free)"
            lobby_text = (f"🔥 **নতুন চ্যালেঞ্জ!** 🔥\n\n**প্লেয়ার:** {player1.get('ingame_name')} (ELO: {player1.get('elo_rating', 1000)})\n{fee_text}")
            try:
                lobby_message = await context.bot.send_message(config.LOBBY_CHANNEL_ID, lobby_text, parse_mode='Markdown')
                await db.add_to_queue(player1_id, fee, lobby_message.message_id)
                await query.message.edit_text("আপনার চ্যালেঞ্জটি ম্যাচ লবিতে পোস্ট করা হয়েছে।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ বাতিল করুন", callback_data=f"cancel_{player1_id}")]]))
            except Exception as e:
                logger.error(f"Failed to post to lobby: {e}", exc_info=True)
                await query.message.edit_text("লবিতে পোস্ট করা সম্ভব হচ্ছে না।")

async def play_1v1_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'Play 1v1' মেন্যু তৈরি করে এবং ডাটাবেস থেকে ফ্রি-প্লে স্ট্যাটাস চেক করে।"""
    user = await ensure_user(update)
    if not await check_channel_member(update, context) or not user.get('is_registered'): 
        return await update.message.reply_text("অনুগ্রহ করে চ্যানেলে যোগ দিন এবং /start করে রেজিস্ট্রেশন সম্পন্ন করুন।")
    
    kb = []
    free_play_status = await db.get_setting('free_play_status')
    if free_play_status == 'on':
        kb.append([InlineKeyboardButton('🎮 Fun Match (Free)', callback_data='play_fee_0')])
    
    kb.extend([
        [InlineKeyboardButton(f'{fee} TK', callback_data=f'play_fee_{fee}') for fee in [20, 30, 50]],
        [InlineKeyboardButton(f'{fee} TK', callback_data=f'play_fee_{fee}') for fee in [100, 200, 500]]
    ])
    await update.effective_message.reply_text('ম্যাচের ধরন বা এন্ট্রি ফি নির্বাচন করুন:', reply_markup=InlineKeyboardMarkup(kb))

# ... (Unaltered functions: cancel_search, admin_resolve_match, share_menu, wallet_menu, check_match_timeout, show_profile, show_leaderboard, result_command) ...
async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; user_id = int(query.data.split('_')[-1])
    if query.from_user.id != user_id: return await query.answer("এটি আপনার চ্যালেঞ্জ নয়।", show_alert=True)
    challenge_data = await db.get_from_queue(user_id)
    if challenge_data:
        await db.remove_from_queue(user_id)
        try: await context.bot.delete_message(chat_id=config.LOBBY_CHANNEL_ID, message_id=challenge_data['lobby_message_id'])
        except: pass
        await query.message.edit_text("আপনার ম্যাচ খোঁজা বাতিল করা হয়েছে।")
    else: await query.message.edit_text("আপনি কোনো ম্যাচ খুঁজছেন না।")
async def admin_resolve_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.from_user.id not in config.ADMINS: return
    try:
        _, _, match_id, winner_id_str = query.data.split('_'); winner_id = int(winner_id_str)
        match = await db.get_match(match_id)
        if match and match['status'] != 'completed':
            success = await db.resolve_match(match_id, winner_id)
            if success:
                loser_id = match['player2_id'] if winner_id == match['player1_id'] else match['player1_id']
                winner_user = await db.get_user(winner_id)
                await context.bot.send_message(winner_id, "অভিনন্দন! আপনি ম্যাচটি জিতেছেন।")
                await context.bot.send_message(loser_id, "দুঃখিত, আপনি ম্যাচটি হেরে গেছেন।")
                final_caption = f"✅ ম্যাচ {match_id} সমাধান করা হয়েছে।\nবিজয়ী: {winner_user.get('ingame_name', winner_id)}"
                await query.edit_message_caption(caption=final_caption, reply_markup=None)
        else: await query.edit_message_caption(caption="⚠️ এই ম্যাচটি ইতিমধ্যে সমাধান করা হয়েছে।", reply_markup=None)
    except Exception as e:
        logger.error(f"Error in admin_resolve_match: {e}", exc_info=True)
        try: await query.edit_message_caption(caption="❌ একটি ত্রুটি ঘটেছে।", reply_markup=None)
        except: pass
async def share_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    share_link = f"https://t.me/{config.BOT_USERNAME}?start=ref_{user['user_id']}"
    message = f"🔗 **বন্ধুদের রেফার করুন এবং আয় করুন!**\n\n`{share_link}`"
    await update.effective_message.reply_text(message, parse_mode='Markdown')
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    kb = [[InlineKeyboardButton('➕ Deposit', callback_data='deposit'), InlineKeyboardButton('➖ Withdraw', callback_data='withdraw')]]
    await update.effective_message.reply_text(f'আপনার ব্যালেন্স: {user.get("balance", 0):.2f} TK', reply_markup=InlineKeyboardMarkup(kb))
async def check_match_timeout(context: ContextTypes.DEFAULT_TYPE):
    match_id = context.job.data['match_id']; match = await db.get_match(match_id)
    if not match or match['status'] != 'in_progress': return
    p1, p2 = match['player1_id'], match['player2_id']
    ss1, ss2 = match.get('p1_screenshot_id'), match.get('p2_screenshot_id')
    winner, loser = (None, None)
    if ss1 and not ss2: winner, loser = p1, p2
    elif ss2 and not ss1: winner, loser = p2, p1
    if winner:
        await db.resolve_match(match_id, winner)
        await context.bot.send_message(winner, f"প্রতিপক্ষ ফলাফল না দেওয়ায় আপনি বিজয়ী হয়েছেন।")
        await context.bot.send_message(loser, f"ফলাফল না দেওয়ায় আপনি পরাজিত হয়েছেন।")
    else: 
        refund_msg = "এটি একটি ফ্রি ম্যাচ ছিল।"
        if match['fee'] > 0:
            await db.adjust_balance(p1, match['fee'], 'refund', f'Match {match_id} cancelled (timeout)')
            await db.adjust_balance(p2, match['fee'], 'refund', f'Match {match_id} cancelled (timeout)')
            refund_msg = "আপনার ফি ফেরত দেওয়া হয়েছে।"
        await db.cancel_match(match_id)
        await context.bot.send_message(p1, f"ম্যাচ ({match_id}) বাতিল কারণ কোনো ফলাফল পাওয়া যায়নি। {refund_msg}")
        await context.bot.send_message(p2, f"ম্যাচ ({match_id}) বাতিল কারণ কোনো ফলাফল পাওয়া যায়নি। {refund_msg}")
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not user or not await check_channel_member(update, context): return
    txt = (f"👤 **প্রোফাইল**\n\n**IGN:** {user.get('ingame_name') or 'N/A'}\n**Balance:** {user.get('balance', 0):.2f} TK\n**Skill Rating (ELO):** {user.get('elo_rating', 1000)} 🎖️\n**Wins/Losses:** {user.get('wins',0)}/{user.get('losses',0)}")
    await update.effective_message.reply_text(txt, parse_mode='Markdown')
async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_channel_member(update, context): return
    rows = await db.get_top_wins(10)
    text = '🏆 **লিডারবোর্ড (Skill Rating অনুযায়ী)** 🏆\n\n'
    text += '\n'.join([f"**{i+1}.** {r['ingame_name'] or r['username']} — **{r['elo_rating']} ELO** ({r['wins']} wins)" for i,r in enumerate(rows)])
    await update.effective_message.reply_text(text, parse_mode='Markdown')
async def result_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await ensure_user(update)
    if not user or not context.args: return await update.message.reply_text("ব্যবহার: /result <match_id>")
    try:
        match_id = context.args[0].strip()
        match = await db.get_match(match_id)
        if not match or user['user_id'] not in [match['player1_id'], match['player2_id']]: return await update.message.reply_text("অবৈধ ম্যাচ আইডি।")
        if match['status'] != 'in_progress': return await update.message.reply_text("এই ম্যাচের ফলাফল ইতিমধ্যে প্রক্রিয়া করা হয়েছে।")
        await db.set_user_state(user['user_id'], 'awaiting_screenshot', match_id)
        await update.message.reply_text("আপনার জেতার একটি স্পষ্ট স্ক্রিনশট পাঠান।", reply_markup=CANCEL_KEYBOARD)
    except Exception as e: await update.message.reply_text(f"একটি ত্রুটি ঘটেছে: {e}")

# --- NEW/UPDATED Commands for Rules & Free Play ---
async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rules_text = await db.get_setting('rules_text')
    if rules_text:
        await update.message.reply_text(rules_text, parse_mode='Markdown')
    else:
        await update.message.reply_text("এখনও কোনো নিয়মাবলী সেট করা হয়নি। অ্যাডমিনকে /setrules কমান্ড ব্যবহার করতে বলুন।")

async def set_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in config.ADMINS: return await update.message.reply_text("এই কমান্ডটি শুধুমাত্র অ্যাডমিনদের জন্য।")
    if not context.args: return await update.message.reply_text("ব্যবহার: /setrules <আপনার নতুন নিয়মাবলী>")
    new_rules = " ".join(context.args)
    await db.set_setting('rules_text', new_rules)
    await update.message.reply_text("✅ নিয়মাবলী সফলভাবে আপডেট করা হয়েছে।")

async def free_play_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in config.ADMINS: return await update.message.reply_text("এই কমান্ডটি শুধুমাত্র অ্যাডমিনদের জন্য।")
    
    await db.set_setting('free_play_status', 'on')
    await update.message.reply_text("✅ ফ্রি-প্লে মোড চালু করা হয়েছে। সকল ব্যবহারকারীকে নোটিফিকেশন পাঠানো হচ্ছে...")

    all_user_ids = await db.get_all_user_ids()
    notification_text = "🎉 সুসংবাদ! আমাদের বটে এখন ফ্রি ম্যাচ খেলার সুবিধা চালু করা হয়েছে। আপনার স্কিল পরীক্ষা করুন এবং ELO রেটিং বাড়ান!"
    for uid in all_user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=notification_text)
            await asyncio.sleep(0.1) # To avoid hitting Telegram API rate limits
        except (Forbidden, BadRequest):
            logger.warning(f"User {uid} has blocked the bot or chat not found. Skipping.")
        except Exception as e:
            logger.error(f"Failed to send notification to {uid}: {e}")
    
    await update.message.reply_text(f"✅ {len(all_user_ids)} জন ব্যবহারকারীকে নোটিফিকেশন পাঠানো সম্পন্ন হয়েছে।")

async def free_play_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in config.ADMINS: return await update.message.reply_text("এই কমান্ডটি শুধুমাত্র অ্যাডমিনদের জন্য।")
    await db.set_setting('free_play_status', 'off')
    await update.message.reply_text("✅ ফ্রি-প্লে মোড সফলভাবে বন্ধ করা হয়েছে।")

# --- Admin Helper Commands (Unaltered) ---
async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMINS or not context.args: return
    try:
        req_id = int(context.args[0]); req = await db.get_deposit_request(req_id)
        if not req or req['status'] != 'pending': return await update.message.reply_text("অনুরোধ পাওয়া যায়নি বা ইতিমধ্যে প্রক্রিয়াকৃত।")
        await db.adjust_balance(req['user_id'], req['amount'], 'deposit', f'Deposit ID {req_id}')
        await db.update_deposit_status(req_id, 'approved')
        await update.message.reply_text(f"ডিপোজিট #{req_id} অনুমোদিত হয়েছে।")
        await context.bot.send_message(req['user_id'], f"আপনার {req['amount']:.2f} TK ডিপোজিট সফল হয়েছে।")
    except: await update.message.reply_text("ব্যবহার: /approve_deposit <id>")
async def approve_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMINS or not context.args: return
    try:
        req_id = int(context.args[0]); req = await db.get_withdrawal_request(req_id)
        if not req or req['status'] != 'pending': return await update.message.reply_text("অনুরোধ পাওয়া যায়নি।")
        await db.update_withdrawal_status(req_id, 'approved')
        await update.message.reply_text(f"উইথড্র #{req_id} অনুমোদিত হয়েছে।") 
        await context.bot.send_message(req['user_id'], f"আপনার {req['amount']:.2f} TK উইথড্র সফল হয়েছে।")
    except: await update.message.reply_text("ব্যবহার: /approve_withdrawal <id>")
async def reject_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in config.ADMINS or not context.args: return
    try:
        req_id = int(context.args[0]); req = await db.get_withdrawal_request(req_id)
        if not req or req['status'] != 'pending': return await update.message.reply_text("অনুরোধ পাওয়া যায়নি।")
        await db.adjust_balance(req['user_id'], req['amount'], 'withdrawal_rejected', f'Withdrawal ID {req_id} rejected')
        await db.update_withdrawal_status(req_id, 'rejected')
        await update.message.reply_text(f"উইথড্র #{req_id} বাতিল করা হয়েছে এবং টাকা ফেরত দেওয়া হয়েছে।") 
        await context.bot.send_message(req['user_id'], f"আপনার {req['amount']:.2f} TK উইথড্র অনুরোধ বাতিল করা হয়েছে।")
    except: await update.message.reply_text("ব্যবহার: /reject_withdrawal <id>")
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in config.ADMINS: return await update.message.reply_text("এই কমান্ডটি শুধুমাত্র অ্যাডমিনদের জন্য।")
    try:
        await context.bot.send_document(chat_id=user_id, document=open(config.LOCAL_DB, 'rb'), caption=f"✅ ডাটাবেস ব্যাকআপ ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    except FileNotFoundError: await update.message.reply_text("❌ ডাটাবেস ফাইলটি খুঁজে পাওয়া যায়নি।")
    except Exception as e: await update.message.reply_text(f"❌ একটি ত্রুটি ঘটেছে: {e}")

def main():
    db.init_db()
    app = Application.builder().token(config.TOKEN).build()
    
    # --- Registering ALL handlers ---
    # User handlers
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('result', result_command))
    app.add_handler(CommandHandler('rules', rules_command))

    # Admin handlers
    app.add_handler(CommandHandler('approve_deposit', approve_deposit))
    app.add_handler(CommandHandler('approve_withdrawal', approve_withdrawal))
    app.add_handler(CommandHandler('reject_withdrawal', reject_withdrawal))
    app.add_handler(CommandHandler('backup', backup_command))
    app.add_handler(CommandHandler('setrules', set_rules_command))
    app.add_handler(CommandHandler('freeplay_on', free_play_on_command))
    app.add_handler(CommandHandler('freeplay_off', free_play_off_command))
    
    # Message and Callback handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, main_text_handler))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    logger.info('Bot starting...')
    app.run_polling()

if __name__ == '__main__':
    main()
