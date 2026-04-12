FROM python:3.11-slim
WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt
ENV FLASK_APP=web/app.py
CMD ["flask", "run", "--host=0.0.0.0", "--port=8080"]
