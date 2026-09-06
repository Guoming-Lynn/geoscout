FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json /web/package.json
COPY frontend /web
RUN npm install && npm run build

FROM nginx:1.27-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
