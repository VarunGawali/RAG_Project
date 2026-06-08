# ── Contract360 frontend — React + Vite → nginx ───────────────────────────────
#
# Build:
#   docker build \
#     --build-arg VITE_API_BASE_URL=https://contract360-api.azurecontainerapps.io \
#     -t contract360-ui ./frontend
#
# Run (local):
#   docker run -p 3000:80 contract360-ui
# ─────────────────────────────────────────────────────────────────────────────

# Stage 1 — build the React app
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# VITE_API_BASE_URL must be the full URL of the deployed backend, e.g.
# https://contract360-api.azurecontainerapps.io
# It is baked into the JS bundle at build time by Vite.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

# Stage 2 — serve with nginx
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
