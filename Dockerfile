# Individual IKR — Docker
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 18501

ENV TELEGRAM_BOT_TOKEN=""
ENV TELEGRAM_SSL_VERIFY=1

HEALTHCHECK CMD python scripts/health_check.py || exit 1

CMD ["streamlit", "run", "streamlit_app/app.py", "--server.port=18501", "--server.address=0.0.0.0"]
