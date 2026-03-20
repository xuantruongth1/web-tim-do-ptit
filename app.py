from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime

app = Flask(__name__)

def connect_db():
    return sqlite3.connect("database.db")

def create_tables():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lost_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        category TEXT,
        description TEXT,
        location TEXT,
        time TEXT,
        contact TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS found_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        category TEXT,
        description TEXT,
        location TEXT,
        time TEXT,
        contact TEXT
    )
    """)

    conn.commit()
    conn.close()

create_tables()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/lost", methods=["GET", "POST"])
def lost():
    if request.method == "POST":
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO lost_items (item_name, category, description, location, time, contact)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            request.form["item_name"],
            request.form["category"],
            request.form["description"],
            request.form["location"],
            str(datetime.now()),
            request.form["contact"]
        ))

        conn.commit()
        conn.close()
        return redirect("/list")

    return render_template("lost.html")

@app.route("/found", methods=["GET", "POST"])
def found():
    if request.method == "POST":
        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO found_items (item_name, category, description, location, time, contact)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            request.form["item_name"],
            request.form["category"],
            request.form["description"],
            request.form["location"],
            str(datetime.now()),
            request.form["contact"]
        ))

        conn.commit()
        conn.close()
        return redirect("/list")

    return render_template("found.html")

@app.route("/list")
def list_items():
    conn = connect_db()
    cursor = conn.cursor()

    lost = cursor.execute("SELECT * FROM lost_items").fetchall()
    found = cursor.execute("SELECT * FROM found_items").fetchall()

    conn.close()
    return render_template("list.html", lost=lost, found=found)

@app.route("/search", methods=["GET", "POST"])
def search():
    results_lost = []
    results_found = []

    if request.method == "POST":
        keyword = request.form["keyword"]

        conn = connect_db()
        cursor = conn.cursor()

        results_lost = cursor.execute(
            "SELECT * FROM lost_items WHERE item_name LIKE ?", ('%' + keyword + '%',)
        ).fetchall()

        results_found = cursor.execute(
            "SELECT * FROM found_items WHERE item_name LIKE ?", ('%' + keyword + '%',)
        ).fetchall()

        conn.close()

    return render_template("search.html", lost=results_lost, found=results_found)

def match_score(l, f):
    score = 0
    if l[1].lower() in f[1].lower() or f[1].lower() in l[1].lower():
        score += 30
    if l[4].lower() == f[4].lower():
        score += 30
    if l[2].lower() == f[2].lower():
        score += 20
    if l[3].lower() in f[3].lower() or f[3].lower() in l[3].lower():
        score += 20
    return score

@app.route("/match")
def match():
    conn = connect_db()
    cursor = conn.cursor()

    lost = cursor.execute("SELECT * FROM lost_items").fetchall()
    found = cursor.execute("SELECT * FROM found_items").fetchall()

    results = []

    for l in lost:
        for f in found:
            score = match_score(l, f)
            if score >= 50:
                results.append((l, f, score))

    conn.close()
    return render_template("match.html", results=results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)