# BankLens quant terminal — production container (multi-stage: build, then serve).
#
# Build from this directory:
#   docker build -t banklens-web .
#   docker run -p 8080:80 banklens-web
#
# The bridge URL and OIDC provider are build-time args (Vite inlines
# import.meta.env.VITE_* at build time, not runtime — there is no server-side
# process in the nginx stage to read env vars from). Both default to the
# localhost bridge/Keycloak docker-compose.dev.yml starts, so a bare
# `docker build` still works unchanged for local Docker/K8s testing (the
# browser resolves "localhost" against the USER's machine, not the container
# network). Pass real values for a non-localhost deployment:
#   docker build --build-arg VITE_API_BASE=https://api.example.com/api \
#                 --build-arg VITE_KEYCLOAK_URL=https://auth.example.com \
#                 -t banklens-web .

FROM node:22-slim AS build
WORKDIR /app
ARG VITE_API_BASE=http://localhost:8791/api
ARG VITE_KEYCLOAK_URL=http://localhost:8081
ENV VITE_API_BASE=${VITE_API_BASE}
ENV VITE_KEYCLOAK_URL=${VITE_KEYCLOAK_URL}
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
