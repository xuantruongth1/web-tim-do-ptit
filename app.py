from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Tự tạo thư mục uploads nếu chưa có
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
        contact TEXT,
        image TEXT
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
        contact TEXT,
        image TEXT
    )
    """)

    conn.commit()

    # Nếu DB cũ chưa có cột image thì thêm vào
    try:
        cursor.execute("ALTER TABLE lost_items ADD COLUMN image TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE found_items ADD COLUMN image TEXT")
    except:
        pass

    conn.commit()
    conn.close()


create_tables()


@app.route("/")
def home():
    conn = connect_db()
    cursor = conn.cursor()

    lost = cursor.execute("SELECT * FROM lost_items").fetchall()
    found = cursor.execute("SELECT * FROM found_items").fetchall()

    conn.close()

    return render_template("home.html", lost_count=len(lost), found_count=len(found))


@app.route("/lost", methods=["GET", "POST"])
def lost():
    if request.method == "POST":
        image_name = ""

        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename != "" and allowed_file(file.filename):
                image_name = secure_filename(file.filename)

                # tránh trùng tên file
                if image_name:
                    name, ext = os.path.splitext(image_name)
                    image_name = f"{name}_{int(datetime.now().timestamp())}{ext}"

                save_path = os.path.join(app.config["UPLOAD_FOLDER"], image_name)
                file.save(save_path)

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO lost_items (item_name, category, description, location, time, contact, image)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form["item_name"],
            request.form["category"],
            request.form["description"],
            request.form["location"],
            str(datetime.now()),
            request.form["contact"],
            image_name
        ))

        conn.commit()
        conn.close()
        return redirect("/list")

    return render_template("lost.html")


@app.route("/found", methods=["GET", "POST"])
def found():
    if request.method == "POST":
        image_name = ""

        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename != "" and allowed_file(file.filename):
                image_name = secure_filename(file.filename)

                # tránh trùng tên file
                if image_name:
                    name, ext = os.path.splitext(image_name)
                    image_name = f"{name}_{int(datetime.now().timestamp())}{ext}"

                save_path = os.path.join(app.config["UPLOAD_FOLDER"], image_name)
                file.save(save_path)

        conn = connect_db()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO found_items (item_name, category, description, location, time, contact, image)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            request.form["item_name"],
            request.form["category"],
            request.form["description"],
            request.form["location"],
            str(datetime.now()),
            request.form["contact"],
            image_name
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
            "SELECT * FROM lost_items WHERE item_name LIKE ?",
            ('%' + keyword + '%',)
        ).fetchall()

        results_found = cursor.execute(
            "SELECT * FROM found_items WHERE item_name LIKE ?",
            ('%' + keyword + '%',)
        ).fetchall()

        conn.close()

    return render_template("search.html", lost=results_lost, found=results_found)


def match_score(l, f):
    score = 0

    lost_name = (l[1] or "").lower()
    found_name = (f[1] or "").lower()
    lost_category = (l[2] or "").lower()
    found_category = (f[2] or "").lower()
    lost_description = (l[3] or "").lower()
    found_description = (f[3] or "").lower()
    lost_location = (l[4] or "").lower()
    found_location = (f[4] or "").lower()

    # tên gần giống
    if lost_name == found_name:
        score += 40
    elif lost_name in found_name or found_name in lost_name:
        score += 25

    # địa điểm
    if lost_location == found_location:
        score += 25

    # loại đồ
    if lost_category == found_category:
        score += 20

    # mô tả (so từ khóa)
    for word in lost_description.split():
        if word and word in found_description:
            score += 5

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