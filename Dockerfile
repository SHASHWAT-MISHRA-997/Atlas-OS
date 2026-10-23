# ATLAS OS API + web UI. Build from the repository root: docker build -t atlas-os .
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ATLAS_ENV=production
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 atlas
COPY backend/app ./app
COPY frontend ./frontend
USER atlas
EXPOSE 8000
# In a container 127.0.0.1 is the container itself. To use Ollama on the host, run with
#   -e ATLAS_OLLAMA_BASE_URL=http://host.docker.internal:11434
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
