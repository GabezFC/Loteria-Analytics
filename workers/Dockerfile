FROM python:3.13.9-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir 'psycopg[binary]==3.2.13' -r requirements.txt
COPY *.py ./
USER 10001:10001
CMD ["python", "probe.py"]
