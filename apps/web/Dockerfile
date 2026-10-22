FROM node:20-slim

WORKDIR /app

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

# Enable pnpm via corepack for fast, deterministic package management
RUN corepack enable && corepack prepare pnpm@latest --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 3000

CMD ["pnpm", "run", "start"]
