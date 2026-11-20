FROM python:3.12-slim
RUN pip install --no-cache-dir boto3
WORKDIR /app
COPY app/pairs.py /app/pairs.py
ENTRYPOINT ["python", "/app/pairs.py"]
