# Gambit — API + built frontend (craft trains on GitHub Actions, not here)
FROM node:20-alpine AS web
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts/bootstrap_model.sh scripts/start_cloud.sh ./scripts/
RUN pip install --no-cache-dir -e .
COPY --from=web /app/frontend/dist ./frontend/dist
ENV CRAFT_DISABLE=1 \
    STAKE_USE_BROWSER=false \
    STAKE_BROWSER_WARMUP_ON_STARTUP=false \
    GAMBIT_FRONTEND_DIST=/app/frontend/dist \
    GAMBIT_HOST=0.0.0.0 \
    GAMBIT_PORT=10000 \
    GAMBIT_REPO=abhyvx/Gambit
EXPOSE 10000
CMD ["bash", "scripts/start_cloud.sh"]
