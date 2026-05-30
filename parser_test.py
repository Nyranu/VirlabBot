from datetime import date

from scheduleParser import ScheduleParser


def runParserTests():
    Parser = ScheduleParser()
    Today = date.today()
    try:
        Tables = Parser.loadScheduleTables(Force=True)
    except Exception as Error:
        print(f"Ошибка загрузки таблиц: {Error}")
        return

    print(f"Загружено таблиц: {len(Tables)}")
    print("Источник | gid | SheetName | StartDate | EndDate")
    for Table in Tables:
        print(f"{Table.Source} | {Table.Gid} | {Table.SheetName} | {Table.StartDate} | {Table.EndDate}")

    Source, Lessons = Parser.findScheduleForGroup("ИСП11-125П", "пятница", Today)
    print(f"\nИСП11-125П | пятница | {Today} | {Source or 'не найден'} | {len(Lessons)}")
    for Number, Lesson in enumerate(Lessons, 1):
        print(f"{Number}. {Lesson}")

    Lessons = Parser.findTeacherLessons("Филатова", Today)
    print(f"\nФилатова | {Today} | {len(Lessons)}")
    for Number, Lesson in enumerate(Lessons[:10], 1):
        print(f"{Number}. {Lesson}")


if __name__ == "__main__":
    runParserTests()
