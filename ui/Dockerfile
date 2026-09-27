FROM node:22-alpine AS build
WORKDIR /ui
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:22-alpine
WORKDIR /ui
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /ui/.next/standalone ./
COPY --from=build /ui/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
