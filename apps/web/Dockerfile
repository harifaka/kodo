# syntax=docker/dockerfile:1

# ---- build -------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---- runtime -----------------------------------------------------------------
# nginx-unprivileged already provisions /tmp pid + temp paths for the non-root `nginx` user.
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /build/dist /usr/share/nginx/html

USER nginx

EXPOSE 8080

# Static UI only: the API reachability is asserted by the compose healthcheck on /health.
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=10 \
    CMD wget --spider -q -O /dev/null http://127.0.0.1:8080/ || exit 1
