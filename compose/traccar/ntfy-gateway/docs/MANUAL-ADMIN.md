# Manual de administración — gateway ntfy de Traccar

Este gateway recibe eventos de Traccar (`event.forward`) y los reenvía como
avisos push a [ntfy.sh](https://ntfy.sh). Desde esta versión soporta varios
usuarios y varios dispositivos: cada usuario de Traccar recibe avisos solo
de los dispositivos que tiene vinculados directamente, en el tema de ntfy
que configure en su propio perfil.

## 1. Crear la cuenta de servicio

El gateway consulta la API de Traccar para saber qué usuarios tienen acceso
a cada dispositivo. Necesita una cuenta de Traccar dedicada (no uses tu
usuario personal):

1. Panel de Traccar → **Configuración → Usuarios → Añadir**.
2. Nombre, p. ej. `gateway-ntfy`; correo, p. ej. `gateway@tudominio.example`
   (o el que prefieras: será `TRACCAR_SERVICE_USER`); contraseña robusta.
3. Marca **Administrador**. Es imprescindible: solo un administrador puede
   listar todos los usuarios y todos los dispositivos vía API. Marca
   también **Solo lectura** — no es una barrera técnica real (un
   administrador de Traccar puede escribir igual aunque tenga este flag),
   pero deja constancia de la intención y ayuda a detectar por auditoría
   si alguna vez se usa para algo que no sea leer.
4. Guarda el usuario.

**Importante:** el token de esta cuenta equivale en la práctica a un
administrador completo de Traccar (puede leer y escribir todo vía API). La
única garantía real de que el gateway no modifica nada es que su código
nunca emite peticiones POST/PUT/DELETE — no un permiso del lado del
servidor. Trátalo como una credencial sensible: no lo compartas, no lo
subas al repositorio, y si sospechas que se filtró, revócalo de inmediato
(paso 4 más abajo) y genera uno nuevo.

## 2. Generar el token de API (caducidad larga, un año)

Traccar no permite generar un token con caducidad larga desde el panel; se
hace con dos llamadas a la API, iniciando sesión con el usuario de
servicio. Para no dejar la contraseña visible en el historial de la shell
ni en `ps`, pídela de forma interactiva y bórrala de las variables de
entorno al terminar; la cookie de sesión (`cookies.txt`) es también
sensible mientras exista, así que se crea con permisos restrictivos y se
borra al final:

```bash
umask 077                              # cookies.txt nace con permisos 600
read -rs -p "Contraseña de gateway-ntfy: " TRACCAR_PASS; echo

# 1. Inicia sesión (guarda la cookie de sesión en cookies.txt)
curl -c cookies.txt -X POST https://gps.dfcfhub.org/api/session \
  --data-urlencode "email=gateway@tudominio.example" \
  --data-urlencode "password=$TRACCAR_PASS"

unset TRACCAR_PASS

# 2. Genera el token con expiración explícita (ajusta la fecha a ~1 año)
curl -b cookies.txt -X POST https://gps.dfcfhub.org/api/session/token \
  --data-urlencode "expiration=2027-09-29T00:00:00.000+0000"

rm -f cookies.txt
```

La respuesta es el token en texto plano. Traccar no lo vuelve a mostrar:
cópialo de inmediato a `TRACCAR_API_TOKEN` en tu `.env`. Sin `expiration`,
el token caduca a los 7 días (pensado para sesiones normales, no para un
servicio).

### Rotar el token

Repite el paso 2 (genera uno nuevo) y actualiza `TRACCAR_API_TOKEN` en el
`.env` del VPS; reinicia el gateway. El token anterior sigue siendo válido
hasta su expiración salvo que lo revoques explícitamente (misma
precaución con la contraseña y la cookie que en el paso anterior):

```bash
umask 077
read -rs -p "Contraseña de gateway-ntfy: " TRACCAR_PASS; echo
curl -c cookies.txt -X POST https://gps.dfcfhub.org/api/session \
  --data-urlencode "email=gateway@tudominio.example" \
  --data-urlencode "password=$TRACCAR_PASS"
unset TRACCAR_PASS

curl -b cookies.txt -X POST https://gps.dfcfhub.org/api/session/token/revoke \
  --data-urlencode "token=EL_TOKEN_A_REVOCAR"

rm -f cookies.txt
```

Revócalo así inmediatamente si el token se filtra o si la cuenta de
servicio se ve comprometida.

### Si el token caduca o se revoca sin que lo hayas planeado

El gateway sigue funcionando (usa la última caché de destinatarios que
tenga, o el tema de respaldo si nunca llegó a cachear nada) pero deja de
poder actualizar quién recibe qué. Cada fallo de autenticación queda en el
log como `WARNING`, y además se envía un aviso técnico único cada 24 h como
máximo a `NTFY_TOPIC_ADMIN` ("token de la API de Traccar inválido"). Si lo
recibes, regenera el token (pasos de arriba) y reinicia el gateway.

## 3. Configurar el `.env`

Copia `example.env` a `.env` en `compose/traccar/` y completa, además de lo
que ya tenías:

| Variable | Obligatoria | Descripción |
|---|---|---|
| `NTFY_TOPIC_ADMIN` | sí | Tema de **respaldo**: recibe avisos de dispositivos sin ningún usuario con `ntfyTopic`, y los avisos técnicos del propio gateway. Antes se llamaba `NTFY_TOPIC_ALERTS` — ver migración abajo. |
| `TRACCAR_API_TOKEN` | sí | Token de la cuenta de servicio (paso 2). |
| `TRACCAR_SERVICE_USER` | sí | Email o login **exacto** de la cuenta de servicio: se excluye siempre como destinataria de avisos, aunque tenga `ntfyTopic`. |
| `TRACCAR_URL` | no (`http://traccar:8082`) | URL interna de Traccar; no cambiar salvo topología distinta. |
| `TRACCAR_CACHE_SECONDS` | no (300) | Cuánto tiempo se reutiliza el mapa dispositivo→usuarios antes de refrescarlo. |
| `SENT_LOG_DAYS` | no (90) | Retención del historial de envíos (`sent_log`). |
| `LOG_LEVEL` | no (INFO) | `DEBUG` para diagnosticar; nunca registra tokens ni temas de ntfy. |

### Migración desde `NTFY_TOPIC_ALERTS`

Si ya usabas el gateway anterior (todo a un solo tema):

1. **Antes de levantar los contenedores nuevos**, en el `.env` del VPS
   **renombra** la variable `NTFY_TOPIC_ALERTS` a `NTFY_TOPIC_ADMIN` (mismo
   valor, nuevo nombre). El compose ya no reconoce `NTFY_TOPIC_ALERTS`: si
   haces `docker compose up` sin este cambio, falla al arrancar porque
   `NTFY_TOPIC_ADMIN` es obligatoria y no estará definida.
2. Además, configura ese mismo tema como atributo `ntfyTopic` de **tu
   propio usuario** en Traccar (paso 5) si quieres seguir recibiendo tú
   personalmente todo lo que antes recibías.
3. Sin hacer nada más, el comportamiento es idéntico al actual: ningún
   dispositivo tiene `ntfyProfile` ni ningún usuario tiene `ntfyTopic`
   propio, así que todo sigue cayendo en el tema de respaldo.

## 4. Añadir un usuario nuevo y compartirle un dispositivo

1. **Configuración → Usuarios → Añadir**: nombre, correo, contraseña. Deja
   **Administrador** desmarcado (usuario normal).
2. **Configuración → Usuarios**, abre al usuario recién creado, pestaña de
   dispositivos vinculados (o desde **Configuración → Dispositivos**, abre
   el dispositivo y en la pestaña de usuarios vinculados añade a este
   usuario). Debe ser un vínculo **directo** al dispositivo: el gateway
   **no detecta el acceso otorgado solo a través de un grupo** (limitación
   de la API — ver más abajo). Si usas grupos de dispositivos para
   organizar el panel, comparte igualmente cada dispositivo también de
   forma directa con cada usuario que deba recibir avisos de él.
3. Pide al usuario que siga `MANUAL-USUARIO.md` para configurar su propio
   tema de ntfy (`ntfyTopic`), o hazlo tú mismo editando sus atributos
   (paso 5).

### Un administrador que quiere recibir avisos de TODOS los dispositivos

Por defecto, ni siquiera un usuario `administrator=true` recibe avisos de
dispositivos que no tiene vinculados directamente (el atributo
`administrator` ya no da acceso implícito a notificaciones). Para que un
usuario reciba avisos de todos los dispositivos existentes y futuros, añade
en sus atributos:

```
ntfyAllDevices = true   (booleano)
```

## 5. Asignar `ntfyProfile` a un dispositivo

**Configuración → Dispositivos** → abre el dispositivo → **Atributos** →
añade uno nuevo:

```
Clave: ntfyProfile
Valor: vehiculo
```

El perfil debe existir en `config/events.yaml` (sección `profiles`). Un
dispositivo sin este atributo, o con un valor que no corresponde a ningún
perfil definido, usa las reglas por defecto (`events`/`alarms` en el mismo
archivo) — se registra un `WARNING` en el log la primera vez que ocurre por
dispositivo, no en cada evento.

## 6. Crear o editar perfiles y ventanas horarias (YAML)

Archivo: `ntfy-gateway/config/events.yaml`, montado de solo lectura en el
contenedor. Un cambio aquí **requiere reiniciar** el contenedor
(`docker compose restart traccar-ntfy`) para aplicarse — no hay recarga en
caliente.

```yaml
windows:
  noche: {from: "23:00", to: "06:00"}   # HH:MM, America/La_Paz; puede cruzar medianoche

profiles:
  vehiculo:
    geofenceExit:
      enabled: true
      category: info
      during:
        - {window: noche, enabled: true, category: urgent}
```

- `windows`: ventanas con nombre. `from`/`to` en `HH:MM`; si `from > to`
  (p. ej. 23:00 a 06:00), la ventana cruza la medianoche correctamente.
- `profiles.<nombre>.<evento_o_alarma>`: define la regla completa
  (`enabled`, `category`) para esa clave **cuando el dispositivo tenga
  `ntfyProfile: <nombre>`**, reemplazando por completo a la regla por
  defecto de `events`/`alarms`. Las claves NO listadas en el perfil siguen
  usando la regla por defecto sin cambios.
  - `during`: lista de `{window, enabled, category}`. Se evalúa en orden;
    gana la primera ventana que contiene la hora del evento. Si ninguna
    coincide, se usa la regla base (`enabled`/`category` de ese mismo
    bloque, sin `during`).
  - Hora del evento: `event.eventTime`; si falta, `position.fixTime`; si
    también falta, la hora del servidor en ese momento.

Al arrancar, el gateway valida todo el archivo y **se niega a arrancar**
con un mensaje claro si: una ventana referenciada en `during` no existe,
una hora no tiene formato `HH:MM` válido, o una categoría no es `urgent` ni
`info`. Revisa los logs (`docker compose logs traccar-ntfy`) si el
contenedor no levanta tras editar el YAML.

## 7. Qué hace el tema de respaldo (`NTFY_TOPIC_ADMIN`)

Recibe:

- Avisos de un dispositivo que no tiene ningún usuario con `ntfyTopic`
  configurado (con un `WARNING` en el log la primera vez, indicando nombre
  y `uniqueId` del dispositivo).
- Avisos cuando la API de Traccar no responde y nunca hubo una caché
  previa de destinatarios (con `WARNING`). Si sí hubo caché previa
  (aunque esté vencida), se usa esa última caché en vez del respaldo.
- El aviso técnico de token de API inválido (máximo uno cada 24 h).

Nunca se pierde un aviso **urgente** por un fallo de la API: si no se
puede resolver a quién avisar, cae siempre a este tema.

## 8. Leer los logs

```bash
docker compose logs -f traccar-ntfy
```

Con `LOG_LEVEL=INFO` (por defecto) verás, entre otros:

- Al arrancar: perfiles y ventanas cargados, cooldown y `offline_sustained`
  configurados, si la API de Traccar respondió, y cuántos cooldowns/
  temporizadores se restauraron de SQLite.
- Al programar, cancelar o disparar un aviso de `offline_sustained`.
- `WARNING` cuando un dispositivo no tiene destinatarios, cuando la API
  falla, cuando un `ntfyProfile` no existe, o cuando el token de Traccar es
  rechazado.

Ningún log incluye tokens ni temas de ntfy, ni con `LOG_LEVEL=DEBUG`.

## 9. Consultar el historial de envíos (`/history`)

Desde el VPS (el puerto no está publicado, solo accesible dentro de la red
del compose):

```bash
docker compose exec traccar-ntfy \
  python -c "import urllib.request as u; req=u.Request('http://localhost:8080/history?limit=20', headers={'Authorization':'Bearer TU_GATEWAY_TOKEN'}); print(u.urlopen(req).read().decode())"
```

O más simple, con `curl` si el contenedor lo tiene disponible, o desde
otro contenedor en `traccar-network`. Devuelve las últimas entradas
(`timestamp`, dispositivo, tipo de aviso, categoría, destinatario —por
nombre de usuario de Traccar o `admin`—, resultado `ok`/`error`, y
título). Nunca incluye temas de ntfy ni tokens. Usa el mismo
`TRACCAR_NTFY_GATEWAY_TOKEN` que configuraste para `event.forward`.

## 10. Reiniciar el estado (borrar el volumen)

El volumen `traccar-ntfy-state` guarda cooldowns, temporizadores de
`offline_sustained` e historial de envíos. **No forma parte de las copias
de seguridad**: es reconstruible sin pérdida de datos de Traccar (a lo
sumo, se repite algún aviso que estaba en cooldown, o se pierde el
historial de `/history`).

```bash
docker compose stop traccar-ntfy
docker volume rm traccar_traccar-ntfy-state   # el prefijo depende del nombre del proyecto compose
docker compose up -d traccar-ntfy
```

Comprueba el nombre exacto del volumen con `docker volume ls | grep ntfy`
si el prefijo de tu proyecto compose no es `traccar_`.

## 11. Probar sin mover un vehículo

Con el token de `TRACCAR_NTFY_GATEWAY_TOKEN`, simula un evento igual al que
enviaría Traccar:

```bash
curl -X POST http://localhost:8080/event \
  -H "Authorization: Bearer TU_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "event": {"type": "alarm", "eventTime": "2026-09-29T21:00:00.000Z",
              "deviceId": 1, "attributes": {"alarm": "sos"}},
    "position": {"latitude": -17.78, "longitude": -63.18, "speed": 0,
                 "course": 0, "attributes": {}},
    "device": {"id": 1, "name": "Auto de prueba", "uniqueId": "PRUEBA123",
               "attributes": {}}
  }'
```

Si `PRUEBA123` no es un `uniqueId` real, el gateway igual lo procesa: cae
al tema de respaldo (con el `WARNING` correspondiente) salvo que hayas
configurado ese `uniqueId` en algún dispositivo de prueba y le hayas dado
`ntfyProfile`/usuarios con `ntfyTopic`. Ejecutado desde el propio VPS,
`http://localhost:8080` requiere estar dentro de la red del compose (por
ejemplo con `docker compose exec traccar-ntfy sh -c "..."` o publicando el
puerto temporalmente para la prueba).

## Limitación conocida: acceso solo por grupo

El gateway construye el mapa dispositivo→usuarios con
`GET /api/devices?userId=<id>`, que **excluye el acceso otorgado solo a
través de un grupo de dispositivos** (es un comportamiento de la propia
API de Traccar). Si compartes un grupo completo con un usuario en vez de
cada dispositivo por separado, ese usuario no recibirá avisos de esos
dispositivos. Comparte siempre el dispositivo también de forma directa
con cada usuario que deba recibir sus avisos.
