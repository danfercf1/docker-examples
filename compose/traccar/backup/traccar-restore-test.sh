#!/usr/bin/env bash
# Prueba de restauración de un volcado de Traccar en un postgres:16-alpine
# temporal. Sin puertos publicados; el contenedor se elimina siempre al
# terminar (trap EXIT).
#
# Uso: traccar-restore-test.sh /ruta/al/traccar-AAAA-MM-DD_HHMM.dump
set -euo pipefail

DUMP="${1:?Uso: $0 /ruta/al/archivo.dump}"
[[ -f "${DUMP}" ]] || { echo "ERROR: no existe ${DUMP}" >&2; exit 1; }

name="traccar-restore-$$"
cleanup() {
    docker rm -f "${name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Levantando postgres temporal (${name})"
docker run -d --name "${name}" \
    -e POSTGRES_USER=traccar \
    -e POSTGRES_PASSWORD=traccar \
    -e POSTGRES_DB=traccar \
    postgres:16-alpine >/dev/null

echo "==> Esperando a postgres"
for _ in $(seq 1 60); do
    if docker exec "${name}" pg_isready -U traccar -d traccar >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec "${name}" pg_isready -U traccar -d traccar >/dev/null

echo "==> Restaurando ${DUMP}"
docker exec -i "${name}" pg_restore -U traccar -d traccar --exit-on-error < "${DUMP}"

echo "==> Resumen de la base restaurada"
q() { docker exec "${name}" psql -U traccar -d traccar -At -c "$1" 2>&1 || echo "ERROR"; }
echo "tc_devices:      $(q "SELECT count(*) FROM tc_devices")"
echo "tc_positions:    $(q "SELECT count(*) FROM tc_positions")"
echo "tc_users:        $(q "SELECT count(*) FROM tc_users")"
echo "última posición: $(q "SELECT max(fixTime) FROM tc_positions")"
echo "OK: prueba de restauración válida"
