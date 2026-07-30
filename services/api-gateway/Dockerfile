# BankLens REST bridge (services/api-gateway) — production container.
#
# Build from the REPO ROOT (not this directory) — the image needs source from
# three parts of the repo, matching how PYTHONPATH is wired in local dev:
#
#   docker build -f services/api-gateway/Dockerfile -t banklens-bridge .
#   docker run -p 8791:8791 -v "%cd%/data:/app/data" banklens-bridge
#
# `data/` is mounted as a volume, not baked in — it's the "database" here
# (landed Bronze/Silver/crosswalk JSON), not application code.
FROM python:3.13-slim

WORKDIR /app

# Preserve the exact relative directory depth the two REPO=Path(__file__)...
# computations expect (bridge_server.py: parents[3]; data.py: parents[4]) —
# copying anywhere else silently breaks their repo-root resolution.
COPY services/mcp-server/src /app/services/mcp-server/src
COPY pipelines/transforms/src /app/pipelines/transforms/src
COPY services/api-gateway/src /app/services/api-gateway/src
# Small, VERSIONED model artifacts (e.g. ml/deposit_flight/model_card.json) — these
# are checked into git, unlike data/, so they're baked into the image like source,
# not runtime-mounted. Found live: omitting this made get_risk_score fail with
# "Deposit-flight model not trained yet" in an otherwise-working container.
COPY ml /app/ml

ENV PYTHONPATH=/app/services/mcp-server/src:/app/pipelines/transforms/src
ENV PYTHONUNBUFFERED=1
# 0.0.0.0 is required for the port mapping to work — the container's own network
# namespace (not this bind address) is what actually controls external exposure.
ENV BANKLENS_BRIDGE_HOST=0.0.0.0

EXPOSE 8791

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8791/api/health', timeout=3)" || exit 1

# Non-root: this is a public-data reference service, no reason to run as root.
RUN useradd --create-home --uid 1000 banklens
USER banklens

CMD ["python", "services/api-gateway/src/bridge_server.py"]
