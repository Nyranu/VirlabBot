from bot import load_schedule_tables, find_schedule_for_group, find_teacher_lessons


def run():
    tables = load_schedule_tables(force=True)
    print(f"Загружено таблиц: {len(tables)}")
    for t in tables:
        print(f"- {t.source} gid={t.gid} rows={len(t.df)} cols={len(t.df.columns)}")

    for group in ["ИСП11-125П", "ИСП-11-125П"]:
        src, lessons = find_schedule_for_group(group, "понедельник")
        print(f"\nГруппа {group} / понедельник / источник: {src or 'не найден'}")
        for i, lesson in enumerate(lessons, 1):
            print(f"{i}. {lesson}")

    for teacher in ["Филатова", "Жабкин", "Кобякова"]:
        lessons = find_teacher_lessons(teacher)
        print(f"\nПреподаватель {teacher}: найдено {len(lessons)}")
        for i, lesson in enumerate(lessons[:10], 1):
            print(f"{i}. {lesson}")


if __name__ == "__main__":
    run()
