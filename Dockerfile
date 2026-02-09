FROM python:3.11-slim

COPY requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir -r /tmp/requirements.txt

RUN mkdir -p /app /config /reports

COPY src/orchestrator.py /app/

WORKDIR /app

RUN chmod +x orchestrator.py

CMD ["python", "orchestrator.py"]
