FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLCONFIGDIR=/app/logs/.matplotlib

WORKDIR /app

COPY requirements.txt requirements-webull.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt -r requirements-webull.txt

COPY . /app

RUN mkdir -p /app/logs /app/runtime_data /app/backups /app/.webull_tokens \
    && chown -R 1000:1000 /app/logs /app/runtime_data /app/backups /app/.webull_tokens

USER 1000:1000

CMD ["python", "run_app.py", "--host", "127.0.0.1", "--port", "8765"]
