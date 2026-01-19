FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ENABLECORS=false

WORKDIR /app

# Install pip requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy the whole project (paths in app are root-based)
COPY . /app

EXPOSE 8501

CMD ["streamlit", "run", "frontend/main.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
