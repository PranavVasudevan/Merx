# BankLens quant terminal — production container (multi-stage: build, then serve).
#
# Build from this directory:
#   docker build -t banklens-web .
#   docker run -p 8080:80 banklens-web
#
# Honest local-only note: the frontend calls the bridge at a hardcoded
# http://localhost:8791/api (src/api.ts) — this works for local Docker/K8s
# testing (the browser resolves "localhost" against the USER's machine, not the
# container network, so it just needs the bridge's port published/forwarded to
# the host), but would need to become configurable (build-time env or a reverse
# proxy) for any real non-localhost deployment — that's Phase 5+ hardening.

FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD wget -q -O /dev/null http://localhost/ || exit 1
