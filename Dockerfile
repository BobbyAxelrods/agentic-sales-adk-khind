# KHIND sales agent: the Chatwoot webhook app (apps.main:app) for Cloud Run.
# Only requirements.txt, constraints.txt and apps/ go into the image (see .dockerignore and
# .gcloudignore). Secrets come from Secret Manager at run time, never from the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY apps/ apps/

RUN useradd --create-home --uid 10001 app
USER app

# Cloud Run sets PORT. exec makes uvicorn PID 1, so it receives SIGTERM.
CMD exec uvicorn apps.main:app --host 0.0.0.0 --port ${PORT:-8080}
