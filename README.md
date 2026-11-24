# Nexora AI backend (local development)

1. Open a terminal in this `backend` folder.
2. Install dependencies: `python -m pip install -r requirements.txt`
3. Set your Groq key in the terminal environment (never in frontend files): `set GROQ_API_KEY=your_key_here` on Windows CMD.
4. Start the API: `python app.py`
5. Check `http://127.0.0.1:5000/api/health`.

The API migrates an existing `nexora.db` by adding `service` and `requirement` columns without deleting saved leads. `GET /api/analytics?days=7` returns counts derived from actual lead records. CORS is open for local development only; restrict it before deployment. This is not production-ready and does not implement authentication.
