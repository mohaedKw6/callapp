FROM python:3.11-slim
WORKDIR /app
COPY server_requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY call_server.py .
EXPOSE 8000
CMD uvicorn call_server:app --host 0.0.0.0 --port ${PORT:-8000}
