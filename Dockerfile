FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libmariadb-dev libmariadb-dev-compat pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
