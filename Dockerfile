# v4.1.0 — robust message deletion with retry + HTTP fallback, fix 401 polling
FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for voice recording/conversion support
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py callv2.py foxapp_api.py github_sync.py translations.py /app/

# Create data directory (files will be pulled from GitHub data-sync branch on startup)
RUN mkdir -p /app/data/recordings

# DATA_DIR: where local JSON data files are stored.
# GH_TOKEN: GitHub token for persistent storage via GitHub API.
# GH_REPO:  GitHub repo for data storage (default: mohaedKw6/callapp).
# GH_BRANCH: Branch for data sync (default: data-sync — separate from main to avoid rebuilds).
# SYNC_INTERVAL: seconds between auto-sync to GitHub (default: 600).
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PUBLIC_URL=https://eaiupvh6.up.railway.app

EXPOSE 8080

CMD ["python", "bot.py"]
