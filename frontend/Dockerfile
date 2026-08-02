# syntax=docker/dockerfile:1.7
#
# Three stages, same shape as backend/Dockerfile: a dependency layer keyed on the
# manifest alone, a build layer, and a runtime layer that carries neither the
# toolchain nor the sources it was built from, and does not run as root.

# ---------------------------------------------------------------- deps
FROM node:24-alpine AS deps

WORKDIR /build

# Keyed on the manifest alone, so editing a component does not invalidate the
# (slow) install layer. `npm ci` installs the lockfile exactly — `npm install`
# would be free to resolve a different tree inside the image than the one the
# tests ran against.
COPY package.json package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------- builder
FROM node:24-alpine AS builder

WORKDIR /build

ENV NEXT_TELEMETRY_DISABLED=1 \
    NODE_ENV=production

# A NEXT_PUBLIC_* value is inlined into the browser bundle at build time, so it
# has to arrive as a build argument. Passing it only as a container environment
# variable reaches the server process and never the browser, which is the quiet
# way this ends up pointing at the wrong API.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

COPY --from=deps /build/node_modules ./node_modules
COPY . .

RUN npm run build

# ---------------------------------------------------------------- runtime
FROM node:24-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Same uid as the backend image, for the same reason: a volume written by one
# container stays readable by the other, and neither runs as root.
RUN addgroup -g 10001 -S mnemos \
 && adduser -S -u 10001 -G mnemos mnemos

# `output: "standalone"` traced the server's real module graph in the builder,
# so this copies a minimal node_modules and a generated server.js instead of the
# whole dependency tree. Static assets and public/ are not traced and come over
# separately.
COPY --from=builder --chown=mnemos:mnemos /build/public ./public
COPY --from=builder --chown=mnemos:mnemos /build/.next/standalone ./
COPY --from=builder --chown=mnemos:mnemos /build/.next/static ./.next/static

USER mnemos
EXPOSE 3000

CMD ["node", "server.js"]
