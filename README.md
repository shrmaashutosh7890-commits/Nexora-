# Nexora AI — local demo + lead database

## Run the backend
- Open CMD in `nexora-ai/backend`.
- Run `python -m pip install -r requirements.txt`.
- If using Groq AI, set `GROQ_API_KEY` in that terminal (do not place the key in JavaScript).
- Run `python app.py`; keep the terminal open.

## Open the website
- Open `index.html` in Chrome.
- Website enquiries are saved through `POST /api/leads`.
- The Ask Nexora chat uses `POST /api/chat` and needs a valid Groq key.
- Open `dashboard.html` to manage the saved leads. Charts and lead counts are computed from SQLite records, not invented traffic numbers.

## What is connected
- Live: lead CRUD, enquiry form, lead status/source/date charts, source breakdown, CSV export, Groq chat (when configured).
- Demo/local only: appointments, client workspaces, workflow simulation, email drafts, voice-agent settings. They do not send real email or place calls.
- No revenue or website visitor tracking is claimed.

## Notes
- The database is `backend/nexora.db`; the first run creates it. Existing databases are migrated without deleting lead rows.
- CORS is open for local development. Do not deploy this backend publicly without authentication, restricted CORS, secret management, validation, and production server configuration.
