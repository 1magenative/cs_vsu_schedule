import csv
import os

input_file = "e:/cs_vsu_schedule/formatted_schedule.csv"
output_file = "e:/cs_vsu_schedule/formatted_schedule_fixed.csv"

def fix_csv():
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    fixed_lines = []
    for line in lines:
        line = line.strip()
        if not line: continue
        # Detect if the whole line is wrapped in quotes
        if line.startswith('"') and line.endswith('"'):
            # It's probably a row that was accidentally quoted by an editor
            # We need to unquote it. Internal double quotes might be escaped as ""
            inner = line[1:-1]
            # Replace "" with "
            inner = inner.replace('""', '"')
            fixed_lines.append(inner + "\n")
        else:
            fixed_lines.append(line + "\n")

    with open(output_file, 'w', encoding='utf-8-sig') as f:
        f.writelines(fixed_lines)

if __name__ == "__main__":
    fix_csv()
    print("CSV fixed.")
