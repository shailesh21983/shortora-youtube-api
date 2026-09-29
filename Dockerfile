FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY youtube-api.py /app/youtube-api.py

RUN pip install --no-cache-dir flask yt-dlp

EXPOSE 10000

CMD ["python", "youtube-api.py"]
