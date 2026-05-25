import os
import re
import time
from dataclasses import dataclass
from io import StringIO

import pandas as pd
import requests
from dotenv import load_dotenv


load_dotenv()


@dataclass
class SheetTable:
    Source: str
    Gid: str
    DataFrame: pd.DataFrame


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
        self.MainSheetUrl = MainSheetUrl or os.getenv("MAIN_SHEET_URL") or os.getenv("main_gs")
        self.PracticeSheetUrl = PracticeSheetUrl or os.getenv("PRACTICE_SHEET_URL") or os.getenv("PRACT_GS")
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

    def getGids(self, Url):
        Gids = set(re.findall(r"gid=(\d+)", Url or ""))
        try:
            Page = requests.get(Url, timeout=20).text
            Gids.update(re.findall(r"gid=(\d+)", Page))
            Gids.update(re.findall(r'"gid":(\d+)', Page))
        except Exception as Error:
            self.debugLog(f"Не удалось получить gid по URL: {Error}")
        if not Gids:
            Gids.add("0")
        return sorted(Gids)

    def readGoogleCsv(self, SheetId, Gid):
        CsvUrl = f"https://docs.google.com/spreadsheets/d/{SheetId}/gviz/tq?tqx=out:csv&gid={Gid}"
        Response = requests.get(CsvUrl, timeout=30)
        Response.raise_for_status()
        Text = Response.text
        if "<html" in Text[:200].lower():
            raise ValueError("Получена HTML-страница вместо CSV")
        DataFrame = pd.read_csv(StringIO(Text), header=None, dtype=str, keep_default_na=False)
        return self.cleanDf(DataFrame)

    def readGoogleHtml(self, Url):
        Result = []
        Tables = pd.read_html(Url)
        for Index, Table in enumerate(Tables):
            DataFrame = self.cleanDf(Table)
            if not DataFrame.empty:
                Result.append(SheetTable("HTML", str(Index), DataFrame))
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
        return GroupCellCount >= 2

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
            for Gid in self.getGids(Url):
                try:
                    DataFrame = self.readGoogleCsv(SheetId, Gid)
                    if not DataFrame.empty:
                        Loaded.append(SheetTable(Source, Gid, DataFrame))
                        self.debugLog(f"{Source}: загружен gid={Gid}")
                except Exception as Error:
                    self.debugLog(f"{Source}: ошибка CSV gid={Gid}: {Error}")
            if not Loaded:
                try:
                    for Table in self.readGoogleHtml(Url):
                        Loaded.append(SheetTable(Source, Table.Gid, Table.DataFrame))
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
            self.debugLog(f"{Table.Source} gid={Table.Gid}: заголовков группы={len(Headers)}")
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

    def findScheduleForGroup(self, Group, Day):
        Tables = self.loadScheduleTables()
        PracticeTables = [Table for Table in Tables if Table.Source == "Практики"]
        MainTables = [Table for Table in Tables if Table.Source == "Основное расписание"]

        PracticeLessons = self.collectGroupSchedule(PracticeTables, Group, Day)
        if PracticeLessons:
            return "Расписание практик", PracticeLessons

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

    def findTeacherLessons(self, TeacherName):
        TeacherNormalized = self.normalize(TeacherName)
        Tables = self.loadScheduleTables()
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
