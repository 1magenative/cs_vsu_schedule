import pandas as pd
import os
import requests
import re

class ScheduleParser:
    def __init__(self, file_path="formatted_schedule.csv"):
        self.file_path = file_path
        self.df = None
        # Стандартные слоты времени в ВГУ
        self.TIME_SLOTS = [
            "8:00 - 9:35", "9:45 - 11:20", "11:30-13:05", "13:25-15:00", 
            "15:10-16:45", "16:55-18:30", "18:40-20:00", "20:10-21:30"
        ]

    def load_data(self):
        if os.path.exists(self.file_path):
            mtime = os.path.getmtime(self.file_path)
            # Если данные уже загружены и файл не менялся - пропускаем
            if self.df is not None and hasattr(self, '_last_mtime') and self._last_mtime == mtime:
                return True

            try:
                # Читаем файл вручную, чтобы исправить "битые" строки (лишние кавычки из Excel)
                with open(self.file_path, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
                
                clean_lines = []
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    # Если строка целиком в кавычках (ошибка экспорта некоторых редакторов)
                    if line.startswith('"') and line.endswith('"') and line.count(',') > 3:
                        line = line[1:-1].replace('""', '"')
                    clean_lines.append(line + "\n")
                
                from io import StringIO
                df = pd.read_csv(StringIO("".join(clean_lines)))

                # Ensure required columns exist
                required_cols = ['course', 'group', 'subgroup', 'day', 'time', 'week_type', 'subject']
                for col in required_cols:
                    if col not in df.columns:
                        raise KeyError(f"Колонка '{col}' отсутствует в CSV")
                
                # Cleanup: strip whitespace from all strings
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].str.strip().replace(r'\s+', ' ', regex=True)
                
                # Normalize subgroup: "1.0" -> "1", "nan" -> "0"
                def clean_subgroup(val):
                    if pd.isna(val) or str(val).lower() == 'nan': return "0"
                    s = str(val).split('.')[0].strip()
                    return s
                
                df['subgroup'] = df['subgroup'].apply(clean_subgroup)
                
                self.df = df
                self._last_mtime = mtime
                return True
            except Exception as e:
                print(f"Ошибка загрузки CSV: {e}")
                self.df = None
        return False

    def update_data(self):
        """Запуск нормализации локального Excel-файла"""
        try:
            from normalize import normalize
            normalize()
            return self.load_data()
        except Exception as e:
            print(f"Ошибка обновления: {e}")
            return False

    def get_courses(self):
        if self.df is None: self.load_data()
        if self.df is None: return []
        courses = self.df['course'].unique().tolist()
        # Natural sorting: "1 курс", "2 курс" ... "10 курс"
        return sorted(courses, key=lambda x: [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', str(x))])

    def get_groups(self, course_name):
        if self.df is None: self.load_data()
        if self.df is None: return []
        groups = self.df[self.df['course'] == course_name]['group'].unique().tolist()
        # Natural sorting: "1 группа", "2 группа" ... "10 группа"
        return sorted(groups, key=lambda x: [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', str(x))])

    def get_schedule(self, course, group, subgroup, week_type):
        if self.df is None: self.load_data()
        if self.df is None: return "База данных расписания пуста или не найдена."
        
        week_name = "Числитель" if week_type == 0 else "Знаменатель"
        
        # Фильтруем данные из нашего красивого CSV
        mask = (self.df['course'] == course) & \
               (self.df['group'] == group) & \
               (self.df['subgroup'] == str(subgroup)) & \
               (self.df['week_type'] == week_name)
        
        filtered = self.df[mask]
        
        full_schedule = {}
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
        
        for day in days:
            day_data = filtered[filtered['day'] == day]
            lessons_dict = {row['time']: row['subject'] for _, row in day_data.iterrows()}
            
            day_output = []
            for slot in self.TIME_SLOTS:
                if slot in lessons_dict:
                    day_output.append(f"🔹 *{slot}*: {lessons_dict[slot]}")
                else:
                    day_output.append(f"▫️ {slot}: _Нет пары_")
            
            full_schedule[day] = day_output

        return full_schedule

parser = ScheduleParser()
