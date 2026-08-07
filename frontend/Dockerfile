# syntax=docker/dockerfile:1

# =============================================================================
# The syncr frontend image: the Vite build, served by Caddy.
#
# TWO STAGES, and the second carries no node. The application is static files
# after `vite build`, so shipping the toolchain that produced them would put a
# package manager and four hundred dependencies on the deployed host for nothing.
#
# `npm ci` rather than `npm install`, so the image is built from the committed
# lockfile and never resolves a different tree than CI did.
#
# The build runs `tsc --noEmit` before it emits anything, because that is what
# `npm run build` is: vitest transpiles with esbuild and strips types without
# checking them, so this is one of the two places a type error is caught.
#
# CADDY REVERSE-PROXIES THE API PATHS, which is what makes the browser talk to
# ONE origin. The session cookie is `SameSite=Lax` and every unsafe method is
# behind an origin check, so a second origin for the api would be rejected rather
# than merely inconvenient. `Caddyfile` is where that list lives.
#
# Built from the REPO-ROOT context, like every other image here, so one
# `.dockerignore` governs every build.
# =============================================================================

FROM node:22.22-bookworm-slim AS builder

WORKDIR /build

# Dependency layer. Only the manifests, so a source-only change reuses it.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# The build inputs. `openapi.json` is committed and `src/api/schema.d.ts` is
# generated from it, so this needs no backend to build against.
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
FROM caddy:2.11.4-alpine AS runtime

COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=builder /build/dist /srv

# No host port is published anywhere: the Cloudflare tunnel is the only ingress
# and it reaches this on `app-net`.
EXPOSE 8080
