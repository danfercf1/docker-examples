#!/usr/bin/env bash
# Copia de seguridad del backup de Traccar desde el VPS al Vostro (rsync por SSH).
# Usa una clave SSH dedicada y restringida (ver README). Sin --delete: el
# Vostro conserva su propia historia aunque el VPS rote volcados.
#
# Tras un pull correcto comprueba la frescura del volcado más reciente y
# envía un latido (status=up) a Uptime Kuma (monitor Push). Los avisos por
# ntfy.sh se envían SOLO en fallo; si el volcado no es fresco no se envía
# latido.
#
# Configuración (EnvironmentFile /etc/traccar-backup-pull.env, obligatorio):
#   NTFY_TOPIC     topic de ntfy.sh para avisar SOLO en fallo (obligatorio)
#   RETENTION_DAYS días de retención local (por defecto 60)
#   LOCAL_DIR      destino local (por defecto /home/daniel/backups/traccar-vps)
#   MAX_AGE_HOURS  antigüedad máxima del volcado más reciente, en horas (por defecto 25)
#   KUMA_PUSH_URL  URL del monitor Push de Uptime Kuma (opcional; vacía = omitir)
#   REMOTE_SRC     origen remoto visto por rrsync (por defecto danfercf@danfercf.online:./)
#   SSH_KEY        clave SSH dedicada (por defecto /home/daniel/.ssh/traccar-backup)
set -euo pipefail
umask 077

LOCAL_DIR="${LOCAL_DIR:-/home/daniel/backups/traccar-vps}"
RETENTION_DAYS="${RETENTION_DAYS:-60}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-25}"
REMOTE_SRC="${REMOTE_SRC:-danfercf@danfercf.online:./}"
SSH_KEY="${SSH_KEY:-/home/daniel/.ssh/traccar-backup}"

# --- Notificación de fallos (único camino: on_exit) --------------------------
FAIL_REASON=""
notify_fail() {
    local detail="${1:-desconocido}"
    [[ -n "${NTFY_TOPIC:-}" ]] || return 0
    curl -fsS -m 10 -H "Title: Vostro: pull de backup de Traccar FALLÓ" \
        -d "Falló: ${detail}" "https://ntfy.sh/${NTFY_TOPIC}" \
        >/dev/null 2>&1 || true
}

die() {
    echo "ERROR: $*" >&2
    FAIL_REASON="$*"
    exit 1
}

# El trap ERR solo REGISTRA el motivo; el aviso sale siempre desde on_exit,
# así todo camino de fallo (die o comando inesperado) avisa exactamente una vez.
trap 'FAIL_REASON="${BASH_COMMAND:-desconocido}"' ERR
on_exit() {
    local rc=$?
    (( rc == 0 )) && return 0
    notify_fail "${FAIL_REASON:-exit ${rc}}"
}
trap on_exit EXIT

# --- Validación de configuración -------------------------------------------
if [[ -z "${NTFY_TOPIC:-}" ]]; then
    echo "ERROR: NTFY_TOPIC no definido. Crear /etc/traccar-backup-pull.env (ver traccar-backup-pull.env.example)." >&2
    exit 1
fi
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS inválido: ${RETENTION_DAYS}"
[[ "${MAX_AGE_HOURS}" =~ ^[0-9]+$ ]] || die "MAX_AGE_HOURS inválido: ${MAX_AGE_HOURS}"
[[ -f "${SSH_KEY}" ]] || die "no existe la clave SSH dedicada: ${SSH_KEY}"

mkdir -p "${LOCAL_DIR}"

# --- Pull por SSH con la clave dedicada --------------------------------------
echo "==> rsync ${REMOTE_SRC} -> ${LOCAL_DIR}/"
rsync -a -e "ssh -i ${SSH_KEY} -o BatchMode=yes" "${REMOTE_SRC}" "${LOCAL_DIR}/"

# --- Retención local propia (independiente de la del VPS) --------------------
find "${LOCAL_DIR}" -maxdepth 1 -name 'traccar-*.dump' \
    -mtime "+${RETENTION_DAYS}" -delete

# --- Comprobación de frescura (siempre activa) -------------------------------
# El mtime del volcado es la hora del volcado en el VPS (rsync -a lo conserva).
latest="$(find "${LOCAL_DIR}" -maxdepth 1 -name 'traccar-*.dump' -printf '%T@ %p\n' \
    | sort -rn | head -n1 | cut -d' ' -f2-)"
[[ -n "${latest}" ]] || die "no hay ningún traccar-*.dump en ${LOCAL_DIR}"

mtime="$(stat -c %Y "${latest}")"
now="$(date +%s)"
age_hours=$(( (now - mtime) / 3600 ))
if (( age_hours > MAX_AGE_HOURS )); then
    die "volcado demasiado viejo: ${latest} tiene ${age_hours} h (máx ${MAX_AGE_HOURS} h)"
fi
echo "OK: volcado fresco: ${latest} (${age_hours} h)"

# --- Latido a Uptime Kuma (opcional; nunca marca el backup como fallido) ------
if [[ -n "${KUMA_PUSH_URL:-}" ]]; then
    msg="$(basename "${latest}")"
    if ! curl -fsS -m 10 -G "${KUMA_PUSH_URL}" \
            --data-urlencode "status=up" \
            --data-urlencode "msg=${msg}" \
            --data-urlencode "ping=" \
            >/dev/null 2>&1; then
        echo "AVISO: no se pudo enviar el latido a Uptime Kuma (curl falló); la copia es válida" >&2
    fi
fi

echo "OK: pull completado en ${LOCAL_DIR}"
