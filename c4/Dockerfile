FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit google-genai

COPY app.py .

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]