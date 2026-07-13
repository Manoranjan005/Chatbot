import os
import sqlite3
import time
from pathlib import Path

from flask import Flask, request, jsonify, render_template, g
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY not found. Create a .env file (see .env.example) "
        "and set GEMINI_API_KEY=your_key_here"
    )

client = genai.Client(api_key=GEMINI_API_KEY)

# You can swap this for another available Gemini model name if you like.
MODEL_NAME = "gemini-3.1-flash-lite"

DB_PATH = Path(__file__).parent / "chat_history.db"

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,           -- 'user' or 'model'
            content TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations (id)
        )
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Routes - pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Routes - conversations
# ---------------------------------------------------------------------------

@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    db = get_db()
    rows = db.execute(
        "SELECT id, title, created_at FROM conversations ORDER BY id DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/conversations", methods=["POST"])
def create_conversation():
    db = get_db()
    cur = db.execute(
        "INSERT INTO conversations (title, created_at) VALUES (?, ?)",
        ("New chat", time.time()),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid, "title": "New chat"})


@app.route("/api/conversations/<int:conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    db = get_db()
    db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    db.commit()
    return jsonify({"status": "deleted"})


@app.route("/api/conversations/<int:conv_id>/messages", methods=["GET"])
def get_messages(conv_id):
    db = get_db()
    rows = db.execute(
        "SELECT role, content, created_at FROM messages "
        "WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Routes - chat
# ---------------------------------------------------------------------------

def build_history(db, conv_id):
    """Turn stored messages into Gemini `contents` format."""
    rows = db.execute(
        "SELECT role, content FROM messages "
        "WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    ).fetchall()
    contents = []
    for row in rows:
        contents.append(
            types.Content(role=row["role"], parts=[types.Part(text=row["content"])])
        )
    return contents


@app.route("/api/conversations/<int:conv_id>/chat", methods=["POST"])
def chat(conv_id):
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    if not user_message:
        return jsonify({"error": "Message cannot be empty"}), 400

    db = get_db()
    conv = db.execute(
        "SELECT id FROM conversations WHERE id = ?", (conv_id,)
    ).fetchone()
    if conv is None:
        return jsonify({"error": "Conversation not found"}), 404

    try:
        history = build_history(db, conv_id)
        history.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=history,
        )
        reply_text = response.text

        now = time.time()
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, 'user', ?, ?)",
            (conv_id, user_message, now),
        )
        db.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES (?, 'model', ?, ?)",
            (conv_id, reply_text, now),
        )

        # Auto-title new conversations from the first message.
        row = db.execute(
            "SELECT title FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        if row and row["title"] == "New chat":
            title = user_message[:40] + ("..." if len(user_message) > 40 else "")
            db.execute(
                "UPDATE conversations SET title = ? WHERE id = ?", (title, conv_id)
            )

        db.commit()
        return jsonify({"reply": reply_text})
    except Exception as e:
        return jsonify({"error": f"Gemini API error: {str(e)}"}), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
