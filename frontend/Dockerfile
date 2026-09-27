FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
# NEXT_PUBLIC_* are inlined into the browser bundle, so they are build args.
ARG NEXT_PUBLIC_DEMO_MODE=false
ARG NEXT_PUBLIC_REVIEWER_NAME=reviewer-12
ENV NEXT_PUBLIC_DEMO_MODE=$NEXT_PUBLIC_DEMO_MODE \
    NEXT_PUBLIC_REVIEWER_NAME=$NEXT_PUBLIC_REVIEWER_NAME \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
# CLAIMGUARD_API_ORIGIN is read per request by the /v1 proxy, so it is a RUNTIME
# setting: `docker run -e CLAIMGUARD_API_ORIGIN=...` retargets the cockpit with
# no rebuild. The default matches the compose service name.
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    CLAIMGUARD_API_ORIGIN=http://api:8000 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
