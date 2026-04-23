FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py callv2.py foxapp_api.py /app/
COPY data/ /app/data/

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV BOT_TOKEN=8383451832:AAFqpcQKsbssGDknsjUR3qJLxcwXq7VsyfY
ENV PUBLIC_URL=https://eaiupvh6.up.railway.app
EXPOSE 8080

CMD ["python", "bot.py"]
