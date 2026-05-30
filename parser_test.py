from datetime import date, timedelta

from scheduleParser import ScheduleParser


def runParserTests():
    Parser = ScheduleParser()
    Today = date.today()

    TestValues = [
        "26.05-31.05",
        "26.05 - 31.05",
        "26.05–31.05",
        "26.05.2026-31.05.2026",
        "10.10-11.40",
        "9.45-10.30",
        "10.35-11.20",
    ]
    for Value in TestValues:
        print(Value, "=>", Parser.parseSheetDateRange(Value))

    try:
        Tables = Parser.loadScheduleTables(Force=True)
    except Exception as Error:
        print(f"Ошибка загрузки таблиц: {Error}")
        return

    print(f"Загружено таблиц: {len(Tables)}")
    print("Источник | gid | SheetName | StartDate | EndDate")
    for Table in Tables:
        print(f"{Table.Source} | {Table.Gid} | {Table.SheetName} | {Table.StartDate} | {Table.EndDate}")

    Days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    TodayDay = Days[Today.weekday()]

    PracticeTables = Parser.filterTablesByDate(
        [Table for Table in Tables if Table.Source == "Практики"],
        Today,
    )
    GroupNormalized = Parser.normalizeGroup("ИСП11-125П")

    for Table in PracticeTables:
        DataFrame = Table.DataFrame
        print(f"\nDEBUG PRACTICE TABLE: gid={Table.Gid}, sheet={Table.SheetName}")

        for RowIndex in range(len(DataFrame)):
            RowText = Parser.rowText(DataFrame, RowIndex)
            Tokens = Parser.extractGroupTokens(RowText)

            if GroupNormalized in Tokens:
                print(f"\nGROUP FOUND AT ROW {RowIndex}: {RowText}")

                Start = max(0, RowIndex - 5)
                End = min(len(DataFrame), RowIndex + 10)

                for Index in range(Start, End):
                    print(f"{Index}: {Parser.rowText(DataFrame, Index)}")

    Source, Lessons = Parser.findScheduleForGroup("ИСП11-125П", TodayDay, Today)
    print(f"\nИСП11-125П | сегодня {TodayDay} | {Today} | {Source or 'не найден'} | {len(Lessons)}")
    for Number, Lesson in enumerate(Lessons, 1):
        print(f"{Number}. {Lesson}")

    FridayDay = "пятница"
    Monday = Today - timedelta(days=Today.weekday())
    FridayDate = Monday + timedelta(days=Days.index(FridayDay))

    Source, Lessons = Parser.findScheduleForGroup("ИСП11-125П", FridayDay, FridayDate)
    print(f"\nИСП11-125П | {FridayDay} | {FridayDate} | {Source or 'не найден'} | {len(Lessons)}")
    for Number, Lesson in enumerate(Lessons, 1):
        print(f"{Number}. {Lesson}")

    Lessons = Parser.findTeacherLessons("Филатова", Today)
    print(f"\nФилатова | {Today} | {len(Lessons)}")
    for Number, Lesson in enumerate(Lessons[:10], 1):
        print(f"{Number}. {Lesson}")


if __name__ == "__main__":
    runParserTests()
