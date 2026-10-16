# Build the React app, then serve it with unprivileged nginx, which also proxies /api and /rtc.
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.30-alpine
# The official entrypoint renders /etc/nginx/templates/*.template with envsubst, substituting only
# variables that exist in the environment (nginx's own $variables are left untouched).
ENV CB_CSP_CONNECT_EXTRA="ws://localhost:8084 ws://127.0.0.1:8084"
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
