FROM python:3.11-slim

# Optimisations Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 1. On définit le fuseau horaire (Europe/Paris)
ENV TZ=Europe/Paris

# 2. On installe le paquet nécessaire pour gérer l'heure
RUN apt-get update && \
    apt-get install -y tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean

WORKDIR /app

# Installation des libs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie des fichiers
COPY sync.py .
COPY credentials.json .

# Lancement
CMD ["python", "sync.py"]