FROM python:3.12.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

RUN useradd --system --uid 10001 --no-create-home appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Config por defecto; en producción compose la monta :ro por encima
COPY config/events.yaml ./config/events.yaml

# El volumen con nombre traccar-ntfy-state se monta vacío en /srv/state y
# hereda el dueño del directorio creado aquí (debe existir ANTES del USER).
RUN mkdir -p /srv/state && chown appuser:appuser /srv/state

USER appuser
EXPOSE 8080

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
