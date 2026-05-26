# v5.0.0 — PostgreSQL Edition: No GitHub, uses Railway PostgreSQL for data persistence
FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for voice recording/conversion support
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Install libpq-dev for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py callv2.py foxapp_api.py db.py translations.py /app/

# Create data and recordings directories
RUN mkdir -p /app/data/recordings

# DATA_DIR: where local JSON data files are stored (backup only, DB is primary).
# DATABASE_URL: PostgreSQL connection string (required for data persistence).
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

CMD ["python", "bot.py"]
