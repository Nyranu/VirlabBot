import html
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()


@dataclass
class SheetTable:
    Source: str
    Gid: str
    SheetName: str
    DataFrame: pd.DataFrame
    StartDate: date | None = None
    EndDate: date | None = None


class ScheduleParser:
    Days = {
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

    def __init__(self, MainSheetUrl=None, PracticeSheetUrl=None, DebugParser=None, CacheTtl=600):
        self.MainSheetUrl = MainSheetUrl or os.getenv("MAIN_SHEET_URL")
        self.PracticeSheetUrl = PracticeSheetUrl or os.getenv("PRACTICE_SHEET_URL")
        self.DebugParser = (DebugParser if DebugParser is not None else os.getenv("DEBUG_PARSER", "false").lower() == "true")
        self.CacheTtl = CacheTtl
        self.ScheduleCache = {"Time": 0, "Tables": []}

    def debugLog(self, Message):
        if self.DebugParser:
            print(f"[DEBUG_PARSER] {Message}")

    def normalize(self, Text):
        Value = str(Text).lower().replace("ё", "е")
        return re.sub(r"[^a-zа-я0-9]", "", Value)

    def cleanText(self, Text):
        return re.sub(r"\s+", " ", str(Text).replace("\n", " ")).strip()

    def cleanDf(self, DataFrame):
        DataFrame = DataFrame.fillna("").astype(str)
        DataFrame = DataFrame.apply(lambda Col: Col.map(self.cleanText))
        DataFrame = DataFrame.loc[(DataFrame != "").any(axis=1), (DataFrame != "").any(axis=0)]
        return DataFrame.reset_index(drop=True)

    def spreadsheetId(self, Url):
        Found = re.search(r"/spreadsheets/d/([^/]+)", Url or "")
        return Found.group(1) if Found else ""

    def decodeSheetName(self, SheetName):
        Text = html.unescape(str(SheetName))
        try:
            Text = json.loads(f'"{Text}"')
        except Exception:
            pass
        return self.cleanText(Text)

    def addSheetInfo(self, SheetInfos, SeenGids, Gid, SheetName=None):
        Gid = str(Gid)
        if not Gid or Gid in SeenGids:
            return
        SheetName = self.decodeSheetName(SheetName or Gid) or Gid
        SheetInfos.append({"Gid": Gid, "SheetName": SheetName})
        SeenGids.add(Gid)

    def getSheetInfos(self, Url):
        SheetInfos = []
        SeenGids = set()

        UrlGids = re.findall(r"gid=(\d+)", Url or "")

        try:
            Page = requests.get(Url, timeout=20).text
        except Exception as Error:
            self.debugLog(f"Не удалось получить сведения о листах по URL: {Error}")
            Page = ""

        if Page:
            LinkPattern = re.compile(r'<a[^>]+href=["\'][^"\']*gid=(\d+)[^"\']*["\'][^>]*>(.*?)</a>', re.S)
            for Gid, NameHtml in LinkPattern.findall(Page):
                Name = re.sub(r"<[^>]+>", " ", NameHtml)
                self.addSheetInfo(SheetInfos, SeenGids, Gid, Name)

            Patterns = [
                (re.compile(r'"(?:gid|sheetId)"\s*:?\s*"?(\d+)"?.{0,200}?"(?:name|title)"\s*:?\s*"((?:\\.|[^"\\])*)"', re.S), True),
                (re.compile(r'"(?:name|title)"\s*:?\s*"((?:\\.|[^"\\])*)".{0,200}?"(?:gid|sheetId)"\s*:?\s*"?(\d+)"?', re.S), False),
            ]
            for Pattern, GidFirst in Patterns:
                for First, Second in Pattern.findall(Page):
                    if GidFirst:
                        Gid, SheetName = First, Second
                    else:
                        SheetName, Gid = First, Second
                    self.addSheetInfo(SheetInfos, SeenGids, Gid, SheetName)

            for Gid in re.findall(r"gid=(\d+)", Page):
                self.addSheetInfo(SheetInfos, SeenGids, Gid)
            for Gid in re.findall(r'"(?:gid|sheetId)"\s*:?\s*"?(\d+)"?', Page):
                self.addSheetInfo(SheetInfos, SeenGids, Gid)

        for Gid in UrlGids:
            self.addSheetInfo(SheetInfos, SeenGids, Gid)
        if not SheetInfos:
            self.addSheetInfo(SheetInfos, SeenGids, "0")
        return SheetInfos

    def buildDateFromParts(self, DayText, MonthText, YearText=None, FallbackYear=None):
        Day = int(DayText)
        Month = int(MonthText)
        Year = int(YearText) if YearText else (FallbackYear or date.today().year)
        if Year < 100:
            Year += 2000
        return date(Year, Month, Day)

    def findDateMatches(self, Text):
        Text = str(Text or "").lower().replace("ё", "е")
        DateToken = r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\.\d)"
        RangePattern = re.compile(rf"{DateToken}\s*[-–—]\s*{DateToken}")
        DatePattern = re.compile(DateToken)
        Matches = []
        RangeSpans = []
        InvalidRangeSpans = []

        for Match in RangePattern.finditer(Text):
            try:
                StartDate = self.buildDateFromParts(Match.group(1), Match.group(2), Match.group(3))
                EndDate = self.buildDateFromParts(Match.group(4), Match.group(5), Match.group(6), StartDate.year)
                if EndDate < StartDate and not Match.group(6):
                    EndDate = date(StartDate.year + 1, EndDate.month, EndDate.day)
            except ValueError:
                InvalidRangeSpans.append(Match.span())
                continue

            RangeSpans.append(Match.span())
            Matches.append({"start": StartDate, "end": EndDate, "is_range": True, "position": Match.start()})

        def isInsideSpan(Position, Spans):
            return any(Start <= Position < End for Start, End in Spans)

        for Match in DatePattern.finditer(Text):
            if isInsideSpan(Match.start(), RangeSpans) or isInsideSpan(Match.start(), InvalidRangeSpans):
                continue

            Before = Text[max(0, Match.start() - 10):Match.start()]
            After = Text[Match.end():Match.end() + 10]
            if re.match(r"\s*[-–—]\s*\d{1,2}\.\d{1,2}", After):
                continue
            if re.search(r"\d{1,2}\.\d{1,2}\s*[-–—]\s*$", Before):
                continue

            try:
                FoundDate = self.buildDateFromParts(Match.group(1), Match.group(2), Match.group(3))
            except ValueError:
                continue
            Matches.append({"start": FoundDate, "end": FoundDate, "is_range": False, "position": Match.start()})

        return sorted(Matches, key=lambda Item: Item["position"])

    def parseSheetDateRange(self, SheetName):
        Matches = self.findDateMatches(SheetName)
        if not Matches:
            return None, None

        for Match in Matches:
            if Match["is_range"]:
                return Match["start"], Match["end"]

        FirstDate = Matches[0]["start"]
        return FirstDate, FirstDate

    def parseTableDateRange(self, DataFrame):
        Parts = []
        if DataFrame is None or DataFrame.empty:
            return None, None

        for RowIndex in range(min(15, len(DataFrame))):
            for ColIndex in range(len(DataFrame.columns)):
                Value = self.cleanText(DataFrame.iat[RowIndex, ColIndex])
                if Value:
                    Parts.append(Value)

        Matches = self.findDateMatches(" ".join(Parts))
        if not Matches:
            return None, None

        for Match in Matches:
            if Match["is_range"]:
                return Match["start"], Match["end"]

        FirstDate = Matches[0]["start"]
        WeekStart = FirstDate - timedelta(days=FirstDate.weekday())
        WeekEnd = WeekStart + timedelta(days=6)
        return WeekStart, WeekEnd

    def filterTablesByDate(self, Tables, TargetDate):
        Tables = list(Tables or [])
        TargetDate = TargetDate or date.today()
        self.debugLog(f"TargetDate: {TargetDate}")
        Matched = []
        Undated = []
        DatedCount = 0

        for Table in Tables:
            if Table.StartDate and Table.EndDate:
                DatedCount += 1
                if Table.StartDate <= TargetDate <= Table.EndDate:
                    self.debugLog(f"лист подошёл по дате: {Table.Source} gid={Table.Gid} sheet={Table.SheetName} date={Table.StartDate}-{Table.EndDate}")
                    Matched.append(Table)
                else:
                    self.debugLog(f"лист пропущен по дате: {Table.Source} gid={Table.Gid} sheet={Table.SheetName} date={Table.StartDate}-{Table.EndDate}")
            else:
                Undated.append(Table)

        if not Tables:
            return []
        if Matched:
            return Matched
        if DatedCount:
            self.debugLog(f"Точный лист по дате {TargetDate} не найден, fallback на листы без даты: {len(Undated)}")
            return Undated

        self.debugLog(
            f"Датированные листы не найдены, fallback на последний лист источника: "
            f"{Tables[-1].Source} gid={Tables[-1].Gid} sheet={Tables[-1].SheetName}"
        )
        return [Tables[-1]]

    def readGoogleCsv(self, SheetId, Gid):
        CsvUrl = f"https://docs.google.com/spreadsheets/d/{SheetId}/gviz/tq?tqx=out:csv&gid={Gid}"
        Response = requests.get(CsvUrl, timeout=30)
        Response.raise_for_status()
        Text = Response.text
        if "<html" in Text[:200].lower():
            raise ValueError("Получена HTML-страница вместо CSV")
        DataFrame = pd.read_csv(StringIO(Text), header=None, dtype=str, keep_default_na=False)
        return self.cleanDf(DataFrame)

    def readGoogleHtml(self, Url, Source):
        Result = []
        Tables = pd.read_html(Url)
        for Index, Table in enumerate(Tables):
            DataFrame = self.cleanDf(Table)
            if not DataFrame.empty:
                SheetName = str(Index)
                StartDate, EndDate = self.parseSheetDateRange(SheetName)
                self.debugLog(f"дата из названия листа: {Source}, gid={Index}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
                if not StartDate or not EndDate:
                    StartDate, EndDate = self.parseTableDateRange(DataFrame)
                    self.debugLog(f"дата из содержимого таблицы: {Source}, gid={Index}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
                Result.append(SheetTable(Source, str(Index), SheetName, DataFrame, StartDate, EndDate))
                self.debugLog(f"загружен лист: {Source}, gid={Index}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
        return Result

    def normalizeGroup(self, Value):
        Text = str(Value).upper().replace("Ё", "Е")
        Text = re.sub(r"\s+", "", Text)
        Text = Text.replace("—", "-").replace("–", "-")
        Text = re.sub(r"^([А-ЯA-Z]{2,6})-?(\d{1,2})-?(\d{2,4}[А-ЯA-Z]?)$", r"\1-\2-\3", Text)
        return Text

    def extractGroupTokens(self, Text):
        Raw = str(Text).upper().replace("Ё", "Е").replace("\n", " ")
        Raw = Raw.replace("—", "-").replace("–", "-")
        Matches = re.findall(r"[А-ЯA-Z]{2,6}\s*-?\s*\d{1,2}\s*-?\s*\d{2,4}[А-ЯA-Z]?", Raw)
        return {self.normalizeGroup(Item) for Item in Matches if self.normalizeGroup(Item)}

    def detectDay(self, Text):
        Low = str(Text).lower().replace("ё", "е")
        for Key, Value in self.Days.items():
            if re.search(rf"(^|[^а-яa-z]){Key}([^а-яa-z]|$)", Low):
                return Value
        return None

    def rowText(self, DataFrame, RowIndex):
        Values = [self.cleanText(Item) for Item in DataFrame.iloc[RowIndex].tolist()]
        Values = [Item for Item in Values if Item]
        Unique = []
        for Value in Values:
            if Value not in Unique:
                Unique.append(Value)
        return " | ".join(Unique)

    def isHeaderLikeRow(self, DataFrame, RowIndex):
        TokensPerCell = [self.extractGroupTokens(DataFrame.iat[RowIndex, Col]) for Col in range(len(DataFrame.columns))]
        GroupCellCount = sum(1 for Tokens in TokensPerCell if Tokens)
        GroupTokenCount = sum(len(Tokens) for Tokens in TokensPerCell)
        return GroupCellCount >= 2 or GroupTokenCount >= 2

    def findGroupHeaders(self, DataFrame, Group):
        GroupNormalized = self.normalizeGroup(Group)
        Headers = []
        if not GroupNormalized:
            return Headers
        for RowIndex in range(len(DataFrame)):
            HeaderLike = self.isHeaderLikeRow(DataFrame, RowIndex)
            for ColIndex in range(len(DataFrame.columns)):
                Tokens = self.extractGroupTokens(DataFrame.iat[RowIndex, ColIndex])
                if GroupNormalized in Tokens and HeaderLike:
                    Headers.append((RowIndex, ColIndex))
        return Headers

    def hasGroupInTables(self, Tables, Group):
        GroupNormalized = self.normalizeGroup(Group)
        if not GroupNormalized:
            return False

        for Table in Tables:
            DataFrame = Table.DataFrame
            for RowIndex in range(len(DataFrame)):
                for ColIndex in range(len(DataFrame.columns)):
                    Tokens = self.extractGroupTokens(DataFrame.iat[RowIndex, ColIndex])
                    if GroupNormalized in Tokens:
                        self.debugLog(
                            f"группа {GroupNormalized} найдена в {Table.Source} "
                            f"gid={Table.Gid} sheet={Table.SheetName}"
                        )
                        return True
        return False

    def loadScheduleTables(self, Force=False):
        Now = time.time()
        if not Force and self.ScheduleCache["Tables"] and Now - self.ScheduleCache["Time"] < self.CacheTtl:
            return self.ScheduleCache["Tables"]

        if not self.MainSheetUrl and not self.PracticeSheetUrl:
            raise RuntimeError("Не заданы MAIN_SHEET_URL и PRACTICE_SHEET_URL в .env")

        AllTables = []
        for Source, Url in [("Практики", self.PracticeSheetUrl), ("Основное расписание", self.MainSheetUrl)]:
            if not Url:
                continue
            SheetId = self.spreadsheetId(Url)
            Loaded = []
            for SheetInfo in self.getSheetInfos(Url):
                Gid = SheetInfo["Gid"]
                SheetName = SheetInfo["SheetName"]
                StartDate, EndDate = self.parseSheetDateRange(SheetName)
                self.debugLog(f"дата из названия листа: {Source}, gid={Gid}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
                try:
                    DataFrame = self.readGoogleCsv(SheetId, Gid)
                    if not StartDate or not EndDate:
                        StartDate, EndDate = self.parseTableDateRange(DataFrame)
                        self.debugLog(f"дата из содержимого таблицы: {Source}, gid={Gid}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
                    if not DataFrame.empty:
                        Loaded.append(SheetTable(Source, Gid, SheetName, DataFrame, StartDate, EndDate))
                        self.debugLog(f"загружен лист: {Source}, gid={Gid}, SheetName={SheetName}, StartDate={StartDate}, EndDate={EndDate}")
                except Exception as Error:
                    self.debugLog(f"{Source}: ошибка CSV gid={Gid} sheet={SheetName}: {Error}")
            if not Loaded:
                try:
                    for Table in self.readGoogleHtml(Url, Source):
                        Loaded.append(Table)
                    self.debugLog(f"{Source}: fallback HTML таблиц={len(Loaded)}")
                except Exception as Error:
                    self.debugLog(f"{Source}: ошибка HTML: {Error}")
            AllTables.extend(Loaded)
            self.debugLog(f"{Source}: листов={len(Loaded)}")

        self.ScheduleCache["Time"] = Now
        self.ScheduleCache["Tables"] = AllTables
        self.debugLog(f"Всего таблиц загружено: {len(AllTables)}")
        return AllTables

    def makeLessonLine(self, DataFrame, RowIndex, GroupCol, GroupName):
        Row = [self.cleanText(Item) for Item in DataFrame.iloc[RowIndex].tolist()]
        Subject = Row[GroupCol] if GroupCol < len(Row) else ""
        if not Subject or self.detectDay(Subject):
            return "", ""

        LeftParts = [Val for Val in Row[max(0, GroupCol - 3):GroupCol] if Val and not self.detectDay(Val)]
        TimePart = " ".join(LeftParts).strip()
        Line = f"{TimePart}: {Subject}" if TimePart else Subject
        return TimePart, Line

    def collectGroupSchedule(self, Tables, Group, Day):
        Found = []
        Seen = set()
        DedupRemoved = 0
        for Table in Tables:
            DataFrame = Table.DataFrame
            Headers = self.findGroupHeaders(DataFrame, Group)
            self.debugLog(f"{Table.Source} gid={Table.Gid} sheet={Table.SheetName}: заголовков группы={len(Headers)}")
            for HeaderRow, GroupCol in Headers:
                CurrentDay = None
                for RowIndex in range(HeaderRow + 1, len(DataFrame)):
                    if self.isHeaderLikeRow(DataFrame, RowIndex):
                        break
                    RowCombined = self.rowText(DataFrame, RowIndex)
                    DetectedDay = self.detectDay(RowCombined)
                    if DetectedDay:
                        CurrentDay = DetectedDay
                        continue
                    if CurrentDay != Day:
                        continue
                    TimePart, LessonLine = self.makeLessonLine(DataFrame, RowIndex, GroupCol, Group)
                    if not LessonLine:
                        continue
                    SubjectNormalized = self.normalize(LessonLine)
                    Key = f"{CurrentDay}|{self.normalizeGroup(Group)}|{self.normalize(TimePart)}|{SubjectNormalized}"
                    if Key in Seen:
                        DedupRemoved += 1
                        continue
                    Seen.add(Key)
                    Found.append(LessonLine)
        self.debugLog(f"Группа={Group} день={Day}: найдено={len(Found)} дублей_удалено={DedupRemoved}")
        return Found

    def findScheduleForGroup(self, Group, Day, TargetDate=None):
        TargetDate = TargetDate or date.today()
        Tables = self.loadScheduleTables()
        PracticeTables = self.filterTablesByDate([Table for Table in Tables if Table.Source == "Практики"], TargetDate)
        MainTables = self.filterTablesByDate([Table for Table in Tables if Table.Source == "Основное расписание"], TargetDate)

        PracticeGroupExists = self.hasGroupInTables(PracticeTables, Group)
        PracticeLessons = self.collectGroupSchedule(PracticeTables, Group, Day)
        if PracticeLessons:
            return "Расписание практик", PracticeLessons
        if PracticeGroupExists:
            return "Расписание практик", []

        MainLessons = self.collectGroupSchedule(MainTables, Group, Day)
        if MainLessons:
            return "Основное расписание", MainLessons

        return "", []

    def resolveGroupsForColumn(self, DataFrame, RowIndex, ColIndex):
        Found = []
        for UpRow in range(RowIndex, -1, -1):
            Tokens = self.extractGroupTokens(DataFrame.iat[UpRow, ColIndex])
            if Tokens:
                Found = sorted(Tokens)
                if self.isHeaderLikeRow(DataFrame, UpRow):
                    break
        return Found

    def findTeacherLessons(self, TeacherName, TargetDate=None):
        TargetDate = TargetDate or date.today()
        TeacherNormalized = self.normalize(TeacherName)
        AllTables = self.loadScheduleTables()
        PracticeTables = self.filterTablesByDate([Table for Table in AllTables if Table.Source == "Практики"], TargetDate)
        MainTables = self.filterTablesByDate([Table for Table in AllTables if Table.Source == "Основное расписание"], TargetDate)
        Tables = PracticeTables + MainTables
        Result = []
        Seen = set()
        DedupRemoved = 0

        for Table in Tables:
            DataFrame = Table.DataFrame
            CurrentDay = None
            for RowIndex in range(len(DataFrame)):
                RowValues = [self.cleanText(Item) for Item in DataFrame.iloc[RowIndex].tolist()]
                RowCombined = " | ".join([Item for Item in RowValues if Item])
                DetectedDay = self.detectDay(RowCombined)
                if DetectedDay:
                    CurrentDay = DetectedDay
                    continue
                if self.isHeaderLikeRow(DataFrame, RowIndex):
                    continue

                for ColIndex, Cell in enumerate(RowValues):
                    if not Cell:
                        continue
                    CellNormalized = self.normalize(Cell)
                    if not TeacherNormalized or TeacherNormalized not in CellNormalized:
                        continue

                    GroupList = self.resolveGroupsForColumn(DataFrame, RowIndex, ColIndex)
                    if len(GroupList) == 1:
                        GroupPart = f"группа: {GroupList[0]}"
                        GroupForKey = GroupList[0]
                    elif len(GroupList) > 1:
                        GroupPart = f"группы: {', '.join(GroupList)}"
                        GroupForKey = ",".join(GroupList)
                    else:
                        GroupPart = "группа не определена"
                        GroupForKey = ""

                    LeftParts = [Val for Val in RowValues[max(0, ColIndex - 3):ColIndex] if Val and not self.detectDay(Val)]
                    TimePart = " ".join(LeftParts).strip()
                    DayPart = CurrentDay or "день не указан"

                    Key = f"{DayPart}|{self.normalizeGroup(GroupForKey)}|{self.normalize(TimePart)}|{self.normalize(Cell)}"
                    if Key in Seen:
                        DedupRemoved += 1
                        continue
                    Seen.add(Key)

                    Header = f"{Table.Source} | {DayPart} | {GroupPart} | {TimePart}".rstrip(" |")
                    Result.append(f"{Header}\n{Cell}")

        self.debugLog(f"Преподаватель={TeacherName}: найдено={len(Result)} дублей_удалено={DedupRemoved}")
        return Result[:30]
