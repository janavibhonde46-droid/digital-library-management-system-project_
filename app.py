
from flask import Flask, render_template, request, redirect, url_for, jsonify, g
import sqlite3, os, datetime

BASE = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE, 'library.db')

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    # students, books, requests, issues, activity, users
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT UNIQUE,
        name TEXT,
        division TEXT,
        prn TEXT
    );
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        author TEXT,
        quantity INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT,
        student_name TEXT,
        book_id INTEGER,
        book_title TEXT,
        type TEXT, -- 'issue' or 'return'
        status TEXT, -- 'pending','approved','rejected'
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll TEXT,
        student_name TEXT,
        book_id INTEGER,
        book_title TEXT,
        issue_date TEXT,
        due_date TEXT,
        returned INTEGER DEFAULT 0,
        returned_date TEXT
    );
    CREATE TABLE IF NOT EXISTS activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    );
    """)
    # default admin
    cur.execute("INSERT OR IGNORE INTO users (username,password) VALUES (?,?)", ('admin','admin123'))
    # sample books if empty
    cur.execute("SELECT COUNT(*) as c FROM books")
    if cur.fetchone()['c'] == 0:
        books = [
            ('Introduction to Programming','A. Author',5),
            ('Database Systems','B. Writer',4),
            ('Learning Python','C. Dev',6)
        ]
        cur.executemany("INSERT INTO books (title,author,quantity) VALUES (?,?,?)", books)
    db.commit()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = 'replace-with-secret'

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.before_first_request
def setup():
    init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/books')
def books():
    db = get_db()
    books = db.execute("SELECT * FROM books").fetchall()
    return render_template('books.html', books=books)

@app.route('/student/request', methods=['GET','POST'])
def student_request():
    db = get_db()
    books = db.execute("SELECT * FROM books").fetchall()
    if request.method == 'POST':
        roll = request.form.get('roll','').strip()
        name = request.form.get('name','').strip()
        book_id = request.form.get('book_id')
        typ = request.form.get('type','issue')
        book = db.execute("SELECT title FROM books WHERE id=?", (book_id,)).fetchone()
        book_title = book['title'] if book else ''
        db.execute("INSERT INTO requests (roll,student_name,book_id,book_title,type,status,created_at) VALUES (?,?,?,?,?,?,?)",
                   (roll,name,book_id,book_title,typ,'pending', datetime.datetime.utcnow().isoformat()))
        db.execute("INSERT INTO activity (message,created_at) VALUES (?,?)", (f"Request by {name} ({roll}) for {book_title}", datetime.datetime.utcnow().isoformat()))
        db.commit()
        return redirect(url_for('student_request'))
    return render_template('student_request.html', books=books)

@app.route('/api/student')
def api_student():
    roll = request.args.get('roll','').strip()
    if not roll:
        return jsonify({})
    db = get_db()
    s = db.execute("SELECT * FROM students WHERE roll=?", (roll,)).fetchone()
    if not s:
        return jsonify({})
    return jsonify({'roll': s['roll'], 'name': s['name'], 'division': s['division'], 'prn': s['prn']})

# Admin routes
@app.route('/admin/login', methods=['GET','POST'])
def admin_login():
    error=None
    if request.method=='POST':
        u = request.form.get('username')
        p = request.form.get('password')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=? AND password=?", (u,p)).fetchone()
        if user:
            return redirect(url_for('admin_dashboard'))
        error='Invalid credentials'
    return render_template('admin_login.html', error=error)

@app.route('/admin/dashboard')
def admin_dashboard():
    db = get_db()
    requests = db.execute("SELECT * FROM requests ORDER BY created_at DESC").fetchall()
    issues = db.execute("SELECT * FROM issues ORDER BY issue_date DESC").fetchall()
    activity = db.execute("SELECT * FROM activity ORDER BY created_at DESC LIMIT 100").fetchall()
    pending_count = db.execute("SELECT COUNT(*) as c FROM requests WHERE status='pending'").fetchone()['c']
    return render_template('admin_dashboard.html', requests=requests, issues=issues, activity=activity, pending_count=pending_count)

@app.route('/admin/request/<int:req_id>/action', methods=['POST'])
def admin_request_action(req_id):
    action = request.form.get('action')
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id=?", (req_id,)).fetchone()
    if not req:
        return redirect(url_for('admin_dashboard'))
    if action=='approve':
        # create issue
        issue_date = datetime.datetime.utcnow()
        due = issue_date + datetime.timedelta(days=14)
        db.execute("INSERT INTO issues (roll,student_name,book_id,book_title,issue_date,due_date,returned) VALUES (?,?,?,?,?,?,0)",
                   (req['roll'], req['student_name'], req['book_id'], req['book_title'], issue_date.isoformat(), due.isoformat()))
        db.execute("UPDATE requests SET status='approved' WHERE id=?", (req_id,))
        db.execute("INSERT INTO activity (message,created_at) VALUES (?,?)", (f"Approved request {req_id}", datetime.datetime.utcnow().isoformat()))
    elif action=='reject':
        db.execute("UPDATE requests SET status='rejected' WHERE id=?", (req_id,))
        db.execute("INSERT INTO activity (message,created_at) VALUES (?,?)", (f"Rejected request {req_id}", datetime.datetime.utcnow().isoformat()))
    elif action=='delete':
        db.execute("DELETE FROM requests WHERE id=?", (req_id,))
    db.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/api/pending_count')
def api_pending_count():
    db = get_db()
    cnt = db.execute("SELECT COUNT(*) as c FROM requests WHERE status='pending'").fetchone()['c']
    return jsonify({'pending': cnt})

if __name__=='__main__':
    app.run(debug=True, port=3000)
