# BankLens data-refresh job (pipelines/) — the scheduled quarterly re-landing.
#
# Deliberately a SEPARATE image from services/api-gateway/Dockerfile. The bridge
# serves landed data read-only and never needs the connectors; this job is the
# opposite — it reaches the public source APIs and WRITES to data/. Different
# dependencies, different privileges, different lifecycle (a CronJob that exits,
# not a long-lived server), so they don't share an image.
#
# Build from the REPO ROOT (not this directory):
#
#   docker build -f pipelines/Dockerfile -t banklens-refresh .
#   docker run -v "%cd%/data:/app/data" banklens-refresh
FROM python:3.13-slim

WORKDIR /app

# QuantLib backs the DCF stress-test variant in banklens_transforms.stress. psycopg
# is pulled in by banklens_common.db, which filings_cli imports at module load —
# found live: without it the container dies on `import` before a single DAG stage
# runs, rather than failing just the one stage that needs a database.
# The connectors themselves need nothing beyond the standard library by design.
RUN pip install --no-cache-dir QuantLib "psycopg[binary]>=3.2"

# Preserve the exact relative directory depth the Path(__file__).parents[N]
# computations expect (quarterly_refresh.py: parents[3]; the CLIs: parents[4]) —
# copying anywhere else silently breaks their repo-root resolution.
COPY pipelines/ingestion/src /app/pipelines/ingestion/src
COPY pipelines/transforms/src /app/pipelines/transforms/src
COPY pipelines/orchestration/src /app/pipelines/orchestration/src
COPY libs/python/banklens_common/src /app/libs/python/banklens_common/src
# Versioned model artifacts: the deposit-flight retrain stage rewrites
# ml/deposit_flight/model_card.json, so the directory must exist in the image.
COPY ml /app/ml

ENV PYTHONPATH=/app/pipelines/orchestration/src:/app/pipelines/ingestion/src:/app/pipelines/transforms/src:/app/libs/python/banklens_common/src
ENV PYTHONUNBUFFERED=1

# Non-root, same posture as the bridge. Owns /app/data so the mounted volume is
# writable — unlike the bridge, this job's whole purpose is to write there.
RUN useradd --create-home --uid 1000 banklens \
    && mkdir -p /app/data && chown -R banklens:banklens /app/data /app/ml
USER banklens

# Overridden by the CronJob's args to pass --repdte / --land-sod etc.
CMD ["python", "-m", "banklens_orchestration.quarterly_refresh"]
