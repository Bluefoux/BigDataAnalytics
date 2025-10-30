FROM python:3.12.4-slim

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY monitor_tool.py /app/

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/monitor_tool.py"]
