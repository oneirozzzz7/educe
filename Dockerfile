FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY educe/ educe/
COPY deepforge_metrics/ deepforge_metrics/
COPY eval/ eval/
COPY scripts/ scripts/
COPY main.py .

RUN pip install --no-cache-dir -e ".[web]" 2>/dev/null || pip install --no-cache-dir -e .

EXPOSE 7860

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "educe.cli.app", "web", "--host", "0.0.0.0", "--port", "7860"]
