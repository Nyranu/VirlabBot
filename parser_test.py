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
        print(f"- {Table.Source} gid={Table.Gid} rows={len(Table.DataFrame)} cols={len(Table.DataFrame.columns)}")

    for GroupName in ["ИСП11-125П", "ИСП-11-125П"]:
        Source, Lessons = Parser.findScheduleForGroup(GroupName, "понедельник")
        print(f"\nГруппа {GroupName} / понедельник / источник: {Source or 'не найден'}")
        for Number, Lesson in enumerate(Lessons, 1):
            print(f"{Number}. {Lesson}")

    for TeacherName in ["Филатова", "Жабкин", "Кобякова"]:
        Lessons = Parser.findTeacherLessons(TeacherName)
        print(f"\nПреподаватель {TeacherName}: найдено {len(Lessons)}")
        for Number, Lesson in enumerate(Lessons[:10], 1):
            print(f"{Number}. {Lesson}")


if __name__ == "__main__":
    runParserTests()
