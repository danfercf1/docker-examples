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
  `RETENTION_DAYS`, `LOCAL_DIR`, `REMOTE_SRC`, `SSH_KEY`)

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

Añadir la clave pública forzando `rrsync` en solo lectura sobre ese
directorio (la ruta remota que ve el cliente es relativa a esa carpeta,
por eso el origen en el script es `danfercf@danfercf.online:./`):

```
command="/usr/bin/rrsync -ro /home/danfercf/backups/traccar",restrict ssh-ed25519 AAAA... traccar-backup-vostro
```

En Ubuntu 22.04 `rrsync` ya está instalado en `/usr/bin/rrsync`
(comprobar con `command -v rrsync`); solo si no existiera, viene comprimido
en `/usr/share/doc/rsync/scripts/rrsync.gz`:

```bash
sudo zcat /usr/share/doc/rsync/scripts/rrsync.gz | sudo tee /usr/local/bin/rrsync > /dev/null
sudo chmod 755 /usr/local/bin/rrsync
```

Antes de que funcione el timer, la **primera conexión debe hacerse a mano**
(para aceptar la huella del VPS en `known_hosts` del usuario `daniel`;
el script usa `BatchMode=yes` y fallaría sin esa huella):

```bash
rsync -a -e "ssh -i ~/.ssh/traccar-backup" danfercf@danfercf.online:./ /tmp/probe/
# debe listar los .dump; un intento de leer otra ruta o de abrir shell falla
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

> **Nota:** el script usa `BatchMode=yes`: si la huella del VPS no está en
> `known_hosts` de `daniel`, la conexión falla en vez de pedir confirmación
> (ver la primera conexión manual más arriba).

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
