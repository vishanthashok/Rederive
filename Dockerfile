FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY sdk ./sdk
COPY server ./server
RUN pip install --no-cache-dir ".[server]"
COPY demo_agent ./demo_agent
COPY eval ./eval
COPY scenarios ./scenarios
ENV PYTHONPATH=/app/sdk:/app
EXPOSE 8000
# Hosts like Railway and Render set PORT. Locally it falls back to 8000.
CMD ["sh", "-c", "exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
