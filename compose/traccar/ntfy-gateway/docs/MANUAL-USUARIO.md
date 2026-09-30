# Recibir avisos del vehículo en tu celular

Esta guía es para quien va a recibir los avisos (alarmas, encendido del
motor, salida de una zona, etc.), no para quien administra el sistema. No
necesitas conocimientos técnicos, solo seguir los pasos.

## 1. Instalar la app ntfy y crear tu tema

1. Instala la app **ntfy** desde tu tienda de aplicaciones:
   - Android: buscá "ntfy" en Google Play (o F-Droid).
   - iPhone: buscá "ntfy" en la App Store.
2. Abrí la app. Vas a ver un botón para **suscribirte a un tema**
   (generalmente un botón "+" o "Subscribe to topic").
3. **Importante:** un "tema" (topic) en ntfy.sh es como una dirección
   secreta — cualquiera que conozca el nombre exacto puede leer lo que se
   envía ahí (no requiere contraseña). Por eso:
   - Elegí un nombre **largo y aleatorio**, que nadie pueda adivinar. Por
     ejemplo: `auto-mamá-x7k2p9wq3m` o cualquier combinación larga de
     letras y números que solo vos conozcas. **No uses** algo como
     `mi-auto` o `alarma-carro` — son fáciles de adivinar y cualquiera
     que los escriba en la app podría ver tus avisos.
   - Un generador de contraseñas (o simplemente escribir a lo loco en el
     teclado) sirve perfecto para inventar el nombre.
4. Escribí ese nombre en la app ntfy y confirmá la suscripción. Ya estás
   listo para recibir avisos ahí — todavía falta decirle al sistema cuál
   es tu tema (paso 2).

## 2. Configurar tu tema en el panel de Traccar

1. Entrá al panel web de Traccar con tu usuario y contraseña (la dirección
   te la da quien administra el sistema).
2. Arriba a la derecha, tocá el ícono de tu cuenta (una persona o tus
   iniciales) y elegí **Cuenta** (o el nombre que tenga la opción para
   editar tu propio perfil).
3. Se abre un formulario. Desplazate hacia abajo hasta encontrar la
   sección **Atributos** (puede estar colapsada: tocá para desplegarla).
4. Tocá el botón para **añadir un atributo nuevo** (usualmente un "+").
5. En el primer campo (clave) escribí exactamente:

   ```
   ntfyTopic
   ```

6. En el segundo campo (valor) pegá o escribí el **mismo tema exacto** que
   creaste en el paso 1 (mayúsculas/minúsculas importan: debe ser idéntico).
7. Guardá los cambios (botón de guardar/check, generalmente arriba a la
   derecha del formulario).

Desde ese momento vas a empezar a recibir en tu celular los avisos de los
dispositivos que tengas vinculados. Si no recibís nada después de un rato
razonable, revisá que el tema esté escrito exactamente igual en la app
ntfy y en el atributo `ntfyTopic`, y avisá a quien administra el sistema.

## 3. Opcional: recibir solo lo urgente (`ntfyMinCategory`)

Cada aviso tiene una categoría: **urgente** (alarmas, algo que requiere
atención ya) o **informativo** (encendido de motor, salida de una zona,
etc. — para seguimiento, no requieren acción inmediata).

Si preferís que tu celular solo suene para lo urgente y no te llegue nada
informativo, añadí otro atributo (mismo procedimiento del paso 2):

```
Clave:  ntfyMinCategory
Valor:  urgent
```

Sin este atributo (o con cualquier otro valor), recibís ambas categorías.

## 4. Qué significa cada aviso

| Ícono / prioridad en tu celular | Categoría | Ejemplos | Qué hacer |
|---|---|---|---|
| 🔴 Prioridad alta, con sonido de alarma | **Urgente** | SOS, corte de corriente, vehículo remolcado, vibración/manipulación detectada, batería baja, señal de GPS interferida (jamming), antena GPS cortada, exceso de velocidad configurado como urgente | Revisar de inmediato: puede tratarse de un robo, un desperfecto eléctrico o una situación que requiere tu atención ya |
| 🔵 Prioridad normal | **Informativo** | Encendido/apagado de contacto, entrada/salida de una zona conocida | Informativo: para llevar seguimiento, no requiere una acción inmediata |

Algunos avisos cambian de categoría según la hora (por ejemplo, una salida
de zona de madrugada puede marcarse urgente aunque de día sea solo
informativa) — esto lo configura quien administra el sistema según el
perfil asignado al vehículo.

## 5. Ante un aviso urgente

1. Leé el mensaje completo: indica el vehículo, la hora y, cuando aplica,
   un enlace a un mapa con la última posición conocida.
2. Si es una alarma de pánico (SOS), manipulación, remolque o corte de
   corriente sin explicación: contactá a quien corresponda (dueño del
   vehículo, seguridad, o autoridades si sospechás un robo en curso).
3. Si es "sin reportar" (el dispositivo dejó de enviar posición por un
   rato largo): puede ser un problema de señal, batería del rastreador, o
   algo más serio — si persiste, avisá a quien administra el sistema.

## Si querés dejar de recibir avisos

Simplemente desuscribite del tema en la app ntfy (o borrá el atributo
`ntfyTopic` de tu perfil, o dejalo vacío) y guardá los cambios en tu
cuenta de Traccar.
