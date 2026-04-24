import pandas as pd
import re
import os

def clean_text(val):
    if pd.isna(val): return ""
    text = str(val).strip()
    text = re.sub(r'\(?id\s*=\s*\d+\)?', '', text).strip()
    text = re.sub(r'\s+', ' ', text)
    return text.strip(", ")

# Предметы, которые идут каждую неделю
ALWAYS_WEEKLY = ["нир", "военная подготовка", "физическая культура", "физра"]
# Глобальные лекции
GLOBAL_LECTURES = [
    "архитектура эвм", "математический анализ", "квантовая теория", 
    "дифференциальные уравнения", "уравнения математической физики",
    "математическая статистика", "языки и системы программирования",
    "методы вычислений", "философия", "теория вероятностей", "численные методы", "военная подготовка"
]
# Личные предметы
PERSONAL = ["ин.яз", "английский", "англ.", "нем.", "фр.", "практика", "лаб."]

def is_shared_lecture(text):
    if not text: return False
    t = text.lower()
    if any(p in t for p in PERSONAL): return False
    if any(gl in t for gl in GLOBAL_LECTURES): return True
    if any(x in t for x in ["проф.", "доц.", "лек.", "общая"]): return True
    return False

def normalize():
    if not os.path.exists("schedule.csv"): return

    encodings = ['utf-8', 'cp1251', 'utf-16']
    df = None
    for enc in encodings:
        try:
            df = pd.read_csv("schedule.csv", header=None, encoding=enc)
            # Simple check if it looks like garbage
            if df.iat[0, 2] and isinstance(df.iat[0, 2], str) and "курс" in df.iat[0, 2].lower():
                break 
            # Re-read if it doesn't look right, but don't break yet if it's just the first one
        except:
            continue
    
    if df is None:
        try:
            df = pd.read_csv("schedule.csv", header=None) # Final fallback
        except Exception as e:
            print(f"Не удалось прочитать schedule.csv: {e}")
            return
    courses = df.iloc[0].ffill()
    majors = df.iloc[2].ffill()
    groups_raw = df.iloc[1]
    df[1] = df[1].ffill()

    day_ranges = {
        "Понедельник": (4, 19), "Вторник": (21, 36), "Среда": (38, 53),
        "Четверг": (55, 70), "Пятница": (72, 87), "Суббота": (89, 102)
    }

    normalized_data = []
    group_map = {}
    current_group = None
    
    for c in range(2, len(df.columns)):
        g_val = groups_raw[c]
        if pd.notna(g_val) and "группа" in str(g_val).lower():
            current_group = str(g_val).strip()
            current_course = str(courses[c]).strip()
            group_map[(current_course, current_group)] = [c]
        elif current_group:
            group_map[(current_course, current_group)].append(c)

    for (course, group_num), g_cols in group_map.items():
        major_text = str(majors[g_cols[0]]).strip()
        major_cols = [c for c in range(len(df.columns)) if str(courses[c]).strip() == course and str(majors[c]).strip() == major_text]

        for sub_idx, col_idx in enumerate(g_cols):
            if sub_idx > 1: break
            sub_name = str(sub_idx + 1)

            for day_name, (start_row, end_row) in day_ranges.items():
                day_has_military = False
                temp_day = []

                for row_idx in range(start_row, end_row + 1, 2):
                    time_slot = str(df.iloc[row_idx, 1]).strip()
                    if time_slot == "nan" or not time_slot: continue

                    def find_val(offset):
                        r = row_idx + offset
                        # 1. Своя ячейка
                        v = clean_text(df.iloc[r, col_idx])
                        if v: return v
                        # 2. Общая пара группы (sub1)
                        if sub_idx == 1:
                            v = clean_text(df.iloc[r, g_cols[0]])
                            if is_shared_lecture(v): return v
                        # 3. Общая лекция направления (у соседей)
                        for mc in major_cols:
                            v = clean_text(df.iloc[r, mc])
                            if is_shared_lecture(v): return v
                        return ""

                    num = find_val(0)
                    den = find_val(1)

                    if "военная подготовка" in num.lower() or "военная подготовка" in den.lower():
                        day_has_military = True

                    # Вертикальный перенос
                    if num and not den:
                        if any(x in num.lower() for x in ALWAYS_WEEKLY): den = num
                        elif is_shared_lecture(num):
                            major_empty_den = True
                            for mc in major_cols:
                                if clean_text(df.iloc[row_idx + 1, mc]): major_empty_den = False; break
                            if major_empty_den: den = num

                    if num: temp_day.append([course, group_num, sub_name, day_name, time_slot, "Числитель", num])
                    if den: temp_day.append([course, group_num, sub_name, day_name, time_slot, "Знаменатель", den])

                # Растягивание военки
                if day_has_military:
                    military_slots = ["11:30-13:05", "13:25-15:00", "15:10-16:45", "16:55-18:30", "18:40-20:00"]
                    temp_day = [d for d in temp_day if d[4] not in military_slots]
                    for slot in military_slots:
                        temp_day.append([course, group_num, sub_name, day_name, slot, "Числитель", "Военная подготовка"])
                        temp_day.append([course, group_num, sub_name, day_name, slot, "Знаменатель", "Военная подготовка"])
                
                normalized_data.extend(temp_day)

    new_df = pd.DataFrame(normalized_data, columns=["course", "group", "subgroup", "day", "time", "week_type", "subject"])
    new_df = new_df.drop_duplicates()
    new_df.to_csv("formatted_schedule.csv", index=False, encoding="utf-8-sig")
    print(f"Таблица пересобрана. Строк: {len(new_df)}")

if __name__ == "__main__":
    normalize()
