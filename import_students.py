
# scripts/import_students.py
# Usage: place a CSV named students_full.csv in this scripts folder with lines: roll,division,prn,name
# then run: python import_students.py
import csv, sqlite3, os
BASE = os.path.dirname(os.path.dirname(__file__))
DB = os.path.join(BASE, 'app', 'library.db')
def main():
    path = os.path.join(os.path.dirname(__file__), 'students_full.csv')
    if not os.path.exists(path):
        print('Place students_full.csv (roll,division,prn,name) in this folder and re-run.')
        return
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    with open(path, 'r', encoding='utf-8') as f:
        rdr = csv.reader(f)
        for row in rdr:
            if not row: continue
            roll = row[0].strip()
            division = row[1].strip() if len(row)>1 else ''
            prn = row[2].strip() if len(row)>2 else ''
            name = row[3].strip() if len(row)>3 else ''
            cur.execute("INSERT OR IGNORE INTO students (roll,name,division,prn) VALUES (?,?,?,?)", (roll,name,division,prn))
    conn.commit()
    conn.close()
    print('Import complete.')
if __name__=='__main__':
    main()
