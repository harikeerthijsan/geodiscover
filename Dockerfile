# Railway builds from the repository root. This image ships the discovery engine
# together with a compressed snapshot of the data already fetched from the
# providers; release.py loads it into an empty engine database on first boot, so a
# fresh deployment comes up populated rather than blank.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/discovery_engine ./discovery_engine
COPY backend/gateway.py backend/release.py ./
# Snapshot of the already-fetched provider data, loaded into an empty DB on boot.
COPY backend/discovery_engine_seed.db.gz ./

RUN mkdir -p /app/data

# Railway supplies PORT; the default keeps `docker run` working locally.
ENV PORT=8000
EXPOSE 8000

CMD ["python", "release.py"]
