# TestSphere-AI frontend: the built dashboard on nginx, which also proxies the
# API (/api, /docs, /openapi.json) to the backend container, so the browser
# talks to one origin (no CORS, no VITE_API_URL).
#   docker build -t testsphere-frontend frontend
#   docker run -p 8080:8080 -e BACKEND_HOST=backend:8000 testsphere-frontend

# ---- Build -------------------------------------------------------------------
FROM node:24-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Serve -------------------------------------------------------------------
# nginx-unprivileged runs as uid 101 and listens on 8080
FROM nginxinc/nginx-unprivileged:1.28-alpine

# Where /api goes (host:port), and the DNS server that resolves it at request
# time, so a recreated backend container (new IP) is found without a restart.
# 127.0.0.11 is Docker's own DNS on compose / user-defined networks.
ENV BACKEND_HOST=backend:8000 \
    NGINX_RESOLVER=127.0.0.11

# The image's entrypoint fills ${BACKEND_HOST} and ${NGINX_RESOLVER} into
# /etc/nginx/conf.d/default.conf at start (only those: nginx's own $variables stay)
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /src/dist /usr/share/nginx/html

# The base image's unprivileged user, stated so it cannot silently change
USER 101

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
