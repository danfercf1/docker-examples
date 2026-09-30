# Backup de Traccar

Backup de la base de datos PostgreSQL de Traccar con retención y réplica
fuera del VPS (Vostro, detrás de NAT). Aviso por [ntfy.sh](https://ntfy.sh)
**solo en fallo**.

## Arquitectura

```
VPS (03:00 La Paz)                    Vostro (05:00 La Paz)
┌──────────────────────────┐  rsync   ┌────────────────────────────┐
│ traccar-backup.timer     │  por SSH │ traccar-backup-pull.timer  │
│  └─ traccar-backup.sh    │ ───────> │  └─ traccar-backup-pull.sh │
│     pg_dump -Fc          │  clave   │     rsync -a (sin --delete)│
│     valida pg_restore -l │  dedicada│     retención local 60 días│
│     /home/danfercf/      │  rrsync  │     /home/daniel/backups/  │
│     backups/traccar/     │  -ro     │     traccar-vps/           │
└──────────────────────────┘          └────────────────────────────┘
```

| Archivo | Dónde | Qué hace |
|---|---|---|
| `traccar-backup.sh` | VPS | `pg_dump -Fc` del contenedor (localizado por etiquetas de compose), validación con `pg_restore -l`, rotación (14 días por defecto) |
| `traccar-backup.service` / `.timer` | VPS | systemd: diario a las 03:00 America/La_Paz |
| `traccar-backup-pull.sh` | Vostro | `rsync -a` por SSH con clave dedicada restringida, rotación local (60 días por defecto) |
| `traccar-backup-pull.service` / `.timer` | Vostro | systemd: diario a las 05:00 America/La_Paz |
| `traccar-restore-test.sh` | ambas | Restaura un `.dump` en un postgres temporal y muestra conteos (`tc_devices`, `tc_positions`, `tc_users`) y última posición |

Configuración de cada script va en un EnvironmentFile en `/etc/` (root:root,
600), no en el repo:

- VPS: `/etc/traccar-backup.env` (`NTFY_TOPIC` obligatorio, `RETENTION_DAYS`)
- Vostro: `/etc/traccar-backup-pull.env` (`NTFY_TOPIC` obligatorio,
  `RETENTION_DAYS`, `LOCAL_DIR`)

---

## VPS (Ubuntu 22.04) — instalación

Requisitos: `danfercf` en el grupo `docker` (para `docker ps/exec` sin sudo).

```bash
cd ~/projects/docker-examples/compose/traccar/backup

# 1. Variables de entorno del servicio
sudo install -m 600 -o root -g root traccar-backup.env.example /etc/traccar-backup.env
sudo vim /etc/traccar-backup.env        # NTFY_TOPIC=tu-topic-secreto

# 2. Units de systemd (danfercf debe poder leer y ejecutar el script del repo)
sudo cp -p traccar-backup.service traccar-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now traccar-backup.timer

# 3. Prueba manual y revisión
sudo systemctl start traccar-backup.service
journalctl -u traccar-backup.service -n 50 --no-pager
ls -l /home/danfercf/backups/traccar/

# 4. Confirmar la próxima ejecución programada
systemctl list-timers traccar-backup.timer
```

## Vostro (Debian 13) — instalación

### 1. Clave SSH dedicada y restringida

En el Vostro:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/traccar-backup -C "traccar-backup-vostro" -N ""
cat ~/.ssh/traccar-backup.pub
```

En el VPS, restringir la clave para que **solo pueda leer el directorio de
backups** (sin shell completo). Editar con vim:

```bash
vim ~/.ssh/authorized_keys
```

Añadir la clave pública con `restrict` (implica no-pty, no-port-forwarding,
etc.) y forzando `rrsync` en solo lectura sobre ese directorio:

```
restrict,command="/usr/local/bin/rrsync -ro /home/danfercf/backups/traccar" ssh-ed25519 AAAA... traccar-backup-vostro
```

Localizar `rrsync` en Ubuntu 22.04:

```bash
command -v rrsync            # a veces ya está en el PATH
# si no, viene comprimido dentro del paquete rsync:
sudo zcat /usr/share/doc/rsync/scripts/rrsync.gz | sudo tee /usr/local/bin/rrsync > /dev/null
sudo chmod 755 /usr/local/bin/rrsync
```

Comprobar desde el Vostro que la clave solo lista el directorio permitido:

```bash
rsync -a -e "ssh -i ~/.ssh/traccar-backup" danfercf@danfercf.online:/home/danfercf/backups/traccar/ /tmp/probe/
# debe copiar los volcados; un intento de `ssh ... true` o de leer otra ruta falla
```

### 2. Servicio

```bash
cd ~/projects/docker-examples/compose/traccar/backup

# La unit apunta al repo en /home/daniel/projects/docker-examples. Si en el
# Vostro el repo vive en otra ruta, ajustar ExecStart con vim ANTES de copiar:
vim traccar-backup-pull.service

sudo install -m 600 -o root -g root traccar-backup-pull.env.example /etc/traccar-backup-pull.env
sudo vim /etc/traccar-backup-pull.env   # NTFY_TOPIC=tu-topic-secreto

sudo cp -p traccar-backup-pull.service traccar-backup-pull.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now traccar-backup-pull.timer

# Prueba manual y revisión
sudo systemctl start traccar-backup-pull.service
journalctl -u traccar-backup-pull.service -n 50 --no-pager
ls -l /home/daniel/backups/traccar-vps/
```

> **Nota:** la primera conexión SSH debe aceptar la clave de host. Si el
> timer falla con "Host key verification failed", hacer una vez:
> `ssh-keyscan danfercf.online >> ~/.ssh/known_hosts` (como `daniel`).

## Probar un volcado (restore-test)

En cualquiera de las dos máquinas, con Docker disponible:

```bash
./traccar-restore-test.sh /ruta/al/traccar-AAAA-MM-DD_HHMM.dump
```

Levanta un `postgres:16-alpine` temporal (sin puertos publicados), restaura
con `pg_restore --exit-on-error` y muestra conteos y última posición. El
contenedor se elimina siempre al terminar.

## Restauración real (desastre)

En el VPS, con el stack detenido:

```bash
cd ~/projects/docker-examples/compose/traccar
docker compose stop traccar
docker compose exec traccar-db dropdb -U traccar traccar
docker compose exec traccar-db createdb -U traccar traccar
docker compose exec -T traccar-db pg_restore -U traccar -d traccar --exit-on-error \
    < /home/danfercf/backups/traccar/traccar-AAAA-MM-DD_HHMM.dump
docker compose start traccar
```

Traccar reconstruye su esquema al arrancar si la base está vacía, pero con el
volcado restaurado conserva dispositivos, usuarios e historial.

## Desinstalación

VPS:

```bash
sudo systemctl disable --now traccar-backup.timer
sudo rm /etc/systemd/system/traccar-backup.{service,timer}
sudo systemctl daemon-reload
sudo rm /etc/traccar-backup.env
```

Vostro: igual con `traccar-backup-pull.*` y `/etc/traccar-backup-pull.env`.
Los volcados en `/home/danfercf/backups/traccar/` y
`/home/daniel/backups/traccar-vps/` no se tocan.
