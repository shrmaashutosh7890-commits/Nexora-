"""Nexora AI local development API. Not production-ready."""
from flask import Flask, jsonify, request
import json
import os
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import date, timedelta
from contextlib import contextmanager

app = Flask(__name__)
DB = Path(__file__).with_name('nexora.db')

# Development-only CORS. Restrict this to your deployed frontend before production.
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
    return response

@app.route('/api/<path:_path>', methods=['OPTIONS'])
def api_options(_path):
    return ('', 204)

@contextmanager
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def init():
    """Create tables and safely add new columns to an existing local database."""
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            company TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'Website',
            status TEXT NOT NULL DEFAULT 'New',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        existing = {row['name'] for row in c.execute('PRAGMA table_info(leads)').fetchall()}
        if 'service' not in existing:
            c.execute("ALTER TABLE leads ADD COLUMN service TEXT NOT NULL DEFAULT ''")
        if 'requirement' not in existing:
            c.execute("ALTER TABLE leads ADD COLUMN requirement TEXT NOT NULL DEFAULT ''")

def ensure_db():
    init()

@app.get('/')
def home():
    ensure_db()
    return jsonify({'service': 'Nexora AI API', 'health': '/api/health', 'leads': '/api/leads', 'analytics': '/api/analytics', 'chat': '/api/chat'})

@app.get('/api/health')
def health():
    ensure_db()
    return jsonify({'status': 'ok', 'mode': 'development', 'chat_configured': bool(os.getenv('GROQ_API_KEY', '').strip())})

@app.post('/api/chat')
def chat():
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        return jsonify({'error': 'AI is not configured. Set GROQ_API_KEY on the backend.'}), 503
    data = request.get_json(silent=True) or {}
    message = str(data.get('message', '')).strip()
    if not message:
        return jsonify({'error': 'message is required'}), 400
    if len(message) > 4000:
        return jsonify({'error': 'message is too long (maximum 4000 characters)'}), 400

    messages = [{'role': 'system', 'content': (
        'You are Nexora AI, a helpful business automation assistant for small businesses and agencies. '
        'Answer clearly, practically, and conversationally, usually in 2–4 sentences. '
        'Understand the user message before suggesting solutions. Do not give long lists or unsolicited business plans. '
        'Ask one relevant follow-up question when appropriate. Provide detailed steps only when asked. '
        'Never claim you performed an action unless a connected tool confirms it. '
        'If you do not know a business-specific fact, say so honestly.'
    )}]
    history = data.get('history', [])
    if isinstance(history, list):
        for item in history[-10:]:
            if not isinstance(item, dict):
                continue
            role, content = item.get('role'), item.get('content')
            if role in ('user', 'assistant') and isinstance(content, str) and content.strip():
                messages.append({'role': role, 'content': content[:4000]})
    messages.append({'role': 'user', 'content': message})
    payload = json.dumps({
        'model': os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b'),
        'messages': messages, 'temperature': 0.5, 'max_tokens': 700
    }).encode('utf-8')
    req = Request('https://api.groq.com/openai/v1/chat/completions', data=payload,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json', 'User-Agent': 'NexoraAI/1.0'}, method='POST')
    try:
        with urlopen(req, timeout=45) as response:
            result = json.loads(response.read().decode('utf-8'))
        answer = result['choices'][0]['message']['content'].strip()
        if not answer:
            raise ValueError('empty response')
        return jsonify({'reply': answer})
    except HTTPError as exc:
        try: detail = exc.read().decode('utf-8')[:1000]
        except Exception: detail = 'Provider returned an HTTP error.'
        return jsonify({'error': f'AI provider error ({exc.code}).', 'detail': detail}), 502
    except (URLError, TimeoutError):
        return jsonify({'error': 'Could not reach the AI provider. Check your internet connection.'}), 502
    except (KeyError, IndexError, ValueError, TypeError):
        return jsonify({'error': 'Unexpected response from the AI provider.'}), 502

@app.get('/api/leads')
def leads():
    ensure_db()
    with db() as c:
        rows = c.execute('SELECT * FROM leads ORDER BY id DESC').fetchall()
    return jsonify([dict(row) for row in rows])

@app.post('/api/leads')
def create_lead():
    ensure_db()
    data = request.get_json(silent=True) or {}
    required = ('name', 'email', 'company')
    if any(not str(data.get(key, '')).strip() for key in required):
        return jsonify({'error': 'name, email, and company are required'}), 400
    values = {key: str(data.get(key, '') or '').strip() for key in ('name','email','company','source','status','service','requirement')}
    values['source'] = values['source'] or 'Website'
    values['status'] = values['status'] or 'New'
    with db() as c:
        cur = c.execute("INSERT INTO leads (name,email,company,source,status,service,requirement) VALUES (?,?,?,?,?,?,?)", tuple(values[k] for k in ('name','email','company','source','status','service','requirement')))
        row = c.execute('SELECT * FROM leads WHERE id = ?', (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201

@app.patch('/api/leads/<int:lead_id>')
def update_lead(lead_id):
    ensure_db()
    data = request.get_json(silent=True) or {}
    allowed = {'name','email','company','source','status','service','requirement'}
    data = {key: str(value).strip() for key, value in data.items() if key in allowed}
    if not data:
        return jsonify({'error': 'no supported fields supplied'}), 400
    if any(not value for value in data.values()):
        # Empty service/requirement are valid and can be cleared.
        if any(key not in {'service','requirement'} and not value for key, value in data.items()):
            return jsonify({'error': 'name, email, company, source, and status cannot be empty'}), 400
    with db() as c:
        cur = c.execute('UPDATE leads SET ' + ', '.join(key + ' = ?' for key in data) + ' WHERE id = ?', [*data.values(), lead_id])
        if not cur.rowcount:
            return jsonify({'error': 'lead not found'}), 404
        row = c.execute('SELECT * FROM leads WHERE id = ?', (lead_id,)).fetchone()
    return jsonify(dict(row))

@app.delete('/api/leads/<int:lead_id>')
def delete_lead(lead_id):
    ensure_db()
    with db() as c:
        cur = c.execute('DELETE FROM leads WHERE id = ?', (lead_id,))
    if not cur.rowcount:
        return jsonify({'error': 'lead not found'}), 404
    return '', 204

@app.get('/api/analytics')
def analytics():
    """Analytics derived only from saved lead records; no fabricated traffic/revenue."""
    ensure_db()
    try: days = max(1, min(365, int(request.args.get('days', '7'))))
    except ValueError: days = 7
    today = date.today()
    start = today - timedelta(days=days - 1)
    with db() as c:
        total = c.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
        qualified = c.execute("SELECT COUNT(*) FROM leads WHERE lower(status) = 'qualified'").fetchone()[0]
        statuses = c.execute('SELECT status, COUNT(*) AS count FROM leads GROUP BY status ORDER BY count DESC').fetchall()
        sources = c.execute("SELECT CASE WHEN trim(source) = '' THEN 'Unknown' ELSE source END AS source, COUNT(*) AS count FROM leads GROUP BY source ORDER BY count DESC").fetchall()
        daily_rows = c.execute("SELECT date(created_at) AS day, COUNT(*) AS total, SUM(CASE WHEN lower(status) = 'qualified' THEN 1 ELSE 0 END) AS qualified FROM leads WHERE date(created_at) >= ? GROUP BY date(created_at)", (start.isoformat(),)).fetchall()
    daily_map = {row['day']: {'date': row['day'], 'total': row['total'], 'qualified': row['qualified'] or 0} for row in daily_rows if row['day']}
    daily = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        daily.append(daily_map.get(day, {'date': day, 'total': 0, 'qualified': 0}))
    return jsonify({'total': total, 'qualified': qualified, 'qualification_rate': round((qualified / total * 100) if total else 0, 1),
        'statuses': [{'status': r['status'], 'count': r['count']} for r in statuses],
        'sources': [{'source': r['source'] or 'Unknown', 'count': r['count']} for r in sources], 'daily': daily, 'days': days})

if __name__ == '__main__':
    init()
    app.run(debug=True, port=5000)
