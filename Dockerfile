FROM python:3.13-alpine

RUN apk add --no-cache docker-cli docker-cli-compose

COPY app/server.py /app/server.py

EXPOSE 9000

CMD ["python3", "/app/server.py"]
