import os
import re
import time
import sqlite3
from io import StringIO
from dataclasses import dataclass

import pandas as pd
import requests
import telebot
from dotenv import load_dotenv
from telebot import types


load_dotenv()

CACHE_TTL = 600

if not os.getenv("Virlap-API-TOKEN"):
    raise RuntimeError("токена нема")

bot = telebot.TeleBot(os.getenv("Virlap-API-TOKEN"))

registration_cache = {}
schedule_cache = {
    "time": 0,
    "tables": []
}


@dataclass
class SheetTable:
    source: str
    gid: str
    df: pd.DataFrame


def db_connection():
    con = sqlite3.connect(os.getenv('DB-PATH'))
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db_connection()
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            group_name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    con.commit()
    con.close()


def get_user(telegram_id):
    con = db_connection()
    cur = con.cursor()

    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cur.fetchone()

    con.close()

    return dict(row) if row else None


def save_user(telegram_id, full_name, group_name):
    con = db_connection()
    cur = con.cursor()

    cur.execute("""
        INSERT INTO users (telegram_id, full_name, group_name)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            full_name = excluded.full_name,
            group_name = excluded.group_name,
            updated_at = CURRENT_TIMESTAMP
    """, (telegram_id, full_name, group_name))

    con.commit()
    con.close()


def normalize(text):
    text = str(text).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]", "", text)


def clean_text(text):
    return re.sub(r"\s+", " ", str(text).replace("\n", " ")).strip()


def clean_df(df):
    df = df.fillna("").astype(str)
    df = df.apply(lambda col: col.map(clean_text))
    df = df.loc[(df != "").any(axis=1), (df != "").any(axis=0)]
    return df.reset_index(drop=True)


def spreadsheet_id(url):
    found = re.search(r"/spreadsheets/d/([^/]+)", url)
    return found.group(1) if found else ""


def get_gids(url):
    gids = set(re.findall(r"gid=(\d+)", url))

    try:
        page = requests.get(url, timeout=20).text
        gids.update(re.findall(r"gid=(\d+)", page))
        gids.update(re.findall(r'"gid":(\d+)', page))
    except Exception:
        pass

    if not gids:
        gids.add("0")

    return sorted(gids)


def read_google_csv(sheet_id, gid):
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"
    response = requests.get(csv_url, timeout=30)
    response.raise_for_status()

    text = response.text

    if "<html" in text[:200].lower():
        raise ValueError("Вместо CSV получена HTML-страница")

    df = pd.read_csv(StringIO(text), header=None, dtype=str, keep_default_na=False)
    return clean_df(df)


def read_google_html(url):
    result = []
    tables = pd.read_html(url)

    for i, table in enumerate(tables):
        df = clean_df(table)

        if not df.empty:
            result.append(SheetTable("HTML", str(i), df))

    return result


def load_schedule_tables(force=False):
    now = time.time()

    if not force and schedule_cache["tables"] and now - schedule_cache["time"] < CACHE_TTL:
        return schedule_cache["tables"]

    all_tables = []

    for source, url in [
        ("Основное расписание", os.getenv("main_gs")),
        ("Практики", os.getenv("PRACT_GS"))
    ]:
        sid = spreadsheet_id(url)
        loaded_for_source = []

        for gid in get_gids(url):
            try:
                df = read_google_csv(sid, gid)

                if not df.empty:
                    loaded_for_source.append(SheetTable(source, gid, df))
            except Exception:
                pass

        if not loaded_for_source:
            try:
                for table in read_google_html(url):
                    loaded_for_source.append(SheetTable(source, table.gid, table.df))
            except Exception:
                pass

        all_tables.extend(loaded_for_source)

    schedule_cache["time"] = now
    schedule_cache["tables"] = all_tables

    return all_tables


DAYS = {
    "понедельник": "понедельник",
    "пн": "понедельник",
    "вторник": "вторник",
    "вт": "вторник",
    "среда": "среда",
    "ср": "среда",
    "четверг": "четверг",
    "чт": "четверг",
    "пятница": "пятница",
    "пт": "пятница",
    "суббота": "суббота",
    "сб": "суббота",
    "воскресенье": "воскресенье",
    "вс": "воскресенье",
}


def detect_day(text):
    low = str(text).lower().replace("ё", "е")

    for key, value in DAYS.items():
        if re.search(rf"(^|[^а-яa-z]){key}([^а-яa-z]|$)", low):
            return value

    return None


def row_text(df, row_index):
    values = [clean_text(x) for x in df.iloc[row_index].tolist()]
    values = [x for x in values if x]
    result = []

    for value in values:
        if value not in result:
            result.append(value)

    return " | ".join(result)


def cell_has_group(cell, group):
    cell_n = normalize(cell)
    group_n = normalize(group)

    if not group_n:
        return False

    return cell_n == group_n or group_n in cell_n


def find_group_columns(df, group):
    places = []

    for r in range(len(df)):
        for c in range(len(df.columns)):
            if cell_has_group(df.iat[r, c], group):
                places.append((r, c))

    return places


def make_lesson_line(df, row_index, group_col, group):
    row = [clean_text(x) for x in df.iloc[row_index].tolist()]
    subject = row[group_col] if group_col < len(row) else ""

    if not subject:
        return ""

    if cell_has_group(subject, group):
        return ""

    if detect_day(subject):
        return ""

    prefix = []

    for i in range(min(group_col, 3)):
        value = row[i]

        if value and not detect_day(value) and not cell_has_group(value, group):
            prefix.append(value)

    prefix_text = " ".join(prefix).strip()

    if prefix_text:
        return f"{prefix_text}: {subject}"

    return subject


def collect_group_schedule(tables, group, day):
    found = []
    seen = set()

    for table in tables:
        df = table.df
        group_places = find_group_columns(df, group)

        for header_row, group_col in group_places:
            current_day = None

            for r in range(header_row + 1, len(df)):
                text = row_text(df, r)
                detected = detect_day(text)

                if detected:
                    current_day = detected

                if current_day != day:
                    continue

                line = make_lesson_line(df, r, group_col, group)

                if not line:
                    continue

                key = (table.source, table.gid, r, group_col, line)

                if key not in seen:
                    seen.add(key)
                    found.append(line)

    return found


def find_schedule_for_group(group, day):
    tables = load_schedule_tables()

    main_tables = [t for t in tables if t.source == "Основное расписание"]
    practice_tables = [t for t in tables if t.source == "Практики"]

    result = collect_group_schedule(main_tables, group, day)

    if result:
        return "Основное расписание", result

    result = collect_group_schedule(practice_tables, group, day)

    if result:
        return "Расписание практик", result

    return "", []


def find_teacher_lessons(teacher):
    teacher_n = normalize(teacher)
    tables = load_schedule_tables()
    result = []
    seen = set()

    for table in tables:
        df = table.df
        current_day = None

        for r in range(len(df)):
            text = row_text(df, r)
            detected = detect_day(text)

            if detected:
                current_day = detected

            if teacher_n and teacher_n in normalize(text):
                day_text = current_day if current_day else "день не указан"
                line = f"{table.source}, {day_text}: {text}"
                key = normalize(line)

                if key not in seen:
                    seen.add(key)
                    result.append(line)

    return result[:30]


def main_menu():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📅 Расписание на день", "👨‍🏫 Поиск преподавателя")
    kb.add("👤 Мой профиль", "🔄 Обновить расписание")
    return kb


def days_keyboard():
    kb = types.InlineKeyboardMarkup()

    for day in [
        "понедельник",
        "вторник",
        "среда",
        "четверг",
        "пятница",
        "суббота"
    ]:
        kb.add(types.InlineKeyboardButton(day.capitalize(), callback_data=f"day:{day}"))

    return kb


def send_long(chat_id, text):
    if len(text) <= 3900:
        bot.send_message(chat_id, text)
        return

    for i in range(0, len(text), 3900):
        bot.send_message(chat_id, text[i:i + 3900])


@bot.message_handler(commands=["start"])
def start(message):
    user = get_user(message.from_user.id)

    if user:
        bot.send_message(
            message.chat.id,
            f"Привет, {user['full_name']}!\nТвоя группа: {user['group_name']}",
            reply_markup=main_menu()
        )
    else:
        bot.send_message(
            message.chat.id,
            "Привет! Для начала нужно зарегистрироваться.\nНапиши /reg"
        )


@bot.message_handler(commands=["help"])
def help_command(message):
    bot.send_message(
        message.chat.id,
        "Команды:\n"
        "/reg — регистрация\n"
        "/day — расписание группы на день\n"
        "/today — расписание на сегодня\n"
        "/teacher — поиск занятий преподавателя\n"
        "/profile — мой профиль\n"
        "/refresh — обновить расписание"
    )


@bot.message_handler(commands=["reg"])
def reg_start(message):
    bot.send_message(message.chat.id, "Введите ФИО:")
    bot.register_next_step_handler(message, reg_fio)


def reg_fio(message):
    full_name = clean_text(message.text)

    if not full_name or full_name.startswith("/"):
        bot.send_message(message.chat.id, "ФИО введено некорректно. Напиши /reg заново.")
        return

    registration_cache[message.from_user.id] = {"full_name": full_name}
    bot.send_message(message.chat.id, "Введите группу, например ИСП-11-125П:")
    bot.register_next_step_handler(message, reg_group)


def reg_group(message):
    group_name = clean_text(message.text)

    if not group_name or group_name.startswith("/"):
        bot.send_message(message.chat.id, "Группа введена некорректно. Напиши /reg заново.")
        return

    data = registration_cache.get(message.from_user.id)

    if not data:
        bot.send_message(message.chat.id, "Регистрация сброшена. Напиши /reg заново.")
        return

    save_user(message.from_user.id, data["full_name"], group_name)
    registration_cache.pop(message.from_user.id, None)

    bot.send_message(
        message.chat.id,
        f"Регистрация завершена!\nФИО: {data['full_name']}\nГруппа: {group_name}",
        reply_markup=main_menu()
    )


@bot.message_handler(commands=["profile"])
def profile(message):
    user = get_user(message.from_user.id)

    if not user:
        bot.send_message(message.chat.id, "Ты ещё не зарегистрирован. Напиши /reg")
        return

    bot.send_message(
        message.chat.id,
        f"ФИО: {user['full_name']}\nГруппа: {user['group_name']}"
    )


@bot.message_handler(commands=["day"])
def choose_day(message):
    user = get_user(message.from_user.id)

    if not user:
        bot.send_message(message.chat.id, "Сначала нужно зарегистрироваться. Напиши /reg")
        return

    bot.send_message(message.chat.id, "Выбери день:", reply_markup=days_keyboard())


@bot.message_handler(commands=["today"])
def today_schedule(message):
    import datetime

    user = get_user(message.from_user.id)

    if not user:
        bot.send_message(message.chat.id, "Сначала нужно зарегистрироваться. Напиши /reg")
        return

    weekday = datetime.datetime.now().weekday()
    days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    day = days[weekday]

    show_schedule(message.chat.id, user["group_name"], day)


@bot.callback_query_handler(func=lambda call: call.data.startswith("day:"))
def day_callback(call):
    user = get_user(call.from_user.id)

    if not user:
        bot.answer_callback_query(call.id, "Сначала нужно зарегистрироваться")
        bot.send_message(call.message.chat.id, "Напиши /reg")
        return

    day = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id, "Ищу расписание...")
    show_schedule(call.message.chat.id, user["group_name"], day)


def show_schedule(chat_id, group, day):
    source, lessons = find_schedule_for_group(group, day)

    if not lessons:
        bot.send_message(
            chat_id,
            f"Расписание для группы {group} на {day} не найдено.\n"
            f"Возможно, группа указана иначе или расписание находится в другой вкладке таблицы."
        )
        return

    text = f"Расписание группы {group} на {day}\nИсточник: {source}\n\n"

    for i, lesson in enumerate(lessons, 1):
        text += f"{i}. {lesson}\n"

    send_long(chat_id, text)


@bot.message_handler(commands=["teacher"])
def teacher_start(message):
    bot.send_message(message.chat.id, "Введите фамилию или ФИО преподавателя:")
    bot.register_next_step_handler(message, teacher_search)


def teacher_search(message):
    teacher = clean_text(message.text)

    if not teacher or teacher.startswith("/"):
        bot.send_message(message.chat.id, "Имя преподавателя введено некорректно. Напиши /teacher заново.")
        return

    lessons = find_teacher_lessons(teacher)

    if not lessons:
        bot.send_message(message.chat.id, f"Занятия преподавателя «{teacher}» на этой неделе не найдены.")
        return

    text = f"Занятия преподавателя «{teacher}» на этой неделе:\n\n"

    for i, lesson in enumerate(lessons, 1):
        text += f"{i}. {lesson}\n\n"

    send_long(message.chat.id, text)


@bot.message_handler(commands=["refresh"])
def refresh(message):
    load_schedule_tables(force=True)
    bot.send_message(message.chat.id, "Расписание обновлено.")


@bot.message_handler(content_types=["text"])
def text_handler(message):
    text = clean_text(message.text).lower()

    if text == "📅 расписание на день":
        choose_day(message)
    elif text == "👨‍🏫 поиск преподавателя":
        teacher_start(message)
    elif text == "👤 мой профиль":
        profile(message)
    elif text == "🔄 обновить расписание":
        refresh(message)
    else:
        bot.send_message(
            message.chat.id,
            "Я не понял команду.\n"
            "Используй меню или напиши /help"
        )


if __name__ == "__main__":
    init_db()
    load_schedule_tables(force=True)
    print("Бот запущен...")
    bot.infinity_polling(skip_pending=True)