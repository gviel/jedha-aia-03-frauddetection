FROM python:3.12-slim

WORKDIR /app

# libgomp1 : requis par LightGBM (libgomp.so.1, absent de l'image slim)
# curl : utilisé par le healthcheck Docker (docker-compose.yml), absent de l'image slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/app.py .
COPY api/schemas.py .

# Le répertoire model/ est monté en volume (docker-compose.yml)
# afin que le modèle puisse être mis à jour sans rebuild d'image
RUN mkdir -p model

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
