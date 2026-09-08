# Architecture

Launcher or Vite UI → FastAPI (`127.0.0.1:8000`) → SQLite WAL + job rows → worker (same process when launched, or a second process in development) → NCBI E-utilities / GEO HTTPS FTP / optional OpenAI-compatible LLM → evidence snapshots → Excel.

- Double-click `GEOScout.bat` (or the packaged `GEOScout.exe`) serves the built UI from the API on port 8000 and runs the worker in-process.
- `npm run dev` still uses Vite on `127.0.0.1:5173` with a separate API and worker.

The model never executes tools or shell commands. A state machine chooses the next step; model output is schema-checked JSON.

Credential store lives in the API process. A separate worker may fetch them only from `/internal/credentials/{session_id}` with a localhost token stored in `data/.internal_token`.
