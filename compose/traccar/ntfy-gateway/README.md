# Gateway ntfy de Traccar

Recibe eventos de Traccar (`event.forward`) y los reenvía como avisos push
a [ntfy.sh](https://ntfy.sh), a los usuarios que Traccar dice que tienen
acceso a cada dispositivo (no a un único tema fijo). Soporta perfiles con
ventanas horarias, cooldown y estado persistente en SQLite (sobrevive a un
reinicio del contenedor: cooldowns, temporizadores de `offline_sustained` e
historial de envíos).

- **Administración** (crear la cuenta de servicio, `.env`, perfiles,
  ventanas, logs, `/history`, reiniciar el estado, probar sin mover un
  vehículo): [docs/MANUAL-ADMIN.md](docs/MANUAL-ADMIN.md)
- **Para quien recibe los avisos** (instalar ntfy, configurar tu tema,
  qué significa cada aviso): [docs/MANUAL-USUARIO.md](docs/MANUAL-USUARIO.md)

## Arquitectura

```
Traccar (event.forward) --HTTP--> gateway ntfy --HTTP--> ntfy.sh --push--> celulares
                                       |
                                       +--API Traccar (solo lectura)--> usuarios/dispositivos
                                       |
                                       +--SQLite (traccar-ntfy-state)--> cooldowns,
                                                                          offline_sustained,
                                                                          historial
```

- Responde `200` de inmediato a Traccar; el envío a ntfy corre en segundo
  plano con reintentos y nunca bloquea ni hace fallar el evento.
- Un solo worker de uvicorn: SQLite no está pensado para escritura
  concurrente entre procesos.
- El volumen de estado (`traccar-ntfy-state`) **no forma parte de las
  copias de seguridad**: es reconstruible.

## Desarrollo

```bash
cd ntfy-gateway
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Configuración

Ver `example.env` (raíz de `compose/traccar/`) para las variables, y
`config/events.yaml` para reglas, perfiles y ventanas horarias.
