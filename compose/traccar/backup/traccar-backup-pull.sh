#!/usr/bin/env bash
# Copia de seguridad del backup de Traccar desde el VPS al Vostro (rsync por SSH).
# Usa una clave SSH dedicada y restringida (ver README). Sin --delete: el
# Vostro conserva su propia historia aunque el VPS rote volcados.
#
# Configuración (EnvironmentFile /etc/traccar-backup-pull.env, obligatorio):
#   NTFY_TOPIC     topic de ntfy.sh para avisar SOLO en fallo (obligatorio)
#   RETENTION_DAYS días de retención local (por defecto 60)
#   LOCAL_DIR      destino local (por defecto /home/daniel/backups/traccar-vps)
#   REMOTE_SRC     origen remoto visto por rrsync (por defecto danfercf@danfercf.online:./)
#   SSH_KEY        clave SSH dedicada (por defecto /home/daniel/.ssh/traccar-backup)
set -euo pipefail
umask 077

LOCAL_DIR="${LOCAL_DIR:-/home/daniel/backups/traccar-vps}"
RETENTION_DAYS="${RETENTION_DAYS:-60}"
REMOTE_SRC="${REMOTE_SRC:-danfercf@danfercf.online:./}"
SSH_KEY="${SSH_KEY:-/home/daniel/.ssh/traccar-backup}"

notify_fail() {
    local detail="${1:-${BASH_COMMAND:-desconocido}}"
    curl -fsS -H "Title: Vostro: pull de backup de Traccar FALLÓ" \
        -d "Falló: ${detail}" "https://ntfy.sh/${NTFY_TOPIC}" \
        >/dev/null 2>&1 || true
}

die() {
    echo "ERROR: $*" >&2
    notify_fail "$*"
    exit 1
}

trap 'notify_fail' ERR

# --- Validación de configuración -------------------------------------------
if [[ -z "${NTFY_TOPIC:-}" ]]; then
    echo "ERROR: NTFY_TOPIC no definido. Crear /etc/traccar-backup-pull.env (ver traccar-backup-pull.env.example)." >&2
    exit 1
fi
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS inválido: ${RETENTION_DAYS}"
[[ -f "${SSH_KEY}" ]] || die "no existe la clave SSH dedicada: ${SSH_KEY}"

mkdir -p "${LOCAL_DIR}"

# --- Pull por SSH con la clave dedicada --------------------------------------
echo "==> rsync ${REMOTE_SRC} -> ${LOCAL_DIR}/"
rsync -a -e "ssh -i ${SSH_KEY} -o BatchMode=yes" "${REMOTE_SRC}" "${LOCAL_DIR}/"

# --- Retención local propia (independiente de la del VPS) -------------------
find "${LOCAL_DIR}" -maxdepth 1 -name 'traccar-*.dump' \
    -mtime "+${RETENTION_DAYS}" -delete

echo "OK: pull completado en ${LOCAL_DIR}"
