FROM node:22-slim AS frontend
WORKDIR /src
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY . .
COPY --from=frontend /src/py/visdom/static py/visdom/static
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir . \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
RUN python -c "from visdom.server.build import download_scripts; download_scripts()"
RUN ln -s /data /root/.visdom

ENV PYTHONUNBUFFERED=1
EXPOSE 8097
VOLUME /data
ENTRYPOINT ["python", "-m", "visdom.server", "-env_path", "/data"]
CMD ["-port", "8097"]
