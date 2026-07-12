FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p instance logs static/uploads && \
    chmod -R 755 static/uploads

EXPOSE 5000

CMD ["gunicorn", "wsgi:application", "--bind", "0.0.0.0:5000", "--workers", "4", "--threads", "2", "--worker-class", "gthread", "--timeout", "60", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "100", "--access-logfile", "-"]
