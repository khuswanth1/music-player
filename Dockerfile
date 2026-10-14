# syntax=docker/dockerfile:1
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Public, build-time settings (a Spotify Client ID is not a secret; Render passes service env vars as build args).
ARG VITE_SPOTIFY_CLIENT_ID=""
ENV VITE_SPOTIFY_CLIENT_ID=$VITE_SPOTIFY_CLIENT_ID
RUN npm run build

FROM nginx:1.29-alpine
# The official image renders templates/*.template with envsubst at start-up; only the variables listed in
# NGINX_ENVSUBST_FILTER are replaced, so nginx's own $host / $http_upgrade survive.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV BACKEND_UPSTREAM=backend:8000 NGINX_ENVSUBST_FILTER=BACKEND_UPSTREAM
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
