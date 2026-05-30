from datetime import date

from scheduleParser import ScheduleParser


def runParserTests():
    Parser = ScheduleParser()
    try:
        Tables = Parser.loadScheduleTables(Force=True)
    except Exception as Error:
        print(f"Ошибка загрузки таблиц: {Error}")
        return

    print(f"Загружено таблиц: {len(Tables)}")
    for Table in Tables:
        DateRange = f"{Table.StartDate}-{Table.EndDate}" if Table.StartDate and Table.EndDate else "не определена"
        print(
            f"- {Table.Source} gid={Table.Gid} sheet={Table.SheetName} "
            f"date={DateRange} rows={len(Table.DataFrame)} cols={len(Table.DataFrame.columns)}"
        )

    Today = date.today()
    for GroupName in ["ИСП11-125П", "ИСП-11-125П"]:
        Source, Lessons = Parser.findScheduleForGroup(GroupName, "понедельник", Today)
        print(f"\nГруппа {GroupName} / понедельник / дата {Today} / источник: {Source or 'не найден'}")
        for Number, Lesson in enumerate(Lessons, 1):
            print(f"{Number}. {Lesson}")

    for TeacherName in ["Филатова", "Жабкин", "Кобякова"]:
        Lessons = Parser.findTeacherLessons(TeacherName, Today)
        print(f"\nПреподаватель {TeacherName} / дата {Today}: найдено {len(Lessons)}")
        for Number, Lesson in enumerate(Lessons[:10], 1):
            print(f"{Number}. {Lesson}")


if __name__ == "__main__":
    runParserTests()
