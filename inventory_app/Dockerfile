FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# Debian trixie supplies PostgreSQL 17 pg_dump/pg_restore for backup operations.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 duck
WORKDIR /srv/duck
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY cloud.py ./
COPY tools ./tools
USER duck
ENV CLOUD_MODE=true PORT=8080
EXPOSE 8080
CMD ["python", "cloud.py"]
