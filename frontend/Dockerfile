FROM docker.m.daocloud.io/library/node:22-alpine AS build

WORKDIR /app

ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_API_TIMEOUT_MS=60000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_API_TIMEOUT_MS=$VITE_API_TIMEOUT_MS

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM docker.m.daocloud.io/library/nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
