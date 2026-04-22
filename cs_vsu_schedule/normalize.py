import pandas as pd
import re
import os

def clean_text(val):
    if pd.isna(val) or str(val).lower() == 'nan': return ""
    text = str(val).strip()
    # Remove things like (id=1234)
    text = re.sub(r'\(?id\s*=\s*\d+\)?', '', text).strip()
    text = re.sub(r'\s+', ' ', text)
    # Remove leading/trailing punctuation except for common ones in subject names
    return text.strip(", ")

def normalize():
    excel_file = "Расписание_разделенное.xlsx"
    if not os.path.exists(excel_file):
        print(f"Ошибка: файл {excel_file} не найден.")
        return

    xl = pd.ExcelFile(excel_file)
    normalized_data = []

    for sheet_name in xl.sheet_names:
        # Обрабатываем только листы с расписанием
        if "Расписание" not in sheet_name:
            continue
        
        print(f"Обработка листа: {sheet_name}")
        df = xl.parse(sheet_name, header=None)
        
        if len(df) < 5:
            continue

        # Пытаемся найти строку, где начинаются данные (где в первой колонке "Понедельник" или "Пнд")
        start_row = 4 # По умолчанию
        for i in range(len(df)):
            val = str(df.iloc[i, 0]).strip().lower()
            if "понедельник" in val or "пнд" in val:
                start_row = i
                break

        # Строка 0: Курсы (1 курс, 2 курс...)
        courses = df.iloc[0].ffill()
        # Строка 1: Группы (17 группа, 18 группа...)
        groups_raw = df.iloc[1]
        
        # Подготовим маппинг колонок
        group_subgroup_map = {} # (column_index) -> (course, group, subgroup)
        last_group_name = None
        subgroup_counter = 1
        
        for c in range(2, len(df.columns)):
            course_val = clean_text(courses[c])
            group_val = clean_text(groups_raw[c])
            
            if not group_val:
                continue
            
            # Очистка названия группы от лишних слов, если нужно, 
            # но пользователь просил "правильно парсить", так что оставим как есть, только уберем лишние пробелы
            if group_val == last_group_name:
                subgroup_counter += 1
            else:
                subgroup_counter = 1
                last_group_name = group_val
            
            group_subgroup_map[c] = (course_val, group_val, str(subgroup_counter))

        # Заполняем дни в колонке 0 и время в колонке 1
        df[0] = df[0].ffill()
        df[1] = df[1].ffill()
        
        current_day = None
        current_time = None
        slot_row_idx = 0
        
        for row_idx in range(start_row, len(df)):
            day_name_raw = str(df.iloc[row_idx, 0]).strip()
            time_slot_raw = str(df.iloc[row_idx, 1]).strip()
            
            if not day_name_raw or day_name_raw == "nan" or not time_slot_raw or time_slot_raw == "nan":
                continue
                
            # Убираем даты из названия дня
            day_name = re.sub(r'\s*\(.*?\)', '', day_name_raw).strip()
            time_slot = time_slot_raw
            
            # Сбрасываем счетчик при смене дня или времени
            if day_name != current_day or time_slot != current_time:
                current_day = day_name
                current_time = time_slot
                slot_row_idx = 0
            else:
                slot_row_idx += 1
            
            # Тип недели: первая строка слота - Числитель, вторая - Знаменатель
            week_type = "Числитель" if slot_row_idx == 0 else "Знаменатель"
            
            for col_idx, (course, group, subgroup) in group_subgroup_map.items():
                subject = clean_text(df.iloc[row_idx, col_idx])
                if subject:
                    normalized_data.append([
                        course,
                        group,
                        subgroup,
                        day_name,
                        time_slot,
                        week_type,
                        subject
                    ])

    if not normalized_data:
        print("Данные не найдены или ошибка в структуре Excel.")
        return

    new_df = pd.DataFrame(normalized_data, columns=["course", "group", "subgroup", "day", "time", "week_type", "subject"])
    
    # Удаляем дубликаты
    new_df = new_df.drop_duplicates()
    
    # Сортировка для удобства
    new_df = new_df.sort_values(by=["course", "group", "subgroup", "day", "time"])
    
    new_df.to_csv("formatted_schedule.csv", index=False, encoding="utf-8-sig")
    print(f"Таблица успешно пересобрана. Строк: {len(new_df)}")

if __name__ == "__main__":
    normalize()
