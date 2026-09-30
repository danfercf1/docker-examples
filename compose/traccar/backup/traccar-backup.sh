#!/usr/bin/env bash
# Backup de la base de datos Traccar (VPS).
# Localiza el contenedor por etiquetas de compose, vuelca con pg_dump -Fc,
# valida con pg_restore -l y rota por antigüedad.
#
# Configuración (EnvironmentFile /etc/traccar-backup.env, obligatorio):
#   NTFY_TOPIC     topic de ntfy.sh para avisar SOLO en fallo (obligatorio)
#   RETENTION_DAYS días de retención de volcados (por defecto 14)
set -euo pipefail
umask 077

DEST_DIR="/home/danfercf/backups/traccar"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

notify_fail() {
    local detail="${1:-${BASH_COMMAND:-desconocido}}"
    curl -fsS -H "Title: VPS: backup de Traccar FALLÓ" \
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
    echo "ERROR: NTFY_TOPIC no definido. Crear /etc/traccar-backup.env (ver traccar-backup.env.example)." >&2
    exit 1
fi
[[ "${RETENTION_DAYS}" =~ ^[0-9]+$ ]] || die "RETENTION_DAYS inválido: ${RETENTION_DAYS}"

# --- Localizar el contenedor por etiquetas (no por nombre) ------------------
mapfile -t containers < <(docker ps -q \
    --filter label=com.docker.compose.project=traccar \
    --filter label=com.docker.compose.service=traccar-db)
[[ "${#containers[@]}" -eq 1 ]] \
    || die "se esperaba 1 contenedor traccar-db, se encontraron ${#containers[@]}"
container="${containers[0]}"

# --- Volcado a archivo temporal en el mismo directorio ----------------------
mkdir -p "${DEST_DIR}"
stamp="$(date +%F_%H%M)"
tmp="$(mktemp "${DEST_DIR}/.traccar-${stamp}.XXXXXX")"
final="${DEST_DIR}/traccar-${stamp}.dump"

echo "==> Volcando ${container} a ${final}"
if ! docker exec "${container}" pg_dump -U traccar -d traccar -Fc > "${tmp}"; then
    rm -f "${tmp}"
    die "pg_dump falló"
fi

# --- Validación del volcado --------------------------------------------------
if [[ ! -s "${tmp}" ]]; then
    rm -f "${tmp}"
    die "volcado vacío"
fi
if ! docker exec -i "${container}" pg_restore -l < "${tmp}" >/dev/null 2>&1; then
    rm -f "${tmp}"
    die "pg_restore -l no validó el volcado"
fi

mv "${tmp}" "${final}"
chmod 600 "${final}"
echo "OK: ${final}"

# --- Retención (solo tras un volcado válido) --------------------------------
find "${DEST_DIR}" -maxdepth 1 -name 'traccar-*.dump' \
    -mtime "+${RETENTION_DAYS}" -delete
