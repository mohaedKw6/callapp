FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py callv2.py foxapp_api.py /app/

# Copy default data files into /app/data/ — these serve as templates.
# On Railway with a volume mounted at /app/data, the volume takes precedence
# and its contents persist across deploys/restarts. The _init_data_dir()
# function in callv2.py will copy from these defaults only when a file
# does NOT already exist in the volume.
COPY data/ /app/data/

# Create recordings directory
RUN mkdir -p /app/data/recordings

# DATA_DIR: persistent storage directory.
# - Default: /app/data (works with Railway volumes)
# - On Railway: attach a volume at /app/data so data survives restarts.
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PUBLIC_URL=https://eaiupvh6.up.railway.app

EXPOSE 8080

CMD ["python", "bot.py"]
