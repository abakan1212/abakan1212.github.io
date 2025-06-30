#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram Referral Course Bot with gamification.

Setup:
    python -m venv venv && venv\Scripts\Activate.ps1   (Windows)
    pip install aiogram==3.4 aiosqlite==0.20
    set BOT_TOKEN=...  &&  set ADMIN_CHAT=@mychannel
    python main.py

If PowerShell blocks scripts, run:
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F
from aiogram.enums.parse_mode import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, PollAnswer)
import aiosqlite

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT = os.getenv("ADMIN_CHAT")  # ID or @username
DB_PATH = "bot.db"

# TODO: replace lesson links and file IDs
LESSON_URL = {
    1: "https://example.com/lesson1",
    2: "https://example.com/lesson2",
    3: "https://example.com/lesson3",
}
STICKER_ID = "STICKER_FILE_ID"
PDF_FILE_ID = "PDF_FILE_ID"

LEVELS = {
    1: (0, "Novice"),
    2: (500, "Pro"),
    3: (1000, "Guru"),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    tg_id INTEGER PRIMARY KEY,
    referrer_id INTEGER,
    joined_at TEXT
);
CREATE TABLE IF NOT EXISTS stats(
    tg_id INTEGER PRIMARY KEY,
    invites INTEGER DEFAULT 0,
    xp INTEGER DEFAULT 0,
    streak INTEGER DEFAULT 0,
    last_seen TEXT,
    lvl INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS user_badges(
    tg_id INTEGER,
    badge TEXT,
    UNIQUE(tg_id, badge)
);
"""

poll_map: dict[str, int] = {}


def level_for_xp(xp: int) -> int:
    if xp >= 1000:
        return 3
    if xp >= 500:
        return 2
    return 1


async def init_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    await db.commit()
    return db


auto_post_task: asyncio.Task | None = None


async def register_user(db: aiosqlite.Connection, user_id: int, referrer: int | None, bot: Bot) -> None:
    async with db.execute("SELECT tg_id FROM users WHERE tg_id=?", (user_id,)) as cur:
        if await cur.fetchone():
            return
    await db.execute(
        "INSERT INTO users(tg_id, referrer_id, joined_at) VALUES (?,?,?)",
        (user_id, referrer, datetime.utcnow().isoformat()),
    )
    await db.execute(
        "INSERT INTO stats(tg_id, invites, xp, streak, last_seen, lvl) VALUES(?,?,?,?,?,1)",
        (user_id, 0, 0, 0, date.today().isoformat()),
    )
    await db.commit()
    await add_xp(db, user_id, 100)  # lesson 1 XP
    await give_badge(db, user_id, "Explorer")
    if referrer and referrer != user_id:
        await db.execute(
            "UPDATE stats SET invites=invites+1, xp=xp+50 WHERE tg_id=?",
            (referrer,),
        )
        await db.commit()
        await check_mystery_box(db, referrer, bot)


async def add_xp(db: aiosqlite.Connection, user_id: int, amount: int) -> None:
    async with db.execute("SELECT xp FROM stats WHERE tg_id=?", (user_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return
    xp = row[0] + amount
    lvl = level_for_xp(xp)
    await db.execute(
        "UPDATE stats SET xp=?, lvl=? WHERE tg_id=?",
        (xp, lvl, user_id),
    )
    await db.commit()


async def give_badge(db: aiosqlite.Connection, user_id: int, badge: str) -> bool:
    try:
        await db.execute(
            "INSERT INTO user_badges(tg_id, badge) VALUES(?,?)",
            (user_id, badge),
        )
        await db.commit()
        return True
    except aiosqlite.IntegrityError:
        return False


async def check_mystery_box(db: aiosqlite.Connection, user_id: int, bot: Bot) -> None:
    async with db.execute(
        "SELECT invites FROM stats WHERE tg_id=?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row or row[0] < 3:
        return
    awarded = await give_badge(db, user_id, "MysteryBox")
    if not awarded:
        return
    choice = random.choice([1, 2, 3])
    if choice == 1:
        await add_xp(db, user_id, 50)
        await bot.send_message(user_id, "Mystery box: +50 XP boost!")
    elif choice == 2:
        await bot.send_sticker(user_id, STICKER_ID)
    else:
        await bot.send_document(user_id, PDF_FILE_ID)


async def update_daily(db: aiosqlite.Connection, user_id: int) -> None:
    async with db.execute(
        "SELECT streak, last_seen FROM stats WHERE tg_id=?", (user_id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return
    streak, last_seen = row
    today = date.today()
    last = date.fromisoformat(last_seen) if last_seen else None
    if last is None or today > last:
        if last and (today - last).days == 1:
            streak += 1
        else:
            streak = 1
        await db.execute(
            "UPDATE stats SET streak=?, last_seen=? WHERE tg_id=?",
            (streak, today.isoformat(), user_id),
        )
        await db.commit()
        await add_xp(db, user_id, 20)
        if streak % 7 == 0:
            await add_xp(db, user_id, 100)


async def fetch_stats(db: aiosqlite.Connection, user_id: int) -> aiosqlite.Row | None:
    async with db.execute(
        "SELECT invites, xp, streak, last_seen, lvl FROM stats WHERE tg_id=?",
        (user_id,),
    ) as cur:
        return await cur.fetchone()


def progress_bar(xp: int) -> tuple[str, int]:
    lvl = level_for_xp(xp)
    start = LEVELS[lvl][0]
    end = LEVELS.get(lvl + 1, (start,))[0]
    if end == start:
        pct = 1
    else:
        pct = (xp - start) / (end - start)
    filled = int(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return bar, lvl


async def progress_message(db: aiosqlite.Connection, user_id: int, bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    row = await fetch_stats(db, user_id)
    if not row:
        return "No data", InlineKeyboardMarkup(inline_keyboard=[])
    invites, xp, _, _, lvl = row
    bar, lvl = progress_bar(xp)
    name = LEVELS[lvl][1]
    lessons = [f"[Lesson 1]({LESSON_URL[1]})"]
    if invites >= 2:
        lessons.append(f"[Lesson 2]({LESSON_URL[2]})")
    if invites >= 5:
        lessons.append(f"[Lesson 3]({LESSON_URL[3]})")
    text = (
        f"Invites: {invites}\n"
        f"XP: {xp}\n"
        f"Level {lvl} – {name} {bar}\n"
        f"Lessons: {' | '.join(lessons)}"
    )
    url = f"https://t.me/{bot.username}?start={user_id}"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Refresh", callback_data="check")],
            [InlineKeyboardButton(text="Referral link", url=url)],
        ]
    )
    return text, markup


async def send_leaderboard(db: aiosqlite.Connection, bot: Bot, chat_id: str | int) -> None:
    rows = await db.execute_fetchall(
        "SELECT tg_id, invites FROM stats ORDER BY invites DESC, tg_id LIMIT 5"
    )
    text = "\U0001F3C6 Top 5 by invites:\n"
    for i, (uid, invites) in enumerate(rows, 1):
        text += f"{i}. <a href=\"tg://user?id={uid}\">User {uid}</a> - {invites}\n"
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


async def auto_post_loop(db: aiosqlite.Connection, bot: Bot) -> None:
    while True:
        await asyncio.sleep(86400)
        if ADMIN_CHAT:
            await send_leaderboard(db, bot, ADMIN_CHAT)


async def on_startup(bot: Bot, db: aiosqlite.Connection) -> None:
    if ADMIN_CHAT:
        await send_leaderboard(db, bot, ADMIN_CHAT)


async def cmd_start_handler(message: Message, db: aiosqlite.Connection, bot: Bot) -> None:
    args = message.text.split(maxsplit=1)
    referrer = None
    if len(args) == 2 and args[1].isdigit():
        referrer = int(args[1])
    await register_user(db, message.from_user.id, referrer, bot)
    await update_daily(db, message.from_user.id)
    await check_mystery_box(db, message.from_user.id, bot)
    text = f"Lesson 1: {LESSON_URL[1]}"
    progress_text, markup = await progress_message(db, message.from_user.id, bot)
    await message.answer(text)
    await message.answer(progress_text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def cmd_menu(message: Message, db: aiosqlite.Connection, bot: Bot) -> None:
    await update_daily(db, message.from_user.id)
    text, markup = await progress_message(db, message.from_user.id, bot)
    await message.answer(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)


async def cmd_top(message: Message, db: aiosqlite.Connection, bot: Bot) -> None:
    await send_leaderboard(db, bot, message.chat.id)


async def cmd_quiz(message: Message, bot: Bot) -> None:
    poll = await bot.send_poll(
        chat_id=message.chat.id,
        question="What is the capital of France?",
        options=["Paris", "London", "Berlin", "Rome"],
        correct_option_id=0,
        is_anonymous=False,
    )
    poll_map[poll.poll.id] = message.from_user.id


async def poll_answer_handler(
    poll: PollAnswer, db: aiosqlite.Connection, bot: Bot
) -> None:
    user_id = poll.user.id
    creator = poll_map.get(poll.poll_id)
    if creator != user_id:
        return
    if poll.option_ids == [0]:
        await add_xp(db, user_id, 50)
        awarded = await give_badge(db, user_id, "Brainiac")
        text = "Correct! +50 XP"
        if awarded:
            text += " and Brainiac badge!"
    else:
        text = "Wrong answer."
    await bot.send_message(user_id, text)
    poll_map.pop(poll.poll_id, None)


async def cb_check_handler(
    callback: CallbackQuery, db: aiosqlite.Connection, bot: Bot
) -> None:
    await update_daily(db, callback.from_user.id)
    text, markup = await progress_message(db, callback.from_user.id, bot)
    await callback.message.edit_text(text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN env var missing")
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    db = await init_db()

    dp.startup.register(lambda: on_startup(bot, db))

    dp.message.register(cmd_start_handler, CommandStart())
    dp.message.register(cmd_menu, Command("menu"))
    dp.message.register(cmd_menu, F.text == "\u2705 Refresh")
    dp.message.register(cmd_top, Command("top"))
    dp.message.register(cmd_quiz, Command("quiz"))

    dp.callback_query.register(cb_check_handler, F.data == "check")
    dp.poll_answer.register(poll_answer_handler)

    global auto_post_task
    auto_post_task = asyncio.create_task(auto_post_loop(db, bot))

    await dp.start_polling(bot, db=db, bot=bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if auto_post_task:
            auto_post_task.cancel()
