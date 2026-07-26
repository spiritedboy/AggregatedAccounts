FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
RUN addgroup -S --gid 10001 app && adduser -S --uid 10001 -G app app
COPY --from=builder --chown=app:app /app ./
COPY --from=builder --chown=app:app /app/.next/standalone ./
USER app
EXPOSE 3000
CMD ["node", "server.js"]
