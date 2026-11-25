
"""Nexora AI — frontend serving, admin authentication and lead management."""

import os
import json
import hmac
import secrets
import sqlite3
from pathlib import Path
from functools import wraps
from datetime import date, timedelta
from contextlib import contextmanager
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from flask import Flask, jsonify, request, session, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

# Frontend files are in the repository root; this file is in backend/.
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB = Path(__file__).with_name("nexora.db")


# -------------------- Security configuration --------------------

secret_key = os.getenv("SECRET_KEY", "").strip()

if not secret_key:
    raise RuntimeError("Set SECRET_KEY before starting Nexora AI.")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=1800,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# -------------------- CORS configuration --------------------

ALLOWED_ORIGINS = {
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5501",
    "http://127.0.0.1:5501",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}

configured_origin = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")

if configured_origin:
    ALLOWED_ORIGINS.add(configured_origin)


@app.after_request
def add_security_and_cors_headers(response):
    origin = request.headers.get("Origin", "")

    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, X-CSRF-Token"
        )
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PATCH, DELETE, OPTIONS"
        )
        response.headers["Vary"] = "Origin"

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    return response


@app.route("/api/<path:_path>", methods=["OPTIONS"])
def api_options(_path):
    return ("", 204)


# -------------------- Frontend routes --------------------

@app.get("/")
def home():
    return send_from_directory(PROJECT_DIR, "index.html")


@app.get("/dashboard.html")
def dashboard_page():
    return send_from_directory(PROJECT_DIR, "dashboard.html")


@app.get("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(PROJECT_DIR / "css", filename)


@app.get("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(PROJECT_DIR / "js", filename)


# -------------------- Database --------------------

@contextmanager
def db():
    connection = sqlite3.connect(DB, timeout=10)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init():
    admin_email = os.getenv("NEXORA_ADMIN_EMAIL", "").strip().lower()
    admin_password = os.getenv("NEXORA_ADMIN_PASSWORD", "")

    if not admin_email or not admin_password:
        raise RuntimeError(
            "Set NEXORA_ADMIN_EMAIL and NEXORA_ADMIN_PASSWORD before startup."
        )

    if len(admin_password) < 12:
        raise RuntimeError("Admin password must be at least 12 characters.")

    with db() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'Website',
                status TEXT NOT NULL DEFAULT 'New',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        }

        migrations = {
            "service": (
                "ALTER TABLE leads ADD COLUMN "
                "service TEXT NOT NULL DEFAULT ''"
            ),
            "requirement": (
                "ALTER TABLE leads ADD COLUMN "
                "requirement TEXT NOT NULL DEFAULT ''"
            ),
            "follow_up_date": (
                "ALTER TABLE leads ADD COLUMN "
                "follow_up_date TEXT NOT NULL DEFAULT ''"
            ),
        }

        for column, sql in migrations.items():
            if column not in columns:
                connection.execute(sql)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        existing = connection.execute(
            "SELECT id FROM admin_users WHERE email = ?",
            (admin_email,),
        ).fetchone()

        if not existing:
            count = connection.execute(
                "SELECT COUNT(*) FROM admin_users"
            ).fetchone()[0]

            if count:
                raise RuntimeError(
                    "An admin already exists. Use the password-reset "
                    "procedure; do not create a second admin by changing "
                    "environment variables."
                )

            connection.execute(
                """
                INSERT INTO admin_users (email, password_hash)
                VALUES (?, ?)
                """,
                (admin_email, generate_password_hash(admin_password)),
            )


# -------------------- Authentication helpers --------------------

def csrf_valid():
    supplied = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")

    return bool(
        supplied
        and expected
        and hmac.compare_digest(supplied, expected)
    )


def require_csrf():
    if not csrf_valid():
        return jsonify({
            "error": "CSRF validation failed. Refresh and try again."
        }), 403

    return None


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return jsonify({"error": "Admin login required."}), 401

        return function(*args, **kwargs)

    return wrapped


def validate_follow_up_date(value):
    """Return an ISO date string or None when invalid."""
    if value in ("", None):
        return ""

    if not isinstance(value, str):
        return None

    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


# -------------------- Health check --------------------

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "mode": "production",
        "chat_configured": bool(
            os.getenv("GROQ_API_KEY", "").strip()
        ),
    })


# -------------------- Admin authentication API --------------------

@app.get("/api/auth/csrf")
@limiter.limit("60 per minute")
def get_csrf():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)

    response = jsonify({"csrf_token": session["csrf_token"]})
    response.headers["Cache-Control"] = "no-store"

    return response


@app.post("/api/auth/login")
@limiter.limit("5 per minute")
def login():
    csrf_error = require_csrf()

    if csrf_error:
        return csrf_error

    data = request.get_json(silent=True) or {}

    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")

    if not isinstance(password, str) or not email or not password:
        return jsonify({
            "error": "Email and password are required."
        }), 400

    with db() as connection:
        user = connection.execute(
            """
            SELECT id, email, password_hash
            FROM admin_users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()

    if not user or not check_password_hash(
        user["password_hash"], password
    ):
        return jsonify({"error": "Invalid email or password."}), 401

    session.clear()
    session.permanent = True
    session["admin_id"] = user["id"]
    session["admin_email"] = user["email"]
    session["csrf_token"] = secrets.token_urlsafe(32)

    response = jsonify({
        "ok": True,
        "email": user["email"],
        "csrf_token": session["csrf_token"],
    })
    response.headers["Cache-Control"] = "no-store"

    return response


@app.get("/api/auth/me")
def auth_me():
    if not session.get("admin_id"):
        return jsonify({"authenticated": False}), 401

    return jsonify({
        "authenticated": True,
        "email": session.get("admin_email"),
        "csrf_token": session.get("csrf_token"),
    })


@app.post("/api/auth/logout")
@limiter.limit("20 per minute")
def logout():
    csrf_error = require_csrf()

    if csrf_error:
        return csrf_error

    session.clear()

    response = jsonify({"ok": True})
    response.headers["Cache-Control"] = "no-store"

    return response


# -------------------- AI chatbot API --------------------

@app.post("/api/chat")
@limiter.limit("20 per minute")
def chat():
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key:
        return jsonify({
            "error": "AI is not configured on the backend."
        }), 503

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()

    if not message:
        return jsonify({"error": "message is required"}), 400

    if len(message) > 4000:
        return jsonify({
            "error": "message is too long (maximum 4000 characters)"
        }), 400

    messages = [{
        "role": "system",
        "content": (
            "You are Nexora AI, a helpful business automation assistant "
            "for small businesses and agencies. Answer clearly and "
            "practically, usually in 2–4 sentences. Never claim you "
            "performed an action unless a connected tool confirms it. "
            "If you do not know a business-specific fact, say so."
        ),
    }]

    history = data.get("history", [])

    if isinstance(history, list):
        for item in history[-10:]:
            if not isinstance(item, dict):
                continue

            role = item.get("role")
            content = item.get("content")

            if (
                role in ("user", "assistant")
                and isinstance(content, str)
                and content.strip()
            ):
                messages.append({
                    "role": role,
                    "content": content[:4000],
                })

    messages.append({"role": "user", "content": message})

    payload = json.dumps({
        "model": os.getenv(
            "GROQ_MODEL", "openai/gpt-oss-120b"
        ),
        "messages": messages,
        "temperature": 0.5,
        "max_tokens": 700,
    }).encode("utf-8")

    req = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NexoraAI/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=45) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        answer = result["choices"][0]["message"]["content"].strip()

        if not answer:
            raise ValueError("empty response")

        return jsonify({"reply": answer})

    except HTTPError as exc:
        if exc.code in (401, 403):
            app.logger.error(
                "Groq rejected the backend API credentials."
            )
        else:
            app.logger.error(
                "Groq provider returned HTTP %s.", exc.code
            )

        return jsonify({
            "error": "AI provider request failed. Check backend logs."
        }), 502

    except (URLError, TimeoutError):
        return jsonify({
            "error": "Could not reach the AI provider."
        }), 502

    except (KeyError, IndexError, ValueError, TypeError):
        return jsonify({
            "error": "Unexpected response from the AI provider."
        }), 502


# -------------------- Public lead submission API --------------------

@app.post("/api/leads")
@limiter.limit("10 per minute")
def create_lead():
    data = request.get_json(silent=True) or {}
    required = ("name", "email", "company")

    if any(
        not str(data.get(key, "")).strip()
        for key in required
    ):
        return jsonify({
            "error": "name, email, and company are required"
        }), 400

    values = {
        key: str(data.get(key, "") or "").strip()
        for key in (
            "name",
            "email",
            "company",
            "source",
            "status",
            "service",
            "requirement",
        )
    }

    limits = {
        "name": 120,
        "email": 254,
        "company": 160,
        "source": 80,
        "status": 40,
        "service": 120,
        "requirement": 3000,
    }

    if any(
        len(values[key]) > limit
        for key, limit in limits.items()
    ):
        return jsonify({
            "error": "One or more fields are too long."
        }), 400

    if (
        "@" not in values["email"]
        or "." not in values["email"].split("@")[-1]
    ):
        return jsonify({
            "error": "Please provide a valid email address."
        }), 400

    values["source"] = values["source"] or "Website"
    values["status"] = "New"

    with db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO leads
            (
                name, email, company, source, status,
                service, requirement, follow_up_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '')
            """,
            tuple(
                values[key]
                for key in (
                    "name",
                    "email",
                    "company",
                    "source",
                    "status",
                    "service",
                    "requirement",
                )
            ),
        )

        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    return jsonify(dict(row)), 201


# -------------------- Protected lead management API --------------------

@app.get("/api/leads")
@admin_required
def leads():
    with db() as connection:
        rows = connection.execute(
            "SELECT * FROM leads ORDER BY id DESC"
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@app.patch("/api/leads/<int:lead_id>")
@admin_required
def update_lead(lead_id):
    csrf_error = require_csrf()

    if csrf_error:
        return csrf_error

    data = request.get_json(silent=True) or {}

    allowed = {
        "name",
        "email",
        "company",
        "source",
        "status",
        "service",
        "requirement",
        "follow_up_date",
    }

    data = {
        key: str(value).strip()
        for key, value in data.items()
        if key in allowed and isinstance(value, (str, int, float))
    }

    if not data:
        return jsonify({
            "error": "No supported fields supplied."
        }), 400

    if any(
        not value
        and key not in {
            "service",
            "requirement",
            "follow_up_date",
        }
        for key, value in data.items()
    ):
        return jsonify({
            "error": "Required fields cannot be empty."
        }), 400

    if "follow_up_date" in data:
        parsed_date = validate_follow_up_date(
            data["follow_up_date"]
        )

        if parsed_date is None:
            return jsonify({
                "error": "Follow-up date must be a valid date."
            }), 400

        data["follow_up_date"] = parsed_date

    limits = {
        "name": 120,
        "email": 254,
        "company": 160,
        "source": 80,
        "status": 40,
        "service": 120,
        "requirement": 3000,
    }

    for key, limit in limits.items():
        if key in data and len(data[key]) > limit:
            return jsonify({
                "error": f"{key} is too long."
            }), 400

    if "email" in data:
        email = data["email"]

        if (
            "@" not in email
            or "." not in email.split("@")[-1]
        ):
            return jsonify({
                "error": "Please provide a valid email address."
            }), 400

    with db() as connection:
        cursor = connection.execute(
            "UPDATE leads SET "
            + ", ".join(key + " = ?" for key in data)
            + " WHERE id = ?",
            [*data.values(), lead_id],
        )

        if not cursor.rowcount:
            return jsonify({"error": "Lead not found."}), 404

        row = connection.execute(
            "SELECT * FROM leads WHERE id = ?",
            (lead_id,),
        ).fetchone()

    return jsonify(dict(row))


@app.delete("/api/leads/<int:lead_id>")
@admin_required
def delete_lead(lead_id):
    csrf_error = require_csrf()

    if csrf_error:
        return csrf_error

    with db() as connection:
        cursor = connection.execute(
            "DELETE FROM leads WHERE id = ?",
            (lead_id,),
        )

    if not cursor.rowcount:
        return jsonify({"error": "Lead not found."}), 404

    return "", 204


# -------------------- Analytics API --------------------

@app.get("/api/analytics")
@admin_required
def analytics():
    try:
        days = max(
            1,
            min(365, int(request.args.get("days", "7")))
        )
    except ValueError:
        days = 7

    today = date.today()
    today_string = today.isoformat()
    start = today - timedelta(days=days - 1)

    with db() as connection:
        total = connection.execute(
            "SELECT COUNT(*) FROM leads"
        ).fetchone()[0]

        qualified = connection.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE lower(status) = 'qualified'
            """
        ).fetchone()[0]

        statuses = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM leads
            GROUP BY status
            ORDER BY count DESC
            """
        ).fetchall()

        sources = connection.execute(
            """
            SELECT
                CASE
                    WHEN trim(source) = '' THEN 'Unknown'
                    ELSE source
                END AS source,
                COUNT(*) AS count
            FROM leads
            GROUP BY source
            ORDER BY count DESC
            """
        ).fetchall()

        daily_rows = connection.execute(
            """
            SELECT
                date(created_at) AS day,
                COUNT(*) AS total,
                SUM(
                    CASE
                        WHEN lower(status) = 'qualified' THEN 1
                        ELSE 0
                    END
                ) AS qualified
            FROM leads
            WHERE date(created_at) >= ?
            GROUP BY date(created_at)
            """,
            (start.isoformat(),),
        ).fetchall()

        due = connection.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE trim(COALESCE(follow_up_date, '')) <> ''
              AND date(follow_up_date) <= ?
              AND lower(status) <> 'converted'
            """,
            (today_string,),
        ).fetchone()[0]

        overdue = connection.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE trim(COALESCE(follow_up_date, '')) <> ''
              AND date(follow_up_date) < ?
              AND lower(status) <> 'converted'
            """,
            (today_string,),
        ).fetchone()[0]

        due_today = connection.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE trim(COALESCE(follow_up_date, '')) <> ''
              AND date(follow_up_date) = ?
              AND lower(status) <> 'converted'
            """,
            (today_string,),
        ).fetchone()[0]

        upcoming = connection.execute(
            """
            SELECT COUNT(*) FROM leads
            WHERE trim(COALESCE(follow_up_date, '')) <> ''
              AND date(follow_up_date) > ?
              AND lower(status) <> 'converted'
            """,
            (today_string,),
        ).fetchone()[0]

    daily_map = {
        row["day"]: {
            "date": row["day"],
            "total": row["total"],
            "qualified": row["qualified"] or 0,
        }
        for row in daily_rows
        if row["day"]
    }

    daily = []

    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()

        daily.append(
            daily_map.get(
                day,
                {"date": day, "total": 0, "qualified": 0},
            )
        )

    return jsonify({
        "total": total,
        "qualified": qualified,
        "qualification_rate": round(
            (qualified / total * 100) if total else 0,
            1,
        ),
        "statuses": [
            {"status": row["status"], "count": row["count"]}
            for row in statuses
        ],
        "sources": [
            {
                "source": row["source"] or "Unknown",
                "count": row["count"],
            }
            for row in sources
        ],
        "daily": daily,
        "days": days,
        "follow_ups_due": due,
        "overdue_follow_ups": overdue,
        "today_follow_ups": due_today,
        "upcoming_follow_ups": upcoming,
    })


# Initialize database for Gunicorn as well as direct Python execution.
init()


if __name__ == "__main__":
    app.run(debug=False, port=5000)
