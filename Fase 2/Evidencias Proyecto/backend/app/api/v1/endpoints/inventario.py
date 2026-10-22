from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.inventario_schema import (
    AmbitoInventarioRespuesta,
    GestionCatalogoRespuesta,
    HistorialTransicionCategoriaRespuesta,
    HistorialTransicionProductoRespuesta,
    MovimientoCrear,
    MovimientoInventarioRespuesta,
    ProductoDetalleRespuesta,
    ProductoExistenciaRespuesta,
    StockSedeRespuesta,
)
from app.schemas.producto_schema import (
    CategoriaRespuesta,
    ProductoCrear,
    ProductoRespuesta,
    TransicionCatalogo,
)
from app.services import inventario_service
from app.services import global_service
from app.services.auth_service import IdentidadAutenticada

router = APIRouter(prefix="/inventario", tags=["Inventario y Productos"])


@router.get(
    "/categorias",
    response_model=List[CategoriaRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar categorias de productos",
    description=(
        "Devuelve el catalogo de categorias del ambito del actor. Feature 017 "
        "(D-9/AC-15): el **Superadmin no tiene esta lectura** y recibe **403** "
        "sin datos; Administrador, Bodeguero y Solicitante conservan su permiso."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/inventario/categorias")),
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/categorias")),
    ],
)
def listar_categorias(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/categorias")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_categorias(sesion, identidad),
    )


@router.get(
    "/categorias/{categoria_id}",
    response_model=CategoriaRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Obtener una categoria por id",
    description=(
        "Devuelve la categoria pedida si pertenece al ambito del usuario. Un id "
        "ajeno se oculta con **404**, igual que uno inexistente (Feature 008, D-4). "
        "Feature 017 (D-9/AC-15): el **Superadmin no tiene esta lectura** (**403**)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/inventario/categorias/{categoria_id}"
            )
        )
    ],
)
def obtener_categoria(
    categoria_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "GET", "/api/v1/inventario/categorias/{categoria_id}"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.leer_global_unico(
        db,
        identidad,
        lambda sesion: inventario_service.obtener_categoria(
            sesion, categoria_id, identidad
        ),
        no_encontrado="Categoria no encontrada",
    )


@router.get(
    "/productos",
    response_model=List[ProductoRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar productos del catalogo",
    description=(
        "Devuelve el catalogo de productos del ambito del actor. Feature 017 "
        "(D-9/AC-15): el **Superadmin no tiene esta lectura** y recibe **403** "
        "sin datos; Administrador, Bodeguero y Solicitante conservan su permiso."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/inventario/productos")),
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/productos")),
    ],
)
def listar_productos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/productos")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_productos(sesion, identidad),
    )


@router.get(
    "/productos/{producto_id}",
    response_model=ProductoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Obtener un producto por id",
    description=(
        "Devuelve el producto pedido si pertenece al ambito del usuario. Un id "
        "ajeno se oculta con **404**, igual que uno inexistente (Feature 008, D-4). "
        "Feature 017 (D-9/AC-15): el **Superadmin no tiene esta lectura** (**403**)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/inventario/productos/{producto_id}"
            )
        )
    ],
)
def obtener_producto(
    producto_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "GET", "/api/v1/inventario/productos/{producto_id}"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.leer_global_unico(
        db,
        identidad,
        lambda sesion: inventario_service.obtener_producto(
            sesion, producto_id, identidad
        ),
        no_encontrado="Producto no encontrado",
    )


@router.post(
    "/productos",
    response_model=ProductoRespuesta,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un producto en el catalogo",
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(dependencies.requiere_operacion("POST", "/api/v1/inventario/productos")),
        Depends(dependencies.requiere_capacidad("POST", "/api/v1/inventario/productos")),
    ],
)
def crear_producto(
    datos: ProductoCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/inventario/productos")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.crear_producto(db, datos, identidad)


@router.get(
    "/existencias",
    response_model=List[ProductoExistenciaRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Catalogo de insumos con existencias agrupadas por producto",
    description=(
        "Devuelve **un elemento por producto del catalogo**, con el total de stock "
        "y el desglose por sede. Un producto sin existencias aparece con `sedes` "
        "vacio y `stock_total` en 0, en vez de desaparecer. `solo_criticos` se "
        "evalua sobre el total: un producto con `stock_total <= stock_minimo` "
        "queda marcado como critico. Feature 017 (D-9/AC-15): el **Superadmin no "
        "tiene esta lectura** y recibe **403** sin datos.\n\n"
        "Feature 018 (D-7/AC-1/AC-3/AC-6): `sede_id` es un **filtro de lista** "
        "opcional. Con el presente, `stock_total`, `sedes[]` y `es_critico` "
        "describen solo el saldo de esa sede y los productos sin fila de stock en "
        "ella desaparecen de la respuesta. Un id que no existe en el esquema del "
        "actor -incluido uno de otro tenant- responde **200 con lista vacia**, no "
        "**404**: no se hace un lookup previo de la sede. Esto no altera el 404 de "
        "`GET /inventario/stock?sede_id=...` (Feature 011, AC-3), que consulta un "
        "recurso. Combinado con `departamento_id`: si ambos apuntan a sedes "
        "distintas la respuesta es **200 con lista vacia**; sin ninguno de los dos, "
        "los productos sin saldo siguen visibles en cero. Un `departamento_id` de "
        "otra institucion sigue respondiendo **403** y un rol de sede operativa "
        "sin asignacion, **409**."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/existencias"))
    ],
)
def listar_existencias(
    q: Optional[str] = Query(
        default=None,
        description="Busqueda parcial, sin distincion de mayusculas, sobre nombre y descripcion.",
    ),
    categoria_id: Optional[int] = Query(default=None, description="Filtra por categoria."),
    departamento_id: Optional[int] = Query(
        default=None, description="Acota el stock y las sedes a un departamento."
    ),
    sede_id: Optional[int] = Query(
        default=None,
        description=(
            "Acota el stock, las sedes, el total y la criticidad a una sede. Un id "
            "ausente del ambito del actor devuelve una lista vacia (200)."
        ),
    ),
    solo_criticos: bool = Query(
        default=False, description="Deja solo los productos con stock igual o bajo el minimo."
    ),
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/existencias")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_existencias(
            sesion,
            q=q,
            categoria_id=categoria_id,
            departamento_id=departamento_id,
            sede_id=sede_id,
            solo_criticos=solo_criticos,
            identidad=identidad,
        ),
    )


@router.get(
    "/existencias/{producto_id}",
    response_model=ProductoDetalleRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Detalle de un producto con su existencia por sede",
    description=(
        "Feature 019: lectura **aditiva y de solo lectura** que devuelve un "
        "producto del catalogo junto con su existencia desglosada por sede "
        "(`stock_sede`), acotada al ambito del rol. No sustituye a "
        "`GET /inventario/productos/{producto_id}`, que sigue devolviendo solo el "
        "producto bajo la capacidad `catalogo`.\n\n"
        "**Ambito:** el Administrador recibe todas las filas de su institucion; el "
        "Bodeguero, su sede asignada; el Solicitante, la sede de su departamento. "
        "El cliente no elige ni amplia institucion o sede. Las filas de **sedes "
        "inactivas** se incluyen y suman: no se filtra por `Sede.activo`. "
        "`stock_total` es la suma de las sedes devueltas y `es_critico` se evalua "
        "solo sobre ellas; un producto visible sin filas responde **200** con "
        "`sedes: []` y total cero. `sedes` se ordena por `(sede_nombre, sede_id)` "
        "ascendente.\n\n"
        "**Productos:** el Administrador lee activos e inactivos, incluso con "
        "categoria inactiva; Bodeguero y Solicitante solo producto activo con "
        "categoria activa. Un producto inexistente, ajeno o -en roles operativos- "
        "retirado se oculta con **404** indistinguible.\n\n"
        "**Gating:** solo capacidad institucional `inventario`; si esta apagada "
        "responde **403**, tambien al abrir desde Gestion aunque `catalogo` este "
        "habilitada. El **Superadmin** no tiene esta lectura de negocio y recibe "
        "**403**.\n\n"
        "**Precedencia:** `401` -> `403` por matriz -> `403` por capacidad -> "
        "`403` por institucion no resoluble -> `409` por sede operativa no "
        "resoluble -> `404` por recurso -> `200`. El alcance institucional y la "
        "sede se resuelven antes de buscar el producto: un rol operativo sin sede "
        "resoluble recibe **409** incluso con id inexistente, ajeno o retirado. "
        "Un `producto_id` no entero responde **422** por coercion de tipo; cero y "
        "negativos responden **404** tras la precedencia aplicable."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/inventario/existencias/{producto_id}"
            )
        )
    ],
)
def obtener_existencias_producto(
    producto_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "GET", "/api/v1/inventario/existencias/{producto_id}"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.obtener_detalle_producto(db, producto_id, identidad)


@router.get(
    "/ambito",
    response_model=AmbitoInventarioRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Opciones de sede y departamento para filtrar existencias",
    description=(
        "Feature 018 (D-6/AC-4): lectura **aditiva** y minima que solo abastece "
        "los selectores de la pestana de existencias. Devuelve "
        "`{sedes: [{sede_id, sede_nombre}], departamentos: [{departamento_id, "
        "departamento_nombre, sede_id}]}` con **unicamente** filas vigentes: sedes "
        "activas y departamentos activos con sede asignada. No expone usuarios, "
        "tickets, productos, stock ni agregados, y no sustituye la autorizacion de "
        "`GET /inventario/existencias`.\n\n"
        "El **Administrador** recibe las opciones de su institucion; el "
        "**Bodeguero**, solo su sede asignada y los departamentos de esa sede, sin "
        "selector de sede. Un Bodeguero **sin sede asignada** responde **409** sin "
        "ambito alternativo ni sede por defecto, y si su sede esta desactivada "
        "recibe ambas listas vacias. Solicitante y Superadmin reciben **403** por "
        "matriz; con la capacidad institucional `inventario` apagada, **403** "
        "tambien para los dos roles autorizados. El orden es determinista: sedes "
        "por nombre e id, departamentos por nombre e id."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/ambito"))
    ],
)
def obtener_ambito_inventario(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/ambito")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.obtener_ambito_inventario(db, identidad)


@router.get(
    "/stock",
    response_model=List[StockSedeRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar el saldo vigente por sede",
    description=(
        "Devuelve el stock **por sede** (`stock_sede`, spec D-2): una fila plana "
        "por `(sede, producto)` con su `stock_sede_id`, la sede y el saldo. Es la "
        "fuente unica de saldo operativo y **nunca** lee ni expone las filas "
        "legadas de `inventario` (spec §7). A diferencia de "
        "`GET /inventario/existencias`, que agrupa por producto, aqui cada fila "
        "expone la referencia de escritura `stock_sede_id` que consume "
        "`POST /inventario/movimientos`.\n\n"
        "`sede_id` opcional acota a una sede: un id inexistente o ajeno al "
        "tenant, o distinto de la sede del Bodeguero/Solicitante, se oculta con "
        "**404** (AC-3/AC-7). Sin sede asignada, el rol acotado recibe **409**. "
        "Feature 017 (D-9/AC-15): el **Superadmin no tiene esta lectura** (**403**)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/stock"))
    ],
)
def listar_stock_sede(
    sede_id: Optional[int] = Query(
        default=None, description="Acota el saldo a una sede del tenant."
    ),
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/stock")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_stock_sede(
            sesion, sede_id=sede_id, identidad=identidad
        ),
    )


@router.get(
    "/movimientos",
    response_model=List[MovimientoInventarioRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Historial de movimientos con sus datos asociados",
    description=(
        "Devuelve **todas las filas de auditoria de `movimiento_inventario`**, "
        "enriquecidas con el producto, el departamento y la ubicacion de su "
        "inventario de destino. La respuesta es una lista, incluso vacia, sin "
        "paginacion ni filtros en esta entrega.\n\n"
        "El orden es determinista: `fecha_movimiento` descendente y, ante "
        "empates, `movimiento_id` descendente. El recurso es de solo lectura: no "
        "ofrece modificacion ni borrado, porque el historial es la evidencia "
        "inmutable de la trazabilidad de stock. Feature 017 (D-9/AC-15): el "
        "**Superadmin no tiene esta lectura** y recibe **403** sin datos; "
        "Administrador y Bodeguero conservan su permiso."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_capacidad("GET", "/api/v1/inventario/movimientos"))
    ],
)
def listar_movimientos(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/movimientos")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_movimientos(sesion, identidad),
    )


@router.post(
    "/movimientos",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una entrada o salida de stock",
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
    dependencies=[
        Depends(dependencies.requiere_capacidad("POST", "/api/v1/inventario/movimientos"))
    ],
)
def registrar_movimiento(
    datos: MovimientoCrear,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("POST", "/api/v1/inventario/movimientos")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    inventario = inventario_service.registrar_movimiento(db, datos, identidad)
    return {
        "message": "Movimiento registrado exitosamente",
        "nuevo_stock": inventario.stock_actual,
    }


# ---------------------------------------------------------------------------
# Ciclo de vida del catalogo (Feature 014, plan §2.6)
#
# Las cinco operaciones son aditivas y exclusivas del Administrador
# Institucional (AC-2/AC-12/AC-15) y quedan gated bajo la capacidad `catalogo`.
# El orden de validacion D-9 lo resuelve la cadena de dependencias y el
# servicio: 401 (sesion) -> 403 (matriz) -> 403 (capacidad) -> 404 (existencia y
# pertenencia) -> 200 idempotente -> 422 (motivo) -> 409 (precondicion). El
# endpoint no duplica ninguna de esas comprobaciones.
# ---------------------------------------------------------------------------


@router.patch(
    "/productos/{producto_id}/estado",
    response_model=ProductoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Cambiar la vigencia de un producto",
    description=(
        "Da de baja (`activo: false`) o reactiva (`activo: true`) un producto "
        "existente del tenant (Feature 014, D-4).\n\n"
        "El cuerpo lleva **solo** el estado destino y el `motivo` libre de la "
        "transicion real: ausente, vacio, solo espacios o de mas de 500 "
        "caracteres responde **422**; hasta 500 caracteres se persiste literal en "
        "el historial (AC-7).\n\n"
        "El orden es `404` de existencia/pertenencia -> **200 idempotente** si el "
        "destino ya es el estado vigente (no exige motivo ni evalua "
        "precondiciones, y no escribe historial) -> **422** de motivo -> **409** "
        "de precondicion (D-9/AC-3/AC-8): la baja exige saldo cero en todas las "
        "filas de `stock_sede` (el `inventario` legado no participa) y la "
        "reactivacion exige que su categoria este activa (AC-5/AC-6). Un recurso "
        "ajeno se oculta con **404**, indistinguible de uno inexistente.\n\n"
        "Una transicion efectiva confirma en la misma operacion el estado y "
        "exactamente una fila de `historial_transicion_producto` (AC-7). La baja "
        "nunca borra el producto ni altera stock, movimientos o tickets (AC-1), y "
        "no existe borrado fisico (D-3)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_operacion(
                "PATCH", "/api/v1/inventario/productos/{producto_id}/estado"
            )
        ),
        Depends(
            dependencies.requiere_capacidad(
                "PATCH", "/api/v1/inventario/productos/{producto_id}/estado"
            )
        ),
    ],
)
def transicionar_producto(
    producto_id: int,
    datos: TransicionCatalogo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "PATCH", "/api/v1/inventario/productos/{producto_id}/estado"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.transicionar_producto(
        db, producto_id, datos, identidad
    )


@router.patch(
    "/categorias/{categoria_id}/estado",
    response_model=CategoriaRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Cambiar la vigencia de una categoria",
    description=(
        "Da de baja (`activo: false`) o reactiva (`activo: true`) una categoria "
        "existente del tenant (Feature 014, D-4/D-5).\n\n"
        "Misma precedencia que la transicion de producto (D-9/AC-3): `404` -> "
        "**200 idempotente** -> **422** de motivo -> **409** de precondicion. El "
        "motivo es obligatorio solo en un cambio real y se persiste literal con "
        "hasta 500 caracteres (AC-7); la repeticion idempotente no lo exige ni "
        "agrega historial (AC-8).\n\n"
        "Una categoria con al menos un producto activo responde **409** "
        "(AC-5): primero deben retirarse sus productos. Reactivarla **no** "
        "reactiva sus productos en cascada. Las referencias de los productos "
        "inactivos se conservan (AC-1). Una transicion efectiva confirma estado y "
        "exactamente una fila de `historial_transicion_categoria` en la misma "
        "operacion."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        **dependencies.respuesta_conflicto(),
    },
    dependencies=[
        Depends(
            dependencies.requiere_operacion(
                "PATCH", "/api/v1/inventario/categorias/{categoria_id}/estado"
            )
        ),
        Depends(
            dependencies.requiere_capacidad(
                "PATCH", "/api/v1/inventario/categorias/{categoria_id}/estado"
            )
        ),
    ],
)
def transicionar_categoria(
    categoria_id: int,
    datos: TransicionCatalogo,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "PATCH", "/api/v1/inventario/categorias/{categoria_id}/estado"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.transicionar_categoria(
        db, categoria_id, datos, identidad
    )


@router.get(
    "/productos/{producto_id}/historial",
    response_model=List[HistorialTransicionProductoRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Historial de transiciones de un producto",
    description=(
        "Devuelve las transiciones de vigencia de un producto del tenant, "
        "**mas reciente primero** y con orden determinista (Feature 014, "
        "D-8/AC-12): `fecha_transicion` descendente y, ante empates, "
        "`historial_producto_id` descendente. Cada fila expone recurso, actor, "
        "instante, estado origen/destino y motivo. Un producto sin transiciones "
        "devuelve una lista vacia.\n\n"
        "Es una lectura **inmutable y de solo lectura**: no se publica alta, "
        "edicion ni borrado del historial (AC-12). Solo el Administrador "
        "Institucional la consume; un recurso ajeno o inexistente responde "
        "**404** identico (ocultamiento D-4). Los errores aplicables son "
        "**401/403/404** y el **422** de identificador de ruta invalido; la "
        "operacion no muta estado ni evalua precondiciones, por lo que no "
        "produce un **409** de conflicto (clase documentada por el contrato "
        "uniforme de AC-14)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        status.HTTP_409_CONFLICT: {
            "description": (
                "Clase documentada por el contrato uniforme de AC-14: la lectura "
                "de historial no muta estado ni evalua precondiciones, asi que no "
                "produce un conflicto real."
            )
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Identificador de ruta con forma invalida (no entero)."
        },
    },
    dependencies=[
        Depends(
            dependencies.requiere_operacion(
                "GET", "/api/v1/inventario/productos/{producto_id}/historial"
            )
        ),
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/inventario/productos/{producto_id}/historial"
            )
        ),
    ],
)
def listar_historial_producto(
    producto_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "GET", "/api/v1/inventario/productos/{producto_id}/historial"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.listar_historial_producto(
        db, producto_id, identidad
    )


@router.get(
    "/categorias/{categoria_id}/historial",
    response_model=List[HistorialTransicionCategoriaRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Historial de transiciones de una categoria",
    description=(
        "Tabla hermana del historial de producto: transiciones de vigencia de "
        "una categoria del tenant, **mas reciente primero** y con orden "
        "determinista (Feature 014, D-8/AC-12). Cada fila expone recurso, actor, "
        "instante, estado origen/destino y motivo, y referencia exclusivamente su "
        "categoria. Una categoria sin transiciones devuelve una lista vacia.\n\n"
        "Lectura **inmutable y de solo lectura** (AC-12). Solo el Administrador "
        "Institucional la consume; un recurso ajeno o inexistente responde "
        "**404** identico. Los errores aplicables son **401/403/404** y el "
        "**422** de identificador de ruta invalido; la operacion no muta estado "
        "ni evalua precondiciones, por lo que no produce un **409** de conflicto "
        "(clase documentada por el contrato uniforme de AC-14)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
        status.HTTP_409_CONFLICT: {
            "description": (
                "Clase documentada por el contrato uniforme de AC-14: la lectura "
                "de historial no muta estado ni evalua precondiciones, asi que no "
                "produce un conflicto real."
            )
        },
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Identificador de ruta con forma invalida (no entero)."
        },
    },
    dependencies=[
        Depends(
            dependencies.requiere_operacion(
                "GET", "/api/v1/inventario/categorias/{categoria_id}/historial"
            )
        ),
        Depends(
            dependencies.requiere_capacidad(
                "GET", "/api/v1/inventario/categorias/{categoria_id}/historial"
            )
        ),
    ],
)
def listar_historial_categoria(
    categoria_id: int,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion(
            "GET", "/api/v1/inventario/categorias/{categoria_id}/historial"
        )
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.listar_historial_categoria(
        db, categoria_id, identidad
    )


@router.get(
    "/gestion",
    response_model=GestionCatalogoRespuesta,
    status_code=status.HTTP_200_OK,
    summary="Listado de gestion del catalogo con ambos estados",
    description=(
        "Devuelve `{productos, categorias}` del tenant, **activos e inactivos**, "
        "con el estado vigente en cada recurso (Feature 014, AC-15). Es la unica "
        "lectura con esa propiedad y alimenta exclusivamente la seccion "
        "administrativa de la vista de inventario; los listados operativos "
        "existentes siguen filtrados para todos los roles, incluido el "
        "Administrador.\n\n"
        "Solo el Administrador Institucional la consume: Bodeguero, Solicitante y "
        "Superadmin reciben **403** y el ambito tenant se deriva siempre en "
        "servidor, nunca de una entrada del cliente. Los errores relevantes son "
        "**401** y **403**; el listado no muta estado."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(
            dependencies.requiere_operacion("GET", "/api/v1/inventario/gestion")
        ),
        Depends(
            dependencies.requiere_capacidad("GET", "/api/v1/inventario/gestion")
        ),
    ],
)
def listar_gestion(
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/gestion")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return inventario_service.listar_gestion(db, identidad)
