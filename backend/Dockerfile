FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini
COPY backend/tests/fixtures /app/tests/fixtures
RUN pip install --no-cache-dir .
ENV GEOSCOUT_HOST=127.0.0.1
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
