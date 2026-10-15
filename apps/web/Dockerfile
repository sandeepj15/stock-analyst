FROM node:20-slim

WORKDIR /app

ENV PORT=3000 \
    HOSTNAME="0.0.0.0"

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
