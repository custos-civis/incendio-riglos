# Panel ciudadano del incendio de Las Peñas de Riglos

Primera versión funcional de una web pública estática para reunir información oficial sobre un posible incendio forestal en Las Peñas de Riglos (Huesca). El panel prioriza claridad, trazabilidad, privacidad y seguridad informativa.

> **No es una herramienta oficial de emergencias.** No sustituye los avisos de 112 Aragón, Protección Civil, CECOPI ni de ninguna autoridad. En caso de discrepancia, prevalecen siempre las instrucciones oficiales. Ante una emergencia, llama al 112.

Los datos iniciales están deliberadamente vacíos: la comprobación realizada al crear esta versión no permitió verificar un parte oficial específico del incendio descrito en el encargo. Las cifras del enunciado eran ejemplos, no fuentes, y por tanto no se han publicado como hechos.

## Características

- HTML5, CSS3 y JavaScript vanilla, sin compilación ni backend.
- Datos editables en JSON local.
- Mapa Leaflet con capas activables y GeoJSON local.
- Resumen, evacuaciones, carreteras, meteorología, lluvia útil, evolución y cronología.
- Tres estados de fiabilidad: `oficial`, `provisional` y `sin_actualizacion`.
- Gráfica SVG propia, accesible y sin dependencias adicionales.
- Diseño responsive, navegación por teclado y marcado semántico.
- Sin cookies, formularios, autenticación, analítica, publicidad ni trackers propios.

## Ejecutar localmente

Los navegadores suelen impedir que una página abierta con `file://` lea archivos JSON por seguridad. Sirve la carpeta mediante HTTP local:

```bash
python -m http.server 8000
```

Después abre <http://localhost:8000/>. En Windows también puede usarse `py -m http.server 8000`. Otra opción es la extensión **Live Server** de Visual Studio Code.

No hacen falta `npm install`, Node.js, base de datos ni variables de entorno.

## Estructura

```text
.
├── index.html
├── README.md
├── LICENSE
├── css/
│   └── style.css
├── js/
│   ├── app.js
│   ├── map.js
│   └── charts.js
├── data/
│   ├── estado.json
│   ├── evacuaciones.json
│   ├── carreteras.json
│   ├── meteo.json
│   ├── cronologia.json
│   ├── fuentes.json
│   ├── perimetro.geojson
│   └── espacios-protegidos.geojson
└── assets/
    └── icons/
```

## Editar los JSON

### Reglas generales

1. Haz una revisión humana de la publicación original.
2. Confirma que el emisor es una Administración u organismo oficial.
3. Copia el dato sin redondear, completar ni extrapolar.
4. Registra el enlace directo y la fecha/hora de la publicación.
5. Usa `null` si el valor es desconocido.
6. Valida los JSON antes de publicar.
7. Actualiza `ultima_comprobacion_panel` aunque no haya novedades; cambia `ultima_actualizacion_oficial` solo cuando se incorpore un parte nuevo.

Las fechas deben estar en ISO 8601 con zona horaria, por ejemplo `2026-08-16T10:01:00+02:00`.

### Estado general

Cada dato de `data/estado.json` contiene un valor y metadatos independientes. Así se evita atribuir a una fuente cifras que no publicó:

```json
{
  "superficie_ha": {
    "value": 16600,
    "meta": {
      "fecha_hora": "2026-08-16T10:01:00+02:00",
      "fiabilidad": "oficial",
      "fuente": {
        "nombre": "Gobierno de Aragón",
        "url": "https://enlace-directo-al-parte.example"
      }
    }
  }
}
```

El valor anterior es solo una demostración de esquema: **no debe copiarse al archivo real sin una publicación oficial verificable**. `perimetro_consolidado_pct` debe permanecer en `null` si la fuente no facilita el porcentaje explícitamente.

### Evacuaciones

Añade objetos en `data/evacuaciones.json`:

```json
{
  "poblacion": "Nombre del núcleo",
  "estado": "Evacuada",
  "fecha_hora": "2026-08-16T10:01:00+02:00",
  "coordenadas": [42.0, -0.7],
  "fuente": {
    "nombre": "112 Aragón",
    "url": "https://enlace-directo.example"
  }
}
```

Estados admitidos: `Evacuada`, `Confinada`, `Retorno autorizado` y `Sin actualización`. Las coordenadas son opcionales. No incluyas nombres ni datos personales.

### Carreteras

En `data/carreteras.json`, cada registro admite `carretera`, `tramo`, `estado`, `fecha_hora`, `fuente` y, opcionalmente, `coordenadas`. Verifica el estado en DGT o en la autoridad vial competente antes de publicarlo.

### Meteorología y precipitación útil

`data/meteo.json` separa `prevision` de `observacion`. La estación y la hora pertenecen a `meta`; no mezcles una observación de Jaca con una predicción municipal.

Los registros manuales de `precipitacion_efecto_operativo` usan:

```json
{
  "fecha": "2026-08-16T09:00:00+02:00",
  "estacion": "Nombre oficial de la estación",
  "precipitacion_mm": 0.0,
  "observacion": "Sin lluvia significativa"
}
```

La observación solo puede ser: `Sin lluvia significativa`, `Lluvia local`, `Lluvia potencialmente útil`, `Tormenta con rachas erráticas` o `Pendiente de confirmar`. La aplicación no interpreta automáticamente el efecto de la lluvia.

### Cronología y gráfica

`data/cronologia.json` contiene:

- `eventos`: partes ordenados de más reciente a más antiguo;
- `series`: puntos cronológicos con `fecha`, `superficie_ha`, `perimetro_consolidado_pct` y `precipitacion_mm`.

Usa `null` cuando falte un valor. La gráfica separa los segmentos y no interpola huecos.

## Añadir un perímetro GeoJSON

1. Obtén una geometría publicada por una fuente oficial y comprueba sus condiciones de reutilización.
2. Confirma que el sistema de coordenadas sea WGS84 (`EPSG:4326`) y el orden GeoJSON sea longitud, latitud.
3. Sustituye el contenido de `data/perimetro.geojson` por un `FeatureCollection` válido.
4. Añade a `metadata` la fuente, el enlace, la fecha/hora y un aviso sobre su vigencia.
5. Comprueba visualmente que la geometría cae en la zona correcta.
6. No dibujes a mano un perímetro aproximado ni publiques una geometría operativa filtrada.

La capa del Paisaje Protegido de San Juan de la Peña y Monte Oroel funciona igual en `data/espacios-protegidos.geojson`. Ambas se entregan vacías para evitar representar aproximaciones como cartografía real.

Las capas para focos térmicos, precipitación y perímetros históricos ya aparecen preparadas en `js/map.js`, pero vacías.

## Publicar en GitHub Pages

### Desde la interfaz de GitHub

1. Crea un repositorio público o privado compatible con Pages.
2. Sube el contenido de esta carpeta a la rama principal, dejando `index.html` en la raíz.
3. Abre **Settings → Pages** en el repositorio.
4. En **Build and deployment**, selecciona **Deploy from a branch**.
5. Elige la rama `main` y la carpeta `/(root)`.
6. Pulsa **Save** y espera a que GitHub muestre la URL publicada.
7. Abre la URL, confirma que el mapa carga y revisa la consola del navegador.

### Desde Git

```bash
git add .
git commit -m "Añadir panel ciudadano de Riglos"
git branch -M main
git remote add origin https://github.com/USUARIO/REPOSITORIO.git
git push -u origin main
```

Después activa Pages con los pasos 3–6 anteriores. No hace falta una acción de compilación: el sitio se sirve tal cual.

## Lista de comprobación antes de publicar

- [ ] Todos los datos proceden de enlaces oficiales accesibles.
- [ ] Las fechas distinguen comprobación del panel y publicación oficial.
- [ ] Los campos desconocidos siguen en `null`.
- [ ] No hay información táctica ni datos personales.
- [ ] No hay publicaciones particulares usadas como confirmación.
- [ ] Los JSON son válidos y la consola no muestra errores.
- [ ] Se ha probado escritorio, móvil y navegación por teclado.
- [ ] El perímetro, si existe, tiene fuente, fecha y licencia documentadas.
- [ ] Una segunda persona ha revisado los cambios sensibles.

## Seguridad informativa

Reglas obligatorias para cualquier actualización:

- No publicar información táctica.
- No publicar ubicaciones de bomberos, maquinaria, UME, voluntariado ni otros equipos.
- No publicar rutas de ataque, maniobras o movimientos de extinción.
- No usar información de redes sociales particulares como confirmación.
- Priorizar siempre fuentes oficiales y enlazar la publicación original.
- Mantener revisión humana antes de actualizar datos.
- No inferir perímetros, porcentajes, evacuaciones ni efectos meteorológicos.

## Privacidad

El código no solicita nombre, correo, teléfono, dirección, geolocalización ni identificadores; tampoco crea cookies, formularios, perfiles o analítica. GitHub Pages y los proveedores externos pueden procesar datos técnicos de conexión conforme a sus propias políticas:

- Leaflet se descarga desde `unpkg.com`.
- Las teselas del mapa se solicitan a `tile.openstreetmap.org` y, como en cualquier petición web, el servidor puede recibir la dirección IP.
- GitHub procesa las visitas cuando aloja el sitio.

Para reducir todavía más las conexiones externas, puede descargarse Leaflet al repositorio y sustituirse el mapa base por teselas de un proveedor con condiciones adecuadas. No almacenes teselas masivamente: respeta la [política de uso de teselas de OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/).

## Limitaciones

- Los datos se actualizan manualmente y pueden quedar desfasados.
- El panel no consulta APIs en tiempo real ni envía alertas.
- El mapa es informativo y depende de servicios externos para el fondo cartográfico.
- Una ausencia en el panel significa “no incorporado”, no “inexistente”.
- La disponibilidad de fuentes, enlaces y formatos oficiales puede cambiar.
- No es una herramienta de coordinación, predicción ni toma de decisiones operativas.

## Licencia y contenidos de terceros

El código original de este repositorio se distribuye bajo licencia MIT; consulta `LICENSE`.

La licencia MIT **no** se extiende automáticamente a datos, mapas, geometrías, teselas, logotipos, marcas, publicaciones oficiales ni otros contenidos de terceros. Esos materiales mantienen sus propias licencias y condiciones de reutilización. Leaflet se distribuye bajo licencia BSD-2-Clause y los datos de OpenStreetMap bajo ODbL; revisa siempre las condiciones vigentes de cada proveedor.

