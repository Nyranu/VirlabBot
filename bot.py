import os
import sqlite3
import datetime
import time

import telebot
from dotenv import load_dotenv
from telebot import types

from scheduleParser import ScheduleParser


load_dotenv()

BotToken = os.getenv("BOT_TOKEN")
DbPath = os.getenv("DB_PATH", "schedule_bot.db")

if not BotToken:
    raise RuntimeError("Не задан BOT_TOKEN")

Bot = telebot.TeleBot(BotToken)
RegistrationCache = {}
Parser = ScheduleParser()


def dbConnection():
    Connection = sqlite3.connect(DbPath)
    Connection.row_factory = sqlite3.Row
    return Connection


def initDb():
    Connection = dbConnection()
    Cursor = Connection.cursor()
    Cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            group_name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    Connection.commit()
    Connection.close()


def getUser(TelegramId):
    Connection = dbConnection()
    Cursor = Connection.cursor()
    Cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (TelegramId,))
    Row = Cursor.fetchone()
    Connection.close()
    return dict(Row) if Row else None


def saveUser(TelegramId, FullName, GroupName):
    Connection = dbConnection()
    Cursor = Connection.cursor()
    Cursor.execute(
        """
        INSERT INTO users (telegram_id, full_name, group_name)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            full_name = excluded.full_name,
            group_name = excluded.group_name,
            updated_at = CURRENT_TIMESTAMP
        """,
        (TelegramId, FullName, GroupName),
    )
    Connection.commit()
    Connection.close()


def mainMenu():
    Keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    Keyboard.add("📅 Расписание на день", "👨‍🏫 Поиск преподавателя")
    Keyboard.add("👤 Мой профиль", "🔄 Обновить расписание")
    return Keyboard


def daysKeyboard():
    Keyboard = types.InlineKeyboardMarkup()
    for Day in ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]:
        Keyboard.add(types.InlineKeyboardButton(Day.capitalize(), callback_data=f"day:{Day}"))
    return Keyboard


def sendLong(ChatId, Text):
    if len(Text) <= 3900:
        Bot.send_message(ChatId, Text)
        return
    for Index in range(0, len(Text), 3900):
        Bot.send_message(ChatId, Text[Index:Index + 3900])


def getDateForWeekday(Day):
    Days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    Today = datetime.date.today()
    Monday = Today - datetime.timedelta(days=Today.weekday())
    return Monday + datetime.timedelta(days=Days.index(Day))


def showSchedule(ChatId, GroupName, Day, TargetDate=None):
    Source, Lessons = Parser.findScheduleForGroup(GroupName, Day, TargetDate)
    if not Lessons:
        if Source == "Расписание практик":
            Bot.send_message(ChatId, f"Расписание практик для группы {GroupName} на {Day} не найдено.")
        else:
            Bot.send_message(ChatId, f"Расписание для группы {GroupName} на {Day} не найдено.")
        return

    Text = f"Расписание группы {GroupName} на {Day}\nИсточник: {Source}\n\n"
    for Number, Lesson in enumerate(Lessons, 1):
        Text += f"{Number}. {Lesson}\n"
    sendLong(ChatId, Text)


@Bot.message_handler(commands=["start"])
def start(Message):
    User = getUser(Message.from_user.id)
    if User:
        Bot.send_message(Message.chat.id, f"Привет, {User['full_name']}!\nТвоя группа: {User['group_name']}", reply_markup=mainMenu())
    else:
        Bot.send_message(Message.chat.id, "Привет! Для начала нужно зарегистрироваться.\nНапиши /reg")


@Bot.message_handler(commands=["help"])
def helpCommand(Message):
    Bot.send_message(
        Message.chat.id,
        "/reg — регистрация\n"
        "/day — расписание группы на день\n"
        "/today — расписание на сегодня\n"
        "/teacher — поиск занятий преподавателя\n"
        "/profile — мой профиль\n"
        "/refresh — обновить расписание\n"
        "/help — помощь",
    )


@Bot.message_handler(commands=["reg"])
def regStart(Message):
    Bot.send_message(Message.chat.id, "Введите ФИО:")
    Bot.register_next_step_handler(Message, regFio)


def regFio(Message):
    FullName = Parser.cleanText(Message.text)
    if not FullName or FullName.startswith("/"):
        Bot.send_message(Message.chat.id, "ФИО введено некорректно. Напиши /reg заново.")
        return
    RegistrationCache[Message.from_user.id] = {"FullName": FullName}
    Bot.send_message(Message.chat.id, "Введите группу, например ИСП-11-125П:")
    Bot.register_next_step_handler(Message, regGroup)


def regGroup(Message):
    GroupName = Parser.cleanText(Message.text)
    if not GroupName or GroupName.startswith("/"):
        Bot.send_message(Message.chat.id, "Группа введена некорректно. Напиши /reg заново.")
        return
    Data = RegistrationCache.get(Message.from_user.id)
    if not Data:
        Bot.send_message(Message.chat.id, "Регистрация сброшена. Напиши /reg заново.")
        return
    saveUser(Message.from_user.id, Data["FullName"], GroupName)
    RegistrationCache.pop(Message.from_user.id, None)
    Bot.send_message(Message.chat.id, f"Регистрация завершена!\nФИО: {Data['FullName']}\nГруппа: {GroupName}", reply_markup=mainMenu())


@Bot.message_handler(commands=["profile"])
def profile(Message):
    User = getUser(Message.from_user.id)
    if not User:
        Bot.send_message(Message.chat.id, "Ты ещё не зарегистрирован. Напиши /reg")
        return
    Bot.send_message(Message.chat.id, f"ФИО: {User['full_name']}\nГруппа: {User['group_name']}")


@Bot.message_handler(commands=["day"])
def chooseDay(Message):
    User = getUser(Message.from_user.id)
    if not User:
        Bot.send_message(Message.chat.id, "Сначала нужно зарегистрироваться. Напиши /reg")
        return
    Bot.send_message(Message.chat.id, "Выбери день:", reply_markup=daysKeyboard())


@Bot.message_handler(commands=["today"])
def todaySchedule(Message):
    User = getUser(Message.from_user.id)
    if not User:
        Bot.send_message(Message.chat.id, "Сначала нужно зарегистрироваться. Напиши /reg")
        return
    TargetDate = datetime.date.today()
    Days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    Day = Days[TargetDate.weekday()]
    showSchedule(Message.chat.id, User["group_name"], Day, TargetDate)


@Bot.callback_query_handler(func=lambda Call: Call.data.startswith("day:"))
def dayCallback(Call):
    User = getUser(Call.from_user.id)
    if not User:
        Bot.answer_callback_query(Call.id, "Сначала нужно зарегистрироваться")
        Bot.send_message(Call.message.chat.id, "Напиши /reg")
        return
    Day = Call.data.split(":", 1)[1]
    TargetDate = getDateForWeekday(Day)
    Bot.answer_callback_query(Call.id, "Ищу расписание...")
    showSchedule(Call.message.chat.id, User["group_name"], Day, TargetDate)


@Bot.message_handler(commands=["teacher"])
def teacherStart(Message):
    Bot.send_message(Message.chat.id, "Введите фамилию или ФИО преподавателя:")
    Bot.register_next_step_handler(Message, teacherSearch)


def teacherSearch(Message):
    Teacher = Parser.cleanText(Message.text)
    if not Teacher or Teacher.startswith("/"):
        Bot.send_message(Message.chat.id, "Имя преподавателя введено некорректно. Напиши /teacher заново.")
        return
    Lessons = Parser.findTeacherLessons(Teacher, datetime.date.today())
    if not Lessons:
        Bot.send_message(Message.chat.id, f"Занятия преподавателя «{Teacher}» на этой неделе не найдены.")
        return
    Text = f"Занятия преподавателя «{Teacher}» на этой неделе:\n\n"
    for Number, Lesson in enumerate(Lessons, 1):
        Text += f"{Number}. {Lesson}\n\n"
    sendLong(Message.chat.id, Text)


@Bot.message_handler(commands=["refresh"])
def refresh(Message):
    try:
        Parser.loadScheduleTables(Force=True)
        Bot.send_message(Message.chat.id, "Расписание обновлено.")
    except Exception as Error:
        Bot.send_message(Message.chat.id, f"Не удалось обновить расписание: {Error}")


@Bot.message_handler(content_types=["text"])
def textHandler(Message):
    Text = Parser.cleanText(Message.text).lower()
    if Text == "📅 расписание на день":
        chooseDay(Message)
    elif Text == "👨‍🏫 поиск преподавателя":
        teacherStart(Message)
    elif Text == "👤 мой профиль":
        profile(Message)
    elif Text == "🔄 обновить расписание":
        refresh(Message)
    else:
        Bot.send_message(Message.chat.id, "Я не понял команду.\nИспользуй меню или напиши /help")


if __name__ == "__main__":
    initDb()
    try:
        Parser.loadScheduleTables(Force=True)
    except Exception as Error:
        print(f"Не удалось загрузить расписание при запуске: {Error}")
    print("Бот запущен...")
    while True:
        try:
            Bot.infinity_polling(skip_pending=False)
        except Exception as Error:
            print(f"Ошибка polling, повтор через 5 секунд: {Error}")
            time.sleep(5)
