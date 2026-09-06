# Architecture

Browser (127.0.0.1:5173) → FastAPI (127.0.0.1:8000) → SQLite WAL + job rows → worker process → NCBI E-utilities / GEO HTTPS FTP / optional OpenAI-compatible LLM → evidence snapshots → Excel.

The model never executes tools or shell commands. A state machine chooses the next step; model output is schema-checked JSON.

Credential store lives in the API process. The worker may fetch them only from `/internal/credentials/{session_id}` with a localhost token stored in `data/.internal_token`.
