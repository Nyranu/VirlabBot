from datetime import date, timedelta

from scheduleParser import ScheduleParser, SheetTable


class SyntheticILoc:
    def __init__(self, DataFrame):
        self.DataFrame = DataFrame

    def __getitem__(self, RowIndex):
        return type("SyntheticRow", (), {"tolist": lambda _Self: self.DataFrame.Rows[RowIndex][:]})()


class SyntheticIAt:
    def __init__(self, DataFrame):
        self.DataFrame = DataFrame

    def __getitem__(self, Position):
        RowIndex, ColIndex = Position
        return self.DataFrame.Rows[RowIndex][ColIndex]


class SyntheticDataFrame:
    def __init__(self, Rows):
        ColumnCount = max(len(Row) for Row in Rows)
        self.Rows = [Row + [""] * (ColumnCount - len(Row)) for Row in Rows]
        self.columns = list(range(ColumnCount))
        self.iloc = SyntheticILoc(self)
        self.iat = SyntheticIAt(self)

    def __len__(self):
        return len(self.Rows)


def runSyntheticPracticeTests(Parser):
    TargetDate = date(2026, 5, 30)

    WeekRangeDataFrame = SyntheticDataFrame([
        ["26.05-31.05"],
        ["ИСП11-125П"],
        ["понедельник"],
        ["занятие понедельника"],
        ["суббота"],
        ["учебная практика"],
    ])
    WeekRangeTable = SheetTable("Практики", "synthetic-week", "synthetic-week", WeekRangeDataFrame)
    GroupExists, Lessons = Parser.collectPracticeSchedule([WeekRangeTable], "ИСП11-125П", "суббота", TargetDate)
    if not GroupExists or Lessons != ["учебная практика"]:
        raise AssertionError(f"Недельный диапазон смешал дни: GroupExists={GroupExists}, Lessons={Lessons}")

    ExactDateDataFrame = SyntheticDataFrame([
        ["ИСП11-125П"],
        ["30.05 учебная практика"],
    ])
    ExactDateTable = SheetTable("Практики", "synthetic-date", "synthetic-date", ExactDateDataFrame)
    GroupExists, Lessons = Parser.collectPracticeSchedule([ExactDateTable], "ИСП11-125П", "суббота", TargetDate)
    if not GroupExists or Lessons != ["30.05 учебная практика"]:
        raise AssertionError(f"Точная дата занятия не найдена: GroupExists={GroupExists}, Lessons={Lessons}")

    print("Synthetic practice tests: OK")


def runParserTests():
    Parser = ScheduleParser()
    Today = date.today()

    runSyntheticPracticeTests(Parser)

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
