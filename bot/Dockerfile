FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir "python-telegram-bot[webhooks]>=21.0" httpx>=0.27.0
COPY . .
CMD ["python", "telegram_bot.py"]
