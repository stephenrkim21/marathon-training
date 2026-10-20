FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY server ./server
COPY public ./public
RUN groupadd --gid 10001 runner && useradd --uid 10001 --gid 10001 --create-home runner && mkdir /data && chown runner:runner /data
ENV DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-m", "server.entrypoint"]
