FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py /app/
COPY templates /app/templates
COPY static /app/static

ENV PORT=8000
EXPOSE 8000
CMD ["python", "app.py"]
