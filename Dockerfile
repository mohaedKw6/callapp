FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py callv2.py foxapp_api.py /app/
COPY data/bot_data.json data/telicall_accounts.json /app/data/

# Create recordings directory
RUN mkdir -p /app/recordings

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV PUBLIC_URL=https://eaiupvh6.up.railway.app

EXPOSE 8080

CMD ["python", "bot.py"]
