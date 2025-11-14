#!/usr/bin/env python3
"""
বোট টেস্ট স্ক্রিপ্ট - কনফিগ এবং ডাটাবেস চেক করে
"""
import sys
import os

print("=" * 60)
print("🤖 eFootball Bot - টেস্ট স্ক্রিপ্ট")
print("=" * 60)

# ১. কনফিগ চেক
print("\n✅ ধাপ ১: কনফিগ চেক করছি...")
try:
    import config
    print(f"   ✓ TOKEN সেট আছে: {'✓' if config.TOKEN else '✗'}")
    print(f"   ✓ ADMINS: {config.ADMINS}")
    print(f"   ✓ BOT_USERNAME: {config.BOT_USERNAME}")
    print(f"   ✓ CHANNEL_ID: {config.CHANNEL_ID}")
    print("   ✓ কনফিগ ঠিক আছে!")
except Exception as e:
    print(f"   ✗ কনফিগ এরর: {e}")
    sys.exit(1)

# ২. ডাটাবেস চেক
print("\n✅ ধাপ ২: ডাটাবেস চেক করছি...")
try:
    import db
    db.init_db()
    print(f"   ✓ ডাটাবেস ইনিশিয়ালাইজ সফল")
    print(f"   ✓ DB ফাইল: {config.LOCAL_DB}")
    
    # টেস্ট ডাটা
    import asyncio
    
    async def test_db():
        total_users = await db.get_total_users()
        total_matches = await db.get_total_matches()
        print(f"   ✓ মোট ব্যবহারকারী: {total_users}")
        print(f"   ✓ মোট ম্যাচ: {total_matches}")
    
    asyncio.run(test_db())
    print("   ✓ ডাটাবেস ঠিক আছে!")
except Exception as e:
    print(f"   ✗ ডাটাবেস এরর: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ৩. মডিউল চেক
print("\n✅ ধাপ ৩: প্রয়োজনীয় মডিউল চেক করছি...")
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler
    print("   ✓ python-telegram-bot ইনস্টল আছে")
    print("   ✓ সব মডিউল ঠিক আছে!")
except Exception as e:
    print(f"   ✗ মডিউল এরর: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ সব টেস্ট পাস করেছে!")
print("=" * 60)
print("\n🚀 বোট চালাতে: python bot.py")
print("=" * 60 + "\n")
