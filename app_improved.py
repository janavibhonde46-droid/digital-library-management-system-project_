from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify, send_file
import sqlite3, os, csv, io
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / 'library.db'
SECRET_KEY = os.environ.get('LIB_SECRET') or 'change-this-secret-please-change'

# Config
DEFAULT_LOAN_DAYS = 14
FINE_PER_DAY = 5
BOOKS_PER_PAGE = 8

app = Flask(__name__)
app.secret_key = SECRET_KEY

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(str(DB_PATH))
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute(sql, args=()):
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid

SCHEMA = '''CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT,
    isbn TEXT UNIQUE,
    copies INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    roll_no TEXT UNIQUE,
    email TEXT,
    password_hash TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    issued_at TEXT NOT NULL,
    due_date TEXT NOT NULL,
    returned_at TEXT,
    fine_paid INTEGER DEFAULT 0,
    FOREIGN KEY(book_id) REFERENCES books(id),
    FOREIGN KEY(student_id) REFERENCES students(id)
);
'''

def init_db(create_admin=True):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    conn.commit()
    if create_admin:
        cur.execute('SELECT id FROM admins WHERE username=?', ('admin',))
        if not cur.fetchone():
            pw = generate_password_hash('admin123')
            cur.execute('INSERT INTO admins (username,password_hash) VALUES (?,?)', ('admin', pw))
            conn.commit()
    conn.close()

def admin_required(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login', next=request.path))
        return fn(*args, **kwargs)
    return decorated

def student_required(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if 'student_id' not in session:
            return redirect(url_for('student_login', next=request.path))
        return fn(*args, **kwargs)
    return decorated

def calculate_fine(due_date_str, returned_at_str=None):
    try:
        due = datetime.fromisoformat(due_date_str)
    except Exception:
        return 0
    if returned_at_str:
        returned = datetime.fromisoformat(returned_at_str)
    else:
        returned = datetime.utcnow()
    overdue = (returned.date() - due.date()).days
    return max(0, overdue * FINE_PER_DAY)

@app.route('/')
def index():
    q = request.args.get('q','').strip()
    page = max(1, int(request.args.get('page') or 1))
    params = []
    sql = 'SELECT * FROM books'
    if q:
        sql += ' WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?'
        pattern = f'%{q}%'
        params.extend([pattern, pattern, pattern])
    sql += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
    params.extend([BOOKS_PER_PAGE, (page-1)*BOOKS_PER_PAGE])
    books = query(sql, tuple(params))
    # count total
    if q:
        total = query('SELECT COUNT(*) as c FROM books WHERE title LIKE ? OR author LIKE ? OR isbn LIKE ?', (pattern,pattern,pattern), one=True)['c']
    else:
        total = query('SELECT COUNT(*) as c FROM books', one=True)['c']
    pages = (total + BOOKS_PER_PAGE - 1)//BOOKS_PER_PAGE
    return render_template('index.html', books=books, q=q, page=page, pages=pages)

# ---------------- Admin auth ----------------
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = query('SELECT * FROM admins WHERE username=?', (username,), one=True)
        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_id'] = admin['id']
            session['admin_username'] = admin['username']
            flash('Logged in as admin', 'success')
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    flash('Logged out', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {
        'books': query('SELECT COUNT(*) as c FROM books', one=True)['c'],
        'students': query('SELECT COUNT(*) as c FROM students', one=True)['c'],
        'issued': query('SELECT COUNT(*) as c FROM issues WHERE returned_at IS NULL', one=True)['c'],
        'overdue': query('SELECT COUNT(*) as c FROM issues WHERE returned_at IS NULL AND due_date < ?', (datetime.utcnow().isoformat(),), one=True)['c']
    }
    recent = query('''SELECT issues.*, books.title, students.name, students.roll_no FROM issues
                              JOIN books ON books.id=issues.book_id
                              JOIN students ON students.id=issues.student_id
                              ORDER BY issues.issued_at DESC LIMIT 12''')
    annotated = []
    for i in recent:
        d = dict(i)
        d['fine'] = calculate_fine(d['due_date'], d['returned_at'])
        annotated.append(d)
    return render_template('admin_dashboard.html', stats=stats, recent_issues=annotated)

# ---------------- Books CRUD + CSV import/export ----------------
@app.route('/admin/books')
@admin_required
def admin_books():
    books = query('SELECT * FROM books ORDER BY id DESC')
    return render_template('books.html', books=books)

@app.route('/admin/books/add', methods=['GET','POST'])
@admin_required
def add_book():
    if request.method == 'POST':
        title = request.form['title'].strip()
        author = request.form.get('author','').strip()
        isbn = request.form.get('isbn','').strip() or None
        try:
            copies = int(request.form.get('copies') or 1)
        except ValueError:
            copies = 1
        execute('INSERT INTO books (title,author,isbn,copies) VALUES (?,?,?,?)', (title,author,isbn,copies))
        flash('Book added', 'success')
        return redirect(url_for('admin_books'))
    return render_template('books.html', action='add')

@app.route('/admin/books/delete/<int:book_id>', methods=['POST'])
@admin_required
def delete_book(book_id):
    execute('DELETE FROM books WHERE id=?', (book_id,))
    flash('Book deleted', 'info')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/import', methods=['GET','POST'])
@admin_required
def import_books():
    if request.method == 'POST':
        f = request.files.get('file')
        if not f:
            flash('No file uploaded', 'danger'); return redirect(url_for('admin_books'))
        stream = io.StringIO(f.stream.read().decode('utf-8'))
        reader = csv.DictReader(stream)
        count = 0
        for row in reader:
            title = row.get('title') or row.get('Title')
            if not title: continue
            author = row.get('author') or row.get('Author') or ''
            isbn = row.get('isbn') or row.get('ISBN') or None
            copies = int(row.get('copies') or 1)
            try:
                execute('INSERT INTO books (title,author,isbn,copies) VALUES (?,?,?,?)', (title,author,isbn,copies))
                count += 1
            except Exception:
                continue
        flash(f'Imported {count} books (duplicates skipped)', 'success')
        return redirect(url_for('admin_books'))
    return redirect(url_for('admin_books'))

@app.route('/admin/books/export')
@admin_required
def export_books():
    rows = query('SELECT * FROM books')
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['id','title','author','isbn','copies','created_at'])
    for r in rows:
        writer.writerow([r['id'], r['title'], r['author'], r['isbn'], r['copies'], r['created_at']])
    mem = io.BytesIO()
    mem.write(si.getvalue().encode('utf-8'))
    mem.seek(0)
    return send_file(mem, as_attachment=True, download_name='books_export.csv', mimetype='text/csv')

# ---------------- Students CRUD + registration + CSV import ----------------
@app.route('/admin/students')
@admin_required
def admin_students():
    students = query('SELECT * FROM students ORDER BY id DESC')
    return render_template('students.html', students=students)

@app.route('/admin/students/import', methods=['POST'])
@admin_required
def import_students():
    f = request.files.get('file')
    if not f:
        flash('No file uploaded', 'danger'); return redirect(url_for('admin_students'))
    stream = io.StringIO(f.stream.read().decode('utf-8'))
    reader = csv.DictReader(stream)
    count = 0
    for row in reader:
        name = row.get('name') or row.get('Name') or ''
        if not name: continue
        roll = row.get('roll_no') or row.get('Roll') or None
        email = row.get('email') or row.get('Email') or None
        pwd = row.get('password') or 'student123'
        try:
            execute('INSERT INTO students (name,roll_no,email,password_hash) VALUES (?,?,?,?)', (name,roll,email, generate_password_hash(pwd)))
            count += 1
        except Exception:
            continue
    flash(f'Imported {count} students (duplicates skipped)', 'success')
    return redirect(url_for('admin_students'))

@app.route('/admin/students/add', methods=['POST'])
@admin_required
def add_student():
    name = request.form['name'].strip()
    roll = request.form.get('roll_no','').strip() or None
    email = request.form.get('email','').strip() or None
    password = request.form.get('password') or 'student123'
    execute('INSERT INTO students (name,roll_no,email,password_hash) VALUES (?,?,?,?)', (name,roll,email, generate_password_hash(password)))
    flash('Student added', 'success')
    return redirect(url_for('admin_students'))

# ---------------- Issue / Return with copies handling ----------------
@app.route('/admin/issue', methods=['GET','POST'])
@admin_required
def issue_book():
    if request.method == 'POST':
        book_id = int(request.form['book_id'])
        student_id = int(request.form['student_id'])
        loan_days = int(request.form.get('loan_days') or DEFAULT_LOAN_DAYS)
        book = query('SELECT * FROM books WHERE id=?', (book_id,), one=True)
        student = query('SELECT * FROM students WHERE id=?', (student_id,), one=True)
        if not book or not student:
            flash('Book or student not found', 'danger'); return redirect(url_for('admin_dashboard'))
        if book['copies'] <= 0:
            flash('No available copies to issue', 'danger'); return redirect(url_for('admin_books'))
        issued_at = datetime.utcnow().isoformat()
        due_date = (datetime.utcnow() + timedelta(days=loan_days)).isoformat()
        execute('INSERT INTO issues (book_id,student_id,issued_at,due_date) VALUES (?,?,?,?)', (book_id, student_id, issued_at, due_date))
        # decrement copies
        execute('UPDATE books SET copies = copies - 1 WHERE id=?', (book_id,))
        flash('Book issued', 'success')
        return redirect(url_for('admin_dashboard'))
    books = query('SELECT * FROM books WHERE copies > 0')
    students = query('SELECT * FROM students')
    return render_template('issue_book.html', books=books, students=students, default_days=DEFAULT_LOAN_DAYS)

@app.route('/admin/return/<int:issue_id>', methods=['POST'])
@admin_required
def return_book(issue_id):
    issue = query('SELECT * FROM issues WHERE id=?', (issue_id,), one=True)
    if not issue:
        flash('Issue record not found', 'danger'); return redirect(url_for('admin_dashboard'))
    if issue['returned_at']:
        flash('Already returned', 'info'); return redirect(url_for('admin_dashboard'))
    returned_at = datetime.utcnow().isoformat()
    execute('UPDATE issues SET returned_at=? WHERE id=?', (returned_at, issue_id))
    # increment copies
    execute('UPDATE books SET copies = copies + 1 WHERE id=?', (issue['book_id'],))
    flash('Book returned', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/mark_fine_paid/<int:issue_id>', methods=['POST'])
@admin_required
def mark_fine_paid(issue_id):
    execute('UPDATE issues SET fine_paid=1 WHERE id=?', (issue_id,))
    flash('Fine marked as paid', 'success')
    return redirect(url_for('admin_dashboard'))

# ---------------- Student portal & auth ----------------
@app.route('/student/register', methods=['GET','POST'])
def student_register():
    if request.method == 'POST':
        name = request.form['name'].strip()
        roll = request.form.get('roll_no','').strip() or None
        email = request.form.get('email','').strip() or None
        password = request.form.get('password') or 'student123'
        try:
            execute('INSERT INTO students (name,roll_no,email,password_hash) VALUES (?,?,?,?)', (name,roll,email, generate_password_hash(password)))
            flash('Student registered. You can login now.', 'success')
            return redirect(url_for('student_login'))
        except Exception as e:
            flash('Registration failed (maybe duplicate roll no)', 'danger')
    return render_template('student_register.html')

@app.route('/student/login', methods=['GET','POST'])
def student_login():
    if request.method == 'POST':
        roll = request.form.get('roll_no','').strip()
        password = request.form.get('password') or ''
        s = query('SELECT * FROM students WHERE roll_no=?', (roll,), one=True)
        if s and s['password_hash'] and check_password_hash(s['password_hash'], password):
            session['student_id'] = s['id']
            session['student_name'] = s['name']
            flash('Logged in', 'success')
            return redirect(url_for('student_portal'))
        flash('Invalid credentials', 'danger')
    return render_template('student_login.html')

@app.route('/student/logout')
def student_logout():
    session.pop('student_id', None); session.pop('student_name', None)
    flash('Logged out', 'info'); return redirect(url_for('student_login'))

@app.route('/student', methods=['GET','POST'])
def student_portal():
    student = None
    issues = []
    total_fine = 0
    # If logged in, show that student, else accept roll_no lookup
    if 'student_id' in session:
        student = query('SELECT * FROM students WHERE id=?', (session['student_id'],), one=True)
    elif request.method == 'POST':
        roll = request.form.get('roll_no','').strip()
        student = query('SELECT * FROM students WHERE roll_no=?', (roll,), one=True)
        if not student:
            flash('Student not found', 'danger'); student = None
    if student:
        issues_raw = query('''SELECT issues.*, books.title, books.author FROM issues
                                   JOIN books ON books.id=issues.book_id
                                   WHERE issues.student_id=? ORDER BY issues.issued_at DESC''', (student['id'],))
        for i in issues_raw:
            d = dict(i)
            d['fine'] = calculate_fine(d['due_date'], d['returned_at'])
            total_fine += d['fine']
            issues.append(d)
    return render_template('student_portal.html', student=student, issues=issues, total_fine=total_fine)

# ---------------- API ----------------
@app.route('/api/books')
def api_books():
    books = query('SELECT * FROM books')
    return jsonify([dict(b) for b in books])

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
