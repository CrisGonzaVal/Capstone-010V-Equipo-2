# Modelo 4+1 de Kruchten — CompuStock ERP

Colección de diagramas de arquitectura de CompuStock ERP según el modelo 4+1 de
Kruchten. Cubre las vistas **lógica**, **de procesos**, **de desarrollo** y **física**.
La vista de **casos de uso** queda fuera de esta carpeta: vive en los diagramas de
actores de `docs/diagramas/`.

- **Entrada:** [`00-indice.html`](00-indice.html) — índice navegable de la colección.
- **Entrega:** cada diagrama tiene su HTML autocontenido y su PNG a 2x.
- **Rama:** `ricardo` · octubre 2026.

## Estructura

```text
docs/diagramas/4+1-kruchten/
├── 00-indice.html
├── 01-vista-logica/
│   ├── 01-clases-organizacion-catalogo.html / .png
│   ├── 02-clases-inventario-tickets.html / .png
│   └── 03-secuencia-despacho.html / .png
├── 02-vista-procesos/
│   ├── 01-actividad-ciclo-ticket.html / .png
│   └── 02-actividad-aprovisionamiento.html / .png
├── 03-vista-desarrollo/
│   ├── 01-componentes.html / .png
│   └── 02-paquetes.html / .png
└── 04-vista-fisica/
    └── 01-despliegue.html / .png
```

## Diagramas

| Vista | Diagrama | Tipo | Qué responde |
|---|---|---|---|
| Lógica | Organización y catálogo | Clases UML | Cómo se estructura la institución, sus sedes, usuarios y roles, y el catálogo maestro con historiales inmutables. |
| Lógica | Inventario y tickets | Clases UML | Cómo se relacionan el stock por sede, el inventario legado, los tickets, sus detalles y el historial de transiciones. |
| Lógica | Despacho de ticket | Secuencia UML | Qué ocurre entre Angular, Clerk, FastAPI, `TicketService` y PostgreSQL durante un despacho atómico. |
| Procesos | Ciclo de vida del ticket | Actividad UML | Cómo transita un ticket entre estados, incluidas la anulación, el rechazo y el stock insuficiente. |
| Procesos | Aprovisionamiento SaaS | Actividad UML | Cómo se crea una institución y su esquema tenant con dos commits coordinados e idempotencia. |
| Desarrollo | Componentes e interfaces | Componentes UML | Qué componentes sustituibles existen en frontend, backend, datos y Clerk, y cómo se conectan. |
| Desarrollo | Paquetes y dependencias | Paquetes UML | Cómo se agrupa el repositorio y qué dependencias de compilación y ejecución existen. |
| Física | Despliegue | Despliegue UML | Qué nodos, contenedores, puertos, volúmenes y redes sostienen el entorno local. |

## Fuentes de verdad

- `docs/spec/stack.md` — arquitectura, stack y esquemas.
- `backend/app/models/` y `backend/app/services/` — entidades y reglas de negocio.
- `frontend/src/app/` — features, guards, interceptor y servicios.
- `database/01_esquema.sql` y `database/02_datos_semilla.sql` — 22 tablas de
  `control` y 19 tablas por esquema tenant.
- `docker-compose.yml`, `backend/Dockerfile` y `frontend/Dockerfile` — vista física.

Los diagramas se contrastaron con el código y con las features 013 (despacho
atómico) y 017 (aprovisionamiento institucional). Si el código cambia, primero se
actualiza el HTML y después se reexporta el PNG.

## Regenerar los PNG

El HTML es la fuente: contiene el `<svg>` inline y los tokens visuales. El PNG se
obtiene rasterizando **solo el SVG** a 2x, nunca el wrapper editorial.

Método canónico de la skill `diagram-design` (requiere Playwright):

```powershell
python .agents/skills/diagram-design/scripts/export_png.py `
  docs/diagramas/4+1-kruchten/01-vista-logica/01-clases-organizacion-catalogo.html `
  docs/diagramas/4+1-kruchten/01-vista-logica/01-clases-organizacion-catalogo.png 2
```

En este entorno Playwright no está instalado; los PNG se generaron con Edge
headless a partir de un HTML mínimo que contiene el SVG con `width`/`height`
iguales al `viewBox`:

```powershell
msedge --headless=new --disable-gpu --hide-scrollbars --no-first-run `
  --user-data-dir=<temp>\profile --force-device-scale-factor=2 `
  --window-size=<W>,<H> --virtual-time-budget=8000 `
  --screenshot=<temp>\out.png file:///<temp>/diagram.html
```

`W` y `H` son las dimensiones del `viewBox`; el PNG resultante mide `2W × 2H`.
Usa una ruta temporal **sin espacios** para el HTML y el PNG: Edge headless falla
con `Multiple targets are not supported in headless mode` cuando la ruta contiene
espacios. Después copia el PNG junto a su HTML.

`00-indice.html` es solo navegación y no se exporta.

## Convenciones visuales

- **Papel:** `#f8fafc` · **tinta:** `#1e293b` · **texto secundario:** `#475569` ·
  **acento:** `#2563eb`.
- **Tipografías:** Instrument Serif para títulos, Geist para texto y Geist Mono
  para etiquetas y estereotipos.
- **Idioma:** identificadores y textos en español; estereotipos UML en mayúsculas.
- **Márgenes:** 40 px de zona segura; sin sombras ni gradientes decorativos.
- **PNG:** 2x, fondo `#f8fafc`, sin recortes ni bordes en blanco.
- **Coherencia:** el skin coincide con los diagramas de casos de uso de
  `docs/diagramas/`, para que toda la evidencia se lea como una sola colección.

## Verificación

Los ocho PNG miden exactamente 2× su `viewBox`:

| Diagrama | PNG |
|---|---|
| `01-clases-organizacion-catalogo` | 2880 × 1640 |
| `02-clases-inventario-tickets` | 2880 × 1960 |
| `03-secuencia-despacho` | 2880 × 1920 |
| `01-actividad-ciclo-ticket` | 2880 × 2520 |
| `02-actividad-aprovisionamiento` | 2880 × 2400 |
| `01-componentes` | 2880 × 1760 |
| `02-paquetes` | 2880 × 1960 |
| `01-despliegue` | 2880 × 1880 |

Cada HTML conserva su `<title>` y `<desc>` para accesibilidad. Los diagramas se
revisaron a 1:1 para descartar cruces de etiquetas, líneas huérfanas y solapes
entre cajas.
