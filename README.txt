
Digital Library Management System (Advanced)
-------------------------------------------

This project is a ready-to-run Flask + SQLite application with:
 - Admin dashboard
 - Student request flow (issue / return)
 - Auto-fill student name by roll (after importing students)
 - Notification bell (polling)
 - Full-screen background image on all pages

How to run:
1. Install dependencies:
   python -m pip install flask pillow

2. Initialize and run:
   cd app
   python app.py

   The app will create 'library.db' automatically and seed sample books and an admin user:
   username: admin  password: admin123

3. To import students:
   - Create a CSV at scripts/students_full.csv with lines:
     241106001,A,PRN001,SANGPAL AMEY MUKESH
     241106002,A,PRN002,KHALANE ROHAN NANDKISHOR
     ...
   - Run:
     python import_students.py

   This will insert students into the SQLite DB used by the app.

Files:
 - app/app.py  (Flask app)
 - app/library.db (created after first run)
 - app/templates/  (HTML templates)
 - app/static/css/style.css
 - app/static/img/background.jpg (placeholder)
 - scripts/import_students.py  (CSV importer)
 - scripts/students_full.csv (place your CSV here)
