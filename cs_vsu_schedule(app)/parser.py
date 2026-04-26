import pandas as pd
import os
import requests
import re
from io import StringIO

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
            if self.df is not None and hasattr(self, '_last_mtime') and self._last_mtime == mtime:
                return True

            try:
                with open(self.file_path, 'r', encoding='utf-8-sig') as f:
                    lines = f.readlines()
                
                clean_lines = []
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('"') and line.endswith('"') and line.count(',') > 3:
                        line = line[1:-1].replace('""', '"')
                    clean_lines.append(line + "\n")
                
                df = pd.read_csv(StringIO("".join(clean_lines)))

                required_cols = ['course', 'group', 'subgroup', 'day', 'time', 'week_type', 'subject']
                for col in required_cols:
                    if col not in df.columns:
                        raise KeyError(f"Колонка '{col}' отсутствует в CSV")
                
                for col in df.columns:
                    if df[col].dtype == object:
                        df[col] = df[col].str.strip().replace(r'\s+', ' ', regex=True)
                
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
        
        # Разделяем бакалавриат и магистратуру
        bak = [c for c in courses if "курс" in str(c).lower() and "магистратура" not in str(c).lower()]
        mag = [c for c in courses if "магистратура" in str(c).lower()]
        
        # Сортировка (естественная)
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(s))]

        bak_sorted = sorted(bak, key=natural_sort_key)
        mag_sorted = sorted(mag, key=natural_sort_key)
        
        return bak_sorted + mag_sorted

    def get_groups(self, course_name):
        if self.df is None: self.load_data()
        if self.df is None: return []
        groups = self.df[self.df['course'] == course_name]['group'].unique().tolist()
        return sorted(groups, key=lambda x: [int(s) if s.isdigit() else s.lower() for s in re.split(r'(\d+)', str(x))])

    def get_subgroups(self, course, group):
        if self.df is None: self.load_data()
        if self.df is None: return []
        mask = (self.df['course'] == course) & (self.df['group'] == group)
        subgroups = self.df[mask]['subgroup'].unique().tolist()
        # Убираем "0" (техническая пометка) и сортируем
        return sorted([s for s in subgroups if s != "0" and str(s).isdigit()], key=int)

    def get_schedule(self, course, group, subgroup, week_type):
        if self.df is None: self.load_data()
        if self.df is None: return "База данных расписания пуста или не найдена."
        
        week_name = "Числитель" if week_type == 0 else "Знаменатель"
        is_masters = "магистратура" in str(course).lower()
        
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
            start_showing = not is_masters # Бакалавриат показываем всегда целиком
            
            for slot in self.TIME_SLOTS:
                has_lesson = slot in lessons_dict
                
                # Если магистры: начинаем показывать только с первой реальной пары
                # Но не позже 16:55 (чтобы вечер был всегда, если день не пустой)
                if is_masters and not start_showing:
                    if has_lesson or slot.startswith("16:55") or slot.startswith("15:10"):
                        start_showing = True
                
                if start_showing:
                    if has_lesson:
                        day_output.append(f"🔹 *{slot}*: {lessons_dict[slot]}")
                    else:
                        day_output.append(f"▫️ {slot}: _Нет пары_")
            
            full_schedule[day] = day_output

        return full_schedule

    def get_teacher_schedule(self, teacher_name):
        if self.df is None: self.load_data()
        if self.df is None: return []
        mask = (self.df['subject'].str.contains(teacher_name, case=False, na=False))
        results = self.df[mask].copy()
        if results.empty: return []
        temp_grouped = results.groupby(['day', 'time', 'subject', 'course', 'week_type'])['group'].unique().reset_index()
        final_grouped = {}
        for _, row in temp_grouped.iterrows():
            key = (row['day'], row['time'], row['subject'], row['course'])
            groups = set(row['group'])
            w_type = row['week_type']
            if key not in final_grouped:
                final_grouped[key] = {'groups': groups, 'weeks': {w_type}}
            else:
                final_grouped[key]['groups'].update(groups)
                final_grouped[key]['weeks'].add(w_type)
        teacher_results = []
        for key, val in final_grouped.items():
            day, time, subject, course = key
            weeks = val['weeks']
            week_display = "Любая неделя" if "Числитель" in weeks and "Знаменатель" in weeks else ("Числитель" if "Числитель" in weeks else "Знаменатель")
            sorted_groups = sorted(list(val['groups']), key=lambda s: int(re.search(r'\d+', s).group()) if re.search(r'\d+', s) else s)
            teacher_results.append({
                "day": day, "time": time, "course": course, "group": ", ".join(sorted_groups), "subject": subject, "week_type": week_display
            })
        days_order = {"Понедельник": 0, "Вторник": 1, "Среда": 2, "Четверг": 3, "Пятница": 4, "Суббота": 5}
        teacher_results.sort(key=lambda x: (days_order.get(x['day'], 9), x['time']))
        return teacher_results

    def get_all_classrooms(self):
        if self.df is None: self.load_data()
        if self.df is None: return []
        def extract_room(s):
            if not s or "(ДО)" in str(s): return None
            s_clean = str(s).strip().replace('"', '')
            match = re.search(r'\s(\d{3,4}[а-яА-Я]?)$', s_clean)
            return match.group(1) if match else None
        rooms = self.df['subject'].apply(extract_room).dropna().unique().tolist()
        return sorted([str(r).upper() for r in rooms])

    def get_free_classrooms(self, day, time_slot, week_type):
        if self.df is None: self.load_data()
        if self.df is None: return {"main": [], "p": []}
        week_name = "Числитель" if int(week_type) == 0 else "Знаменатель"
        day = str(day).strip()
        def clean_t(ts):
            parts = str(ts).replace(' ', '').split('-')
            cleaned = [p.lstrip('0') if p.startswith('0') else p for p in parts]
            return '-'.join(cleaned)
        time_slot_clean = clean_t(time_slot)
        all_rooms = set(self.get_all_classrooms())
        mask = (self.df['day'] == day) & (self.df['week_type'] == week_name)
        df_time_cleaned = self.df['time'].apply(clean_t)
        mask = mask & (df_time_cleaned == time_slot_clean)
        occupied_subjects = self.df[mask]['subject'].tolist()
        occupied_rooms = set()
        for s in occupied_subjects:
            s_clean = str(s).strip().replace('"', '')
            match = re.search(r'\s(\d{3,4}[а-яА-Я]?)$', s_clean)
            if match: occupied_rooms.add(match.group(1).upper())
        free_rooms = sorted(list(all_rooms - occupied_rooms))
        result = {"main": [], "p": []}
        for r in free_rooms:
            if r.endswith('П'): result["p"].append(r)
            else: result["main"].append(r)
        return result

parser = ScheduleParser()
