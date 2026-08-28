FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /app/runtime /app/logs \
    && chown -R appuser:appuser /app /data

USER appuser
EXPOSE 8000
CMD ["python", "scripts/run_api.py"]
