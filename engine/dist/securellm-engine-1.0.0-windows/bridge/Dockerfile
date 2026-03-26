FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py .

RUN groupadd -r bridge && useradd -r -g bridge -d /app bridge
USER bridge

CMD ["python", "bridge.py"]
