from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import Integer, String, and_, cast, null, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.core import permisos
from app.models import (
    Categoria,
    Departamento,
    HistorialTransicionCategoria,
    HistorialTransicionProducto,
    Inventario,
    MovimientoInventario,
    Producto,
    Sede,
    StockSede,
    Usuario,
)
from app.schemas.inventario_schema import (
    AmbitoInventarioRespuesta,
    DepartamentoFiltroRespuesta,
    GestionCatalogoRespuesta,
    HistorialTransicionCategoriaRespuesta,
    HistorialTransicionProductoRespuesta,
    MovimientoCrear,
    MovimientoInventarioRespuesta,
    ProductoDetalleRespuesta,
    ProductoExistenciaRespuesta,
    SedeExistenciaRespuesta,
    SedeFiltroRespuesta,
    StockSedeRespuesta,
)
from app.schemas.producto_schema import (
    CategoriaGestionRespuesta,
    ProductoCrear,
    ProductoGestionRespuesta,
    TransicionCatalogo,
)
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA = "SALIDA"

#: Longitud maxima del motivo libre de una transicion del catalogo (spec D-8).
LONGITUD_MAXIMA_MOTIVO = 500

_DETALLE_PRODUCTO_NO_ENCONTRADO = "Producto no encontrado"
_DETALLE_CATEGORIA_NO_ENCONTRADA = "Categoria no encontrada"

_ADMINISTRADOR = permisos.RolConocido.ADMINISTRADOR.value
_SOLICITANTE = permisos.RolConocido.SOLICITANTE.value
_BODEGUERO = permisos.RolConocido.BODEGUERO.value


def es_stock_critico(stock_actual: int, stock_minimo: int) -> bool:
    """Regla unica de stock critico (`spec.md` D-5).

    La usan tanto el armado de la respuesta como el filtro `solo_criticos`, para
    que el estado que ve el usuario y el filtro que produjo su lista no puedan
    discrepar. El `<=` es deliberado: con `stock_minimo = 0` (default del modelo)
    un producto en cero queda marcado como critico, que es lo correcto.
    """
    return stock_actual <= stock_minimo


def listar_categorias(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Categoria]:
    """Categorias del catalogo acotadas a la institucion (008 D-1/AC-5).

    El catalogo deja de ser global: un rol limitado solo ve las categorias de su
    institucion; Superadmin (alcance global) las ve todas con su `institucion_id`.

    Feature 014 (AC-4): esta lectura es **operativa** y excluye las categorias
    retiradas para todos los roles, incluido el Administrador. El listado
    administrativo con ambos estados es `listar_gestion` (AC-15).
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Categoria).filter(Categoria.activo.is_(True))
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Categoria.institucion_id, institucion_id
    )
    return consulta.order_by(Categoria.nombre_cat).all()


def listar_productos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[Producto]:
    """Productos del catalogo acotados a la institucion (008 D-1/AC-5).

    `selectinload` evita el N+1: sin el, cada producto dispara su propia consulta
    a `categoria` al serializar la respuesta.

    Feature 014 (AC-4): lectura **operativa**, filtrada por el predicado conjunto
    `producto.activo AND categoria.activo` para todos los roles. Un producto
    cuya categoria fue retirada tampoco se ofrece.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = (
        db.query(Producto)
        .options(selectinload(Producto.categoria))
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .filter(Producto.activo.is_(True), Categoria.activo.is_(True))
    )
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Producto.institucion_id, institucion_id
    )
    return consulta.order_by(Producto.nombre, Producto.producto_id).all()


def obtener_categoria(
    db: Session, categoria_id: int, identidad: IdentidadAutenticada | None = None
) -> Categoria:
    """Categoria por id con ocultacion 404 de una categoria ajena (008 D-4/AC-9).

    Un id ajeno es indistinguible de uno inexistente: ambos responden 404.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    categoria = db.get(Categoria, categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="Categoria no encontrada")
    ambito_service.exigir_pertenencia(
        ambito_service.institucion_de_recurso(categoria),
        institucion_id,
        detalle="Categoria no encontrada",
    )
    return categoria


def obtener_producto(
    db: Session, producto_id: int, identidad: IdentidadAutenticada | None = None
) -> Producto:
    """Producto por id con ocultacion 404 de un producto ajeno (008 D-4/AC-9)."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    producto = (
        db.query(Producto)
        .options(selectinload(Producto.categoria))
        .filter(Producto.producto_id == producto_id)
        .first()
    )
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    ambito_service.exigir_pertenencia(
        ambito_service.institucion_de_recurso(producto),
        institucion_id,
        detalle="Producto no encontrado",
    )
    return producto


def crear_producto(
    db: Session,
    datos: ProductoCrear,
    identidad: IdentidadAutenticada | None = None,
) -> Producto:
    """Alta de producto anclada a la institucion del usuario (008 D-1/AC-2/AC-10).

    El producto pertenece a la institucion del creador y su categoria debe ser de
    esa misma institucion: una categoria ajena se oculta con **404** (D-4/AC-9),
    sin dejar fila. Sin institucion resoluble, el rol limitado responde 403
    (`alcance_institucional`); Superadmin no escribe catalogo (matriz 008).

    Feature 014 (AC-13): el alta solo procede en una **categoria activa**; una
    categoria retirada responde **409** sin escritura. El bloqueo de la categoria
    se toma antes de insertar el producto para serializar el alta frente a la
    baja concurrente de esa categoria (AC-16, orden categoria -> producto ->
    stock). El producto creado nace `activo`.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    categoria = (
        db.query(Categoria)
        .filter(Categoria.categoria_id == datos.categoria_id)
        .with_for_update()
        .first()
    )
    if categoria is None:
        raise HTTPException(status_code=404, detail="No existe la categoria indicada")
    # Una categoria de otra institucion no habilita el alta (AC-9/AC-10).
    ambito_service.exigir_pertenencia(
        ambito_service.institucion_de_recurso(categoria),
        institucion_id,
        detalle="No existe la categoria indicada",
    )
    if not categoria.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede crear un producto en una categoria inactiva",
        )

    # La institucion del producto es la del usuario; solo si el ambito fuera
    # global (Superadmin, que la matriz 008 no autoriza a escribir) cae a la de
    # la categoria, para no romper la FK compuesta.
    institucion_producto = (
        institucion_id if institucion_id is not None else categoria.institucion_id
    )
    nuevo_producto = Producto(
        **datos.model_dump(), institucion_id=institucion_producto, activo=True
    )
    db.add(nuevo_producto)
    db.commit()
    db.refresh(nuevo_producto)
    return nuevo_producto


def listar_stock_sede(
    db: Session,
    sede_id: Optional[int] = None,
    identidad: IdentidadAutenticada | None = None,
) -> List[StockSedeRespuesta]:
    """Serie plana del saldo vigente por sede (`stock_sede`).

    Feature 011 (spec D-2/§7, AC-2/AC-3/AC-7): el read model lee **exclusivamente**
    `StockSede`, nunca las filas legadas de `inventario` como saldo. Expone la
    referencia de escritura (`stock_sede_id`) y la sede resuelta, que
    `/inventario/existencias` no entrega.

    Ambito:

    * Se acota a la institucion del actor (lectura global solo para Superadmin).
    * `Solicitante`/`Bodeguero` se recortan a su sede (`sede_del_alcance_por_rol`);
      sin sede asignada, **409** (AC-6/AC-7).
    * Un `sede_id` explicito inexistente, ajeno o distinto de la sede del rol se
      oculta con **404** (AC-3/AC-7), sin revelar su existencia.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    sede_rol = sede_del_alcance_por_rol(db, identidad)

    if sede_id is not None:
        sede = db.get(Sede, sede_id)
        if sede is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada"
            )
        ambito_service.exigir_pertenencia(
            sede.institucion_id, institucion_id, detalle="Sede no encontrada"
        )
        # AC-7: un Bodeguero/Solicitante solo consulta su propia sede.
        if sede_rol is not None and sede_rol != sede_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Sede no encontrada"
            )

    consulta = select(
        StockSede.stock_sede_id,
        StockSede.sede_id,
        Sede.nombre.label("sede_nombre"),
        StockSede.producto_id,
        StockSede.stock_actual,
        StockSede.institucion_id,
    ).join(Sede, StockSede.sede_id == Sede.sede_id)
    consulta = consulta.join(
        Producto, StockSede.producto_id == Producto.producto_id
    ).join(Categoria, Producto.categoria_id == Categoria.categoria_id)
    # Feature 014 (AC-4): serie operativa; no expone productos retirados ni
    # productos de una categoria retirada (predicado conjunto, mismo que las
    # existencias y los catalogos).
    consulta = consulta.where(
        Producto.activo.is_(True), Categoria.activo.is_(True)
    )
    if institucion_id is not None:
        consulta = consulta.where(StockSede.institucion_id == institucion_id)
    if sede_rol is not None:
        consulta = consulta.where(StockSede.sede_id == sede_rol)
    if sede_id is not None:
        consulta = consulta.where(StockSede.sede_id == sede_id)
    consulta = consulta.order_by(StockSede.stock_sede_id)

    return [
        StockSedeRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


def sede_del_alcance_por_rol(
    db: Session, identidad: IdentidadAutenticada | None
) -> int | None:
    """Sede a la que se acota la consulta de existencias, o `None` sin recorte.

    Ambito operativo de la Feature 011 (spec D-5, AC-6/AC-7/AC-8):

    * **Solicitante**: la sede de su departamento (`departamento.sede_id`). Sin
      sede asignada la consulta se deniega con **409** y sin fallback.
    * **Bodeguero**: su `usuario.sede_id`; sin sede, **409**.
    * **Administrador**: `None`: ve todas las sedes de su institucion (el recorte
      institucional lo hace `alcance_institucional`).
    * **Superadmin**: `None`: conserva la lectura global atribuida.
    """
    rol = permisos.nombre_rol_de(identidad)
    usuario = getattr(identidad, "usuario", None)
    if rol == _SOLICITANTE:
        departamento = (
            db.get(Departamento, usuario.departamento_id) if usuario is not None else None
        )
        if departamento is None or departamento.sede_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El departamento del solicitante no tiene una sede asignada",
            )
        return departamento.sede_id
    if rol == _BODEGUERO:
        sede_id = getattr(usuario, "sede_id", None)
        if sede_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El bodeguero no tiene una sede asignada",
            )
        return sede_id
    return None


def obtener_ambito_inventario(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> AmbitoInventarioRespuesta:
    """Opciones minimas de sede y departamento para filtrar existencias (018).

    Feature 018 (spec D-6/AC-4, plan §1.2 y §1.3): lectura **aditiva** que solo
    abastece los selectores de la pestana de existencias. No sustituye la
    autorizacion de `GET /inventario/existencias` y no expone usuarios, tickets,
    productos, stock ni agregados.

    Ambito:

    * **Administrador**: las sedes activas de su institucion y los departamentos
      activos asociados a una sede activa de esa institucion.
    * **Bodeguero**: solo su sede asignada, y solo si sigue activa, con sus
      departamentos activos. Sin sede asignada responde **409** por
      `sede_del_alcance_por_rol`, sin fallback ni ambito sustituto. Si su sede
      esta desactivada, ambas listas salen vacias: nunca se ofrece otra sede.
    * Cualquier otro rol queda fuera antes de esta llamada (matriz 018).

    Las opciones son solo filas **vigentes** (spec D-5): una sede inactiva no es
    opcion y un departamento sin sede no se puede resolver a una ubicacion
    fisica, por lo que tampoco aparece. El orden es determinista: sedes por
    `(nombre, sede_id)` y departamentos por `(nombre_dep, departamento_id)`.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    sede_rol = sede_del_alcance_por_rol(db, identidad)

    consulta_sedes = select(
        Sede.sede_id, Sede.nombre.label("sede_nombre")
    ).where(Sede.activo.is_(True))
    consulta_sedes = ambito_service.filtrar_por_institucion(
        consulta_sedes, Sede.institucion_id, institucion_id
    )
    if sede_rol is not None:
        consulta_sedes = consulta_sedes.where(Sede.sede_id == sede_rol)
    consulta_sedes = consulta_sedes.order_by(Sede.nombre, Sede.sede_id)

    sedes = [
        SedeFiltroRespuesta(**fila)
        for fila in db.execute(consulta_sedes).mappings()
    ]

    # El join a `sede` no es decorativo: acota los departamentos a sedes de la
    # institucion del actor y descarta los de una sede desactivada, que tampoco
    # se ofrece como opcion (D-5).
    consulta_departamentos = (
        select(
            Departamento.departamento_id,
            Departamento.nombre_dep.label("departamento_nombre"),
            Departamento.sede_id,
        )
        .join(Sede, Departamento.sede_id == Sede.sede_id)
        .where(Departamento.activo.is_(True), Sede.activo.is_(True))
    )
    if institucion_id is not None:
        consulta_departamentos = consulta_departamentos.where(
            Sede.institucion_id == institucion_id
        )
    if sede_rol is not None:
        consulta_departamentos = consulta_departamentos.where(
            Departamento.sede_id == sede_rol
        )
    consulta_departamentos = consulta_departamentos.order_by(
        Departamento.nombre_dep, Departamento.departamento_id
    )

    departamentos = [
        DepartamentoFiltroRespuesta(**fila)
        for fila in db.execute(consulta_departamentos).mappings()
    ]

    return AmbitoInventarioRespuesta(sedes=sedes, departamentos=departamentos)


def _es_producto_critico(
    sedes: List[SedeExistenciaRespuesta], stock_minimo: int
) -> bool:
    """Criticidad por saldo de sede (spec D-6, AC-11).

    Un producto queda marcado como critico si **alguna** de sus sedes esta en o
    bajo el minimo: la alerta identifica la bodega fisica que puede abastecer, no
    un promedio institucional. Un producto sin ninguna sede sigue marcado critico
    cuando su `stock_minimo` es positivo (`0 <= stock_minimo`): conserva la
    semantica de "sin existencia" del catalogo (Feature 002, D-5).
    """
    if not sedes:
        return es_stock_critico(0, stock_minimo)
    return any(es_stock_critico(sede.stock_actual, stock_minimo) for sede in sedes)


def listar_existencias(
    db: Session,
    q: Optional[str] = None,
    categoria_id: Optional[int] = None,
    departamento_id: Optional[int] = None,
    sede_id: Optional[int] = None,
    solo_criticos: bool = False,
    identidad: IdentidadAutenticada | None = None,
) -> List[ProductoExistenciaRespuesta]:
    """Un elemento por producto del catalogo, con su stock **por sede** (Feature 011).

    La fuente unica de saldo vigente es `StockSede` (spec D-2): nunca se leen las
    filas legadas de `inventario`. La respuesta expone obligatoriamente la sede y
    el saldo (`SedeExistenciaRespuesta`) y el `stock_total` es la suma de las
    sedes del ambito, no un saldo departamental paralelo.

    Es la unica lectura que cruza varias tablas, asi que -a diferencia del resto
    del servicio- usa `select()` de SQLAlchemy 2.0 con los onclause explicitos
    (`plan.md` §3.2.2). `categoria` entra con join interno porque
    `producto.categoria_id` es NOT NULL con FK; `stock_sede` y `sede` entran con
    `outerjoin` para que un producto sin existencias no desaparezca del catalogo.

    Ambito (D-1/D-4/AC-5/AC-6/AC-7/AC-8): el catalogo es institucional y el
    `outerjoin` de stock solo acepta las existencias del ambito. Ademas,
    `sede_del_alcance_por_rol` recorta la lectura a la sede del Solicitante o del
    Bodeguero; el Administrador ve todas las de su institucion y Superadmin, la
    lectura global atribuida por `institucion_id`. Un `departamento_id` explicito
    de otra institucion responde 403; un departamento sin sede no expone existencias.

    Feature 018 (spec D-7/AC-1/AC-3/AC-6): `sede_id` es un **filtro de lista**,
    no un recurso. Se incorpora a `condicion_stock` antes del `outerjoin`, de modo
    que el saldo que se agrega es el de esa sede, y con cualquier filtro
    organizacional (`sede_id` o `departamento_id`) se exige una fila de stock
    real, degradando el `outerjoin` a INNER. Por eso nunca se hace un lookup
    previo de la sede: un id inexistente o de otro tenant responde **200 con
    lista vacia**, igual que una sede distinta de la del rol operativo.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    sede_rol = sede_del_alcance_por_rol(db, identidad)

    sede_de_departamento: int | None = None
    if departamento_id is not None:
        ambito_service.validar_departamento_en_alcance(
            db, departamento_id, institucion_id
        )
        departamento = db.get(Departamento, departamento_id)
        sede_de_departamento = None if departamento is None else departamento.sede_id
        if sede_de_departamento is None:
            # Un departamento sin sede no tiene bodega que exponer (AC-6).
            return []

    condicion_stock = Producto.producto_id == StockSede.producto_id
    if institucion_id is not None:
        condicion_stock = and_(
            condicion_stock, StockSede.institucion_id == institucion_id
        )
    if sede_rol is not None:
        condicion_stock = and_(condicion_stock, StockSede.sede_id == sede_rol)
    if sede_id is not None:
        # Feature 018 (AC-1/AC-3): la sede pedida restringe el join de stock. Un
        # id ausente del esquema del actor no encuentra fila y la lista sale
        # vacia; no se distingue de uno inexistente (nunca hay lookup previo).
        condicion_stock = and_(condicion_stock, StockSede.sede_id == sede_id)
    if sede_de_departamento is not None:
        condicion_stock = and_(
            condicion_stock, StockSede.sede_id == sede_de_departamento
        )

    consulta = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.descripcion,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.institucion_id,
            Categoria.categoria_id,
            Categoria.nombre_cat,
            StockSede.stock_actual,
            Sede.sede_id.label("sede_id"),
            Sede.nombre.label("sede_nombre"),
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(StockSede, condicion_stock)
        .outerjoin(Sede, StockSede.sede_id == Sede.sede_id)
    )

    if institucion_id is not None:
        # El catalogo ya es institucional (D-1/AC-5): un rol limitado solo ve los
        # productos de su institucion, no uno ajeno con `sedes` vacio.
        consulta = consulta.where(Producto.institucion_id == institucion_id)

    # Feature 014 (AC-4): disponibilidad operativa = producto activo **y**
    # categoria activa, para todos los roles. Es el mismo predicado de
    # `listar_productos`, `listar_stock_sede` y los catalogos de ticket.
    consulta = consulta.where(
        Producto.activo.is_(True), Categoria.activo.is_(True)
    )

    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(
            Producto.nombre.ilike(patron) | Producto.descripcion.ilike(patron)
        )
    if categoria_id is not None:
        consulta = consulta.where(Categoria.categoria_id == categoria_id)
    if departamento_id is not None or sede_id is not None:
        # Degrada el `outerjoin` a INNER: solo interesan los productos con
        # existencias en la sede pedida o en la del departamento pedido
        # (Feature 018, AC-6).
        consulta = consulta.where(StockSede.stock_sede_id.is_not(None))

    consulta = consulta.order_by(
        Producto.nombre,
        Producto.producto_id,
        Sede.nombre,
        Sede.sede_id,
    )

    # Acumulador por producto. Las claves coinciden con los campos del schema
    # salvo `es_critico`, que se calcula al final, asi que el DTO se arma con
    # `**acumulador` sin ir completando un BaseModel mutable.
    acumuladores: dict[int, dict] = {}

    for fila in db.execute(consulta).all():
        if fila.producto_id not in acumuladores:
            acumuladores[fila.producto_id] = {
                "producto_id": fila.producto_id,
                "nombre": fila.nombre,
                "descripcion": fila.descripcion,
                "unidad_medida": fila.unidad_medida,
                "stock_minimo": fila.stock_minimo,
                "categoria_id": fila.categoria_id,
                "categoria_nombre": fila.nombre_cat,
                "stock_total": 0,
                "institucion_id": fila.institucion_id,
                "sedes": [],
            }
        acumulador = acumuladores[fila.producto_id]

        # `sede_id` llega en None cuando el producto no tiene existencias.
        if fila.sede_id is not None:
            acumulador["stock_total"] += fila.stock_actual
            acumulador["sedes"].append(
                SedeExistenciaRespuesta(
                    sede_id=fila.sede_id,
                    sede_nombre=fila.sede_nombre,
                    stock_actual=fila.stock_actual,
                )
            )

    # `dict` conserva el orden de insercion, asi que el `ORDER BY` se propaga
    # solo y no hay que reordenar.
    existencias = [
        ProductoExistenciaRespuesta(
            **acumulador,
            es_critico=_es_producto_critico(
                acumulador["sedes"], acumulador["stock_minimo"]
            ),
        )
        for acumulador in acumuladores.values()
    ]

    # `solo_criticos` no cabe en el `WHERE`: es un predicado sobre la criticidad,
    # que no existe hasta agrupar. La base ya filtro por texto, categoria y sede.
    if solo_criticos:
        existencias = [existencia for existencia in existencias if existencia.es_critico]

    return existencias


def obtener_detalle_producto(
    db: Session,
    producto_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> ProductoDetalleRespuesta:
    """Detalle de un producto con su existencia por sede (Feature 019, §8).

    Lectura **dedicada y de solo lectura** que reúne el catálogo operativo del
    producto y su saldo desglosado por sede, acotada al ámbito del rol. Coexiste
    sin reemplazar a `obtener_producto` (`GET /inventario/productos/{producto_id}`,
    capacidad `catalogo` y solo producto).

    Precedencia de la parte de negocio (spec §6 regla 1; el 401/403 de
    autenticación, matriz y capacidad los resuelve el endpoint):

    1. institución no resoluble -> **403** (`alcance_institucional`);
    2. sede operativa no resoluble -> **409** (`sede_del_alcance_por_rol`), **antes**
       de mirar el producto: así un id inexistente, ajeno o retirado tampoco
       revela nada al rol operativo sin sede;
    3. producto inexistente, ajeno o -para rol operativo- retirado -> **404**
       idéntico (`_DETALLE_PRODUCTO_NO_ENCONTRADO`);
    4. **200** con el detalle (aunque no haya filas de stock en el ámbito).

    Ámbito y visibilidad (spec D-3/D-4/D-5/D-7):

    * **Administrador**: todas las filas `stock_sede` de su institución y lectura
      de productos y categorías **inactivos**.
    * **Bodeguero / Solicitante**: solo su sede asignada y solo producto activo
      con categoría activa; cualquier otra combinación es el mismo 404.
    * Las filas de sedes **inactivas** no se excluyen: no hay predicado sobre
      `Sede.activo`, y una sede asignada inactiva sigue siendo resoluble (D-3).
    * `stock_sede` es la única fuente de saldo: no se leen ni suman las filas
      legadas de `inventario` (D-5).
    * El total y la criticidad se derivan **solo** de las sedes devueltas: con
      `sedes` vacío, `_es_producto_critico` evalúa saldo cero frente al mínimo.

    Cruza producto, categoría y stock, así que -igual que `listar_existencias`-
    usa `select()` de columnas con joins explícitos y ejecuta con `.mappings()`.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    # Regla 1: la sede se resuelve antes que el recurso (409 precede al 404).
    sede_rol = sede_del_alcance_por_rol(db, identidad)
    es_administrador = permisos.nombre_rol_de(identidad) == _ADMINISTRADOR

    consulta = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.descripcion,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.categoria_id,
            Categoria.nombre_cat.label("categoria_nombre"),
            Categoria.activo.label("categoria_activa"),
            Producto.activo,
            Producto.institucion_id,
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .where(Producto.producto_id == producto_id)
    )
    # El filtro institucional deja el producto ajeno fuera del resultado, de modo
    # que comparte el 404 de uno inexistente (spec D-4).
    consulta = ambito_service.filtrar_por_institucion(
        consulta, Producto.institucion_id, institucion_id
    )
    producto = db.execute(consulta).mappings().first()
    if producto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_DETALLE_PRODUCTO_NO_ENCONTRADO,
        )
    if not es_administrador and not (
        producto["activo"] and producto["categoria_activa"]
    ):
        # Un retirado es indistinguible de un inexistente para el rol operativo.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_DETALLE_PRODUCTO_NO_ENCONTRADO,
        )

    # Sin `Sede.activo`: las sedes inactivas forman parte del desglose (D-3/D-5).
    consulta_stock = (
        select(
            Sede.sede_id,
            Sede.nombre.label("sede_nombre"),
            StockSede.stock_actual,
        )
        .join(StockSede, StockSede.sede_id == Sede.sede_id)
        .where(StockSede.producto_id == producto_id)
    )
    consulta_stock = ambito_service.filtrar_por_institucion(
        consulta_stock, StockSede.institucion_id, institucion_id
    )
    if sede_rol is not None:
        consulta_stock = consulta_stock.where(StockSede.sede_id == sede_rol)
    # Orden determinista del contrato §8: (sede_nombre, sede_id).
    consulta_stock = consulta_stock.order_by(Sede.nombre, Sede.sede_id)

    sedes = [
        SedeExistenciaRespuesta(**fila)
        for fila in db.execute(consulta_stock).mappings()
    ]

    return ProductoDetalleRespuesta(
        **dict(producto),
        stock_total=sum(sede.stock_actual for sede in sedes),
        es_critico=_es_producto_critico(sedes, producto["stock_minimo"]),
        sedes=sedes,
    )


def _historial_legados():
    """Select del historial de movimientos historicos (por `inventario_id`).

    Proyeccion compatible con `_historial_nuevos`: atribuye producto,
    departamento y ubicacion desde el inventario legado y deja la sede en `null`.
    """
    return (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            MovimientoInventario.observacion,
            MovimientoInventario.inventario_id,
            cast(null(), Integer).label("stock_sede_id"),
            Inventario.producto_id,
            Producto.nombre.label("producto_nombre"),
            Inventario.departamento_id,
            Departamento.nombre_dep.label("departamento_nombre"),
            cast(null(), Integer).label("sede_id"),
            cast(null(), String(100)).label("sede_nombre"),
            Inventario.ubicacion,
            Departamento.institucion_id,
        )
        .join(
            Inventario,
            MovimientoInventario.inventario_id == Inventario.inventario_id,
        )
        .join(Producto, Inventario.producto_id == Producto.producto_id)
        .join(
            Departamento,
            Inventario.departamento_id == Departamento.departamento_id,
        )
        .where(MovimientoInventario.inventario_id.is_not(None))
    )


def _historial_nuevos():
    """Select del historial de movimientos nuevos (por `stock_sede_id`).

    Proyeccion compatible con `_historial_legados`: atribuye producto, sede e
    institucion desde `stock_sede` y deja departamento/ubicacion en `null`. No
    expone ningun saldo departamental legado.
    """
    return (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            MovimientoInventario.observacion,
            cast(null(), Integer).label("inventario_id"),
            MovimientoInventario.stock_sede_id,
            StockSede.producto_id,
            Producto.nombre.label("producto_nombre"),
            cast(null(), Integer).label("departamento_id"),
            cast(null(), String(200)).label("departamento_nombre"),
            Sede.sede_id.label("sede_id"),
            Sede.nombre.label("sede_nombre"),
            cast(null(), String(100)).label("ubicacion"),
            StockSede.institucion_id,
        )
        .join(
            StockSede,
            MovimientoInventario.stock_sede_id == StockSede.stock_sede_id,
        )
        .join(Producto, StockSede.producto_id == Producto.producto_id)
        .outerjoin(Sede, StockSede.sede_id == Sede.sede_id)
        .where(MovimientoInventario.stock_sede_id.is_not(None))
    )


def listar_movimientos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[MovimientoInventarioRespuesta]:
    """Historial de movimientos con sus datos asociados (plan §3.4, AC-17..AC-20).

    Feature 011 (spec D-2/AC-11): la lectura reune **ambas** poblaciones de
    auditoria en una **proyeccion unica** (`union_all`): los movimientos
    historicos enlazados a `inventario_id` y los nuevos enlazados a
    `stock_sede_id`. Asi el despacho por sede -que deja `inventario_id` nulo- no
    desaparece del historial. Cada fila expone `departamento`/`ubicacion` (legados)
    o `sede` (nuevos) segun su origen, y jamas un saldo departamental legado.

    Como `listar_existencias`, cruza varias tablas, asi que usa `select()` de
    columnas con los onclause explicitos y ejecuta con `.mappings()`. Las etiquetas
    que no coinciden con el campo del DTO (`Producto.nombre` -> `producto_nombre`,
    `Departamento.nombre_dep` -> `departamento_nombre`) se asignan con `.label()`,
    de modo que cada mapping se convierte en `MovimientoInventarioRespuesta` con
    `**fila`.

    El orden `fecha_movimiento DESC, movimiento_id DESC` es determinista incluso
    ante empates de fecha (AC-19); no hay paginacion.

    Ambito institucional (D-4/AC-8): un rol limitado solo ve los movimientos
    cuya institucion -heredada del inventario legado o declarada por la fila de
    stock por sede- coincide con la suya.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    historial = union_all(
        _historial_legados(), _historial_nuevos()
    ).subquery("historial")
    consulta = select(historial)
    consulta = ambito_service.filtrar_por_institucion(
        consulta, historial.c.institucion_id, institucion_id
    )
    consulta = consulta.order_by(
        historial.c.fecha_movimiento.desc(),
        historial.c.movimiento_id.desc(),
    )

    return [
        MovimientoInventarioRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


# ---------------------------------------------------------------------------
# Ciclo de vida del catalogo (Feature 014, spec D-4..D-9 y plan §2.4)
# ---------------------------------------------------------------------------
#
# Orden unico de bloqueo en todos los caminos que pueden solaparse:
#
#     categoria -> producto -> stock_sede
#
# * transicion de producto: lee el resumen (sin bloqueo) para ubicar la
#   categoria, bloquea la categoria si va a reactivar (precondicion de
#   vigencia), bloquea el producto y, en la baja, bloquea las filas de
#   `stock_sede` en orden de PK.
# * transicion de categoria: bloquea la categoria y, en la baja, cuenta los
#   productos activos dentro de la misma transaccion.
# * alta de producto: bloquea la categoria y comprueba su vigencia antes de
#   insertar.
# * movimiento por sede: bloquea el producto antes que la fila de stock.
#
# Asi la baja de categoria, el alta/reactivacion de producto y el movimiento
# no pueden intercalarse para dejar una categoria inactiva con producto activo
# ni un producto inactivo con saldo positivo (AC-6/AC-16). SQLite ignora
# `FOR UPDATE`; la serializacion real se acredita en PostgreSQL (T10).


def _actor_id(identidad: IdentidadAutenticada | None) -> int:
    """Id del usuario autenticado que firma la transicion, o 401 sin sesion."""
    usuario = getattr(identidad, "usuario", None) if identidad is not None else None
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere una sesion autenticada",
        )
    return usuario.usuario_id


def _validar_motivo(motivo: Optional[str]) -> str:
    """Valida el motivo de una transicion **real** (spec D-8/AC-7).

    Se ejecuta en el servicio, nunca en el schema: el 422 debe llegar despues
    del 404 de existencia/pertenencia y despues de la respuesta idempotente
    (spec D-9/AC-3). El motivo se persiste literal, sin recortar.
    """
    if motivo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El motivo es obligatorio para cambiar el estado del catalogo",
        )
    if not motivo.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El motivo no puede estar vacio ni contener solo espacios",
        )
    if len(motivo) > LONGITUD_MAXIMA_MOTIVO:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "El motivo no puede superar los "
                f"{LONGITUD_MAXIMA_MOTIVO} caracteres"
            ),
        )
    return motivo


def _resumen_producto(db: Session, producto_id: int):
    """Fila minima del producto (id, categoria e institucion) sin bloqueo.

    Sirve para conocer la categoria antes de adquirir bloqueos en el orden
    acordado y para ocultar con 404 un recurso inexistente o ajeno antes de
    tocar filas de otro tenant.
    """
    return db.execute(
        select(
            Producto.producto_id,
            Producto.categoria_id,
            Producto.institucion_id,
        ).where(Producto.producto_id == producto_id)
    ).first()


def _bloquear_producto(db: Session, producto_id: int) -> Producto:
    """Producto bloqueado para mutar su vigencia, o 404 si no existe."""
    producto = (
        db.query(Producto)
        .filter(Producto.producto_id == producto_id)
        .with_for_update()
        .first()
    )
    if producto is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_DETALLE_PRODUCTO_NO_ENCONTRADO,
        )
    return producto


def _bloquear_categoria(db: Session, categoria_id: int) -> Categoria:
    """Categoria bloqueada para mutar su vigencia, o 404 si no existe."""
    categoria = (
        db.query(Categoria)
        .filter(Categoria.categoria_id == categoria_id)
        .with_for_update()
        .first()
    )
    if categoria is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_DETALLE_CATEGORIA_NO_ENCONTRADA,
        )
    return categoria


def _exigir_stock_cero(db: Session, producto_id: int) -> None:
    """Precondicion de baja de producto: saldo cero en **todas** las sedes (D-6).

    Solo cuenta `stock_sede`; las filas legadas de `inventario` no son saldo
    operativo. Las filas se bloquean en orden de PK y se leen en la misma
    transaccion que la transicion, de modo que un movimiento concurrente no
    puede crear saldo entre la comprobacion y el cambio de estado.
    """
    filas = (
        db.query(StockSede)
        .filter(StockSede.producto_id == producto_id)
        .order_by(StockSede.stock_sede_id)
        .with_for_update()
        .all()
    )
    if any(fila.stock_actual != 0 for fila in filas):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se puede desactivar un producto con saldo distinto de cero "
                "en stock por sede"
            ),
        )


def _exigir_categoria_sin_productos_activos(db: Session, categoria_id: int) -> None:
    """Precondicion de baja de categoria: ningun producto activo (D-5).

    La comprobacion corre dentro de la misma transaccion que la baja y con la
    categoria ya bloqueada; el alta/reactivacion de producto bloquea esa misma
    categoria antes de escribir (AC-16).
    """
    activo = (
        db.query(Producto)
        .filter(
            Producto.categoria_id == categoria_id,
            Producto.activo.is_(True),
        )
        .first()
    )
    if activo is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No se puede desactivar una categoria con productos activos"
            ),
        )


def transicionar_producto(
    db: Session,
    producto_id: int,
    datos: TransicionCatalogo,
    identidad: IdentidadAutenticada | None = None,
) -> Producto:
    """Cambia la vigencia de un producto existente (Feature 014, D-4..D-9).

    Precedencia de la parte de negocio (el 401/403 de autenticacion, matriz y
    capacidad los resuelve el endpoint en T9):

    1. existencia y pertenencia al tenant -> **404** identico;
    2. si el destino ya es el estado persistido -> **200 idempotente**, sin
       motivo, precondiciones ni historial;
    3. motivo invalido -> **422**;
    4. precondiciones de negocio -> **409** (baja: saldo cero en `stock_sede`;
       reactivacion: categoria activa).

    En una transicion efectiva, el estado y **exactamente una** fila de
    `historial_transicion_producto` se confirman en la misma transaccion.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    resumen = _resumen_producto(db, producto_id)
    if resumen is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_DETALLE_PRODUCTO_NO_ENCONTRADO,
        )
    ambito_service.exigir_pertenencia(
        resumen.institucion_id,
        institucion_id,
        detalle=_DETALLE_PRODUCTO_NO_ENCONTRADO,
    )

    # Orden de bloqueo: categoria (solo en reactivacion) -> producto -> stock.
    categoria = None
    if datos.activo:
        categoria = _bloquear_categoria(db, resumen.categoria_id)
    producto = _bloquear_producto(db, producto_id)

    if producto.activo == datos.activo:
        # Repeticion idempotente: no exige motivo ni evalua precondiciones y no
        # escribe historial (AC-8). Se devuelve el estado persistido.
        return producto

    motivo = _validar_motivo(datos.motivo)

    if datos.activo:
        if categoria is None or not categoria.activo:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No se puede reactivar un producto cuya categoria esta inactiva"
                ),
            )
    else:
        _exigir_stock_cero(db, producto.producto_id)

    origen = producto.activo
    producto.activo = datos.activo
    db.add(
        HistorialTransicionProducto(
            producto_id=producto.producto_id,
            usuario_id=_actor_id(identidad),
            activo_origen=origen,
            activo_destino=datos.activo,
            motivo=motivo,
        )
    )
    db.commit()
    db.refresh(producto)
    return producto


def transicionar_categoria(
    db: Session,
    categoria_id: int,
    datos: TransicionCatalogo,
    identidad: IdentidadAutenticada | None = None,
) -> Categoria:
    """Cambia la vigencia de una categoria existente (Feature 014, D-4/D-5/D-9).

    Una categoria solo puede desactivarse cuando no tiene productos activos;
    reactivarla **no** reactiva sus productos (no hay cascada). Estado e
    historial se confirman juntos, o no se confirman.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    categoria = _bloquear_categoria(db, categoria_id)
    ambito_service.exigir_pertenencia(
        categoria.institucion_id,
        institucion_id,
        detalle=_DETALLE_CATEGORIA_NO_ENCONTRADA,
    )

    if categoria.activo == datos.activo:
        return categoria

    motivo = _validar_motivo(datos.motivo)

    if not datos.activo:
        _exigir_categoria_sin_productos_activos(db, categoria.categoria_id)

    origen = categoria.activo
    categoria.activo = datos.activo
    db.add(
        HistorialTransicionCategoria(
            categoria_id=categoria.categoria_id,
            usuario_id=_actor_id(identidad),
            activo_origen=origen,
            activo_destino=datos.activo,
            motivo=motivo,
        )
    )
    db.commit()
    db.refresh(categoria)
    return categoria


def listar_gestion(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> GestionCatalogoRespuesta:
    """Listado administrativo del catalogo: ambos estados, acotado al tenant.

    Es la unica lectura que devuelve productos/categorias **activos e
    inactivos** (spec AC-15); los listados operativos siguen filtrados para
    todos los roles. Solo el Administrador llega aqui (la autorizacion HTTP se
    cablea en T9); el tenant se deriva en servidor, nunca del cliente.

    El producto viaja con `categoria_nombre` y `categoria_activa` resueltos por
    el join, porque la vista administrativa necesita saber que acciones son
    viables sin cruzar listados operativos.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    consulta_productos = (
        select(
            Producto.producto_id,
            Producto.nombre,
            Producto.descripcion,
            Producto.unidad_medida,
            Producto.stock_minimo,
            Producto.categoria_id,
            Categoria.nombre_cat.label("categoria_nombre"),
            Categoria.activo.label("categoria_activa"),
            Producto.institucion_id,
            Producto.activo,
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .order_by(Producto.nombre, Producto.producto_id)
    )
    consulta_productos = ambito_service.filtrar_por_institucion(
        consulta_productos, Producto.institucion_id, institucion_id
    )
    productos = [
        ProductoGestionRespuesta(**fila)
        for fila in db.execute(consulta_productos).mappings()
    ]

    consulta_categorias = db.query(Categoria)
    consulta_categorias = ambito_service.filtrar_por_institucion(
        consulta_categorias, Categoria.institucion_id, institucion_id
    )
    categorias = [
        CategoriaGestionRespuesta.model_validate(categoria)
        for categoria in consulta_categorias.order_by(
            Categoria.nombre_cat, Categoria.categoria_id
        ).all()
    ]

    return GestionCatalogoRespuesta(productos=productos, categorias=categorias)


def _resolver_recurso_historial(
    db: Session,
    entidad,
    id_columna,
    recurso_id: int,
    institucion_id: str | None,
    detalle: str,
):
    """Recurso del historial existente y del tenant, o 404 oculto (AC-12)."""
    recurso = db.query(entidad).filter(id_columna == recurso_id).first()
    if recurso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)
    ambito_service.exigir_pertenencia(
        ambito_service.institucion_de_recurso(recurso),
        institucion_id,
        detalle=detalle,
    )
    return recurso


def listar_historial_producto(
    db: Session,
    producto_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> List[HistorialTransicionProductoRespuesta]:
    """Transiciones de un producto, mas reciente primero (spec §7, AC-12).

    El historial es inmutable y de solo lectura: no existe alta, edicion ni
    borrado por API. Un recurso inexistente o de otro tenant responde 404
    identico; el 403 por rol se resuelve antes de esta llamada (T9).
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    _resolver_recurso_historial(
        db,
        Producto,
        Producto.producto_id,
        producto_id,
        institucion_id,
        _DETALLE_PRODUCTO_NO_ENCONTRADO,
    )

    consulta = (
        select(
            HistorialTransicionProducto.historial_producto_id,
            HistorialTransicionProducto.producto_id,
            HistorialTransicionProducto.usuario_id,
            HistorialTransicionProducto.fecha_transicion,
            HistorialTransicionProducto.activo_origen,
            HistorialTransicionProducto.activo_destino,
            HistorialTransicionProducto.motivo,
            Usuario.nombre.label("usuario_nombre"),
            Usuario.apellido.label("usuario_apellido"),
        )
        .join(
            Usuario,
            HistorialTransicionProducto.usuario_id == Usuario.usuario_id,
        )
        .where(HistorialTransicionProducto.producto_id == producto_id)
        .order_by(
            HistorialTransicionProducto.fecha_transicion.desc(),
            HistorialTransicionProducto.historial_producto_id.desc(),
        )
    )
    return [
        HistorialTransicionProductoRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


def listar_historial_categoria(
    db: Session,
    categoria_id: int,
    identidad: IdentidadAutenticada | None = None,
) -> List[HistorialTransicionCategoriaRespuesta]:
    """Transiciones de una categoria, mas reciente primero (spec §7, AC-12)."""
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    _resolver_recurso_historial(
        db,
        Categoria,
        Categoria.categoria_id,
        categoria_id,
        institucion_id,
        _DETALLE_CATEGORIA_NO_ENCONTRADA,
    )

    consulta = (
        select(
            HistorialTransicionCategoria.historial_categoria_id,
            HistorialTransicionCategoria.categoria_id,
            HistorialTransicionCategoria.usuario_id,
            HistorialTransicionCategoria.fecha_transicion,
            HistorialTransicionCategoria.activo_origen,
            HistorialTransicionCategoria.activo_destino,
            HistorialTransicionCategoria.motivo,
            Usuario.nombre.label("usuario_nombre"),
            Usuario.apellido.label("usuario_apellido"),
        )
        .join(
            Usuario,
            HistorialTransicionCategoria.usuario_id == Usuario.usuario_id,
        )
        .where(HistorialTransicionCategoria.categoria_id == categoria_id)
        .order_by(
            HistorialTransicionCategoria.fecha_transicion.desc(),
            HistorialTransicionCategoria.historial_categoria_id.desc(),
        )
    )
    return [
        HistorialTransicionCategoriaRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


def registrar_movimiento(
    db: Session,
    movimiento: MovimientoCrear,
    identidad: IdentidadAutenticada | None = None,
):
    """Aplica un movimiento de stock y deja rastro en `movimiento_inventario`.

    Trazabilidad Absoluta (`constitucion.md` §2): el registro de auditoria se
    escribe en la misma transaccion que la mutacion del stock, o no se escribe.

    La Feature 011 (spec D-2/§9, AC-7) hace de `stock_sede_id` la referencia de
    los movimientos **nuevos**: la mutacion toca `StockSede` y la auditoria enlaza
    esa fila dejando `inventario_id` nulo. Un `sede_id` distinto al del Bodeguero
    -de su institucion o ajeno- se oculta con **404** sin mutar; sin sede asignada
    la operacion se deniega con **409**. El camino legado por `inventario_id` se
    conserva para los registros historicos, acotado a la institucion del actor.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    if movimiento.stock_sede_id is not None:
        return _registrar_movimiento_por_sede(
            db, movimiento, institucion_id, identidad
        )

    if movimiento.inventario_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Debe indicar 'stock_sede_id' o 'inventario_id'",
        )

    inventario = (
        db.query(Inventario)
        .filter(Inventario.inventario_id == movimiento.inventario_id)
        .first()
    )
    if not inventario:
        raise HTTPException(status_code=404, detail="Inventario no encontrado")

    if institucion_id is not None:
        ambito_service.validar_departamento_en_alcance(
            db, inventario.departamento_id, institucion_id
        )

    # Feature 014 (AC-9): el camino legado de auditoria sigue disponible para sus
    # filas historicas, pero tampoco admite movimientos nuevos sobre un producto
    # retirado.
    producto_legado = db.get(Producto, inventario.producto_id)
    if producto_legado is not None and not producto_legado.activo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede registrar un movimiento sobre un producto inactivo",
        )

    tipo = movimiento.tipo_movimiento.upper()
    if tipo == TIPO_ENTRADA:
        inventario.stock_actual += movimiento.cantidad
    elif tipo == TIPO_SALIDA:
        if inventario.stock_actual < movimiento.cantidad:
            raise HTTPException(
                status_code=400,
                detail="Stock insuficiente para realizar la salida",
            )
        inventario.stock_actual -= movimiento.cantidad
    else:
        raise HTTPException(
            status_code=400,
            detail="Tipo de movimiento invalido (Use 'ENTRADA' o 'SALIDA')",
        )

    db.add(MovimientoInventario(**movimiento.model_dump()))
    db.commit()
    db.refresh(inventario)
    return inventario


def _registrar_movimiento_por_sede(
    db: Session,
    movimiento: MovimientoCrear,
    institucion_id: str | None,
    identidad: IdentidadAutenticada | None,
) -> StockSede:
    """Movimiento nuevo contra `stock_sede` con auditoria por `stock_sede_id`.

    * Una fila inexistente o de otra institucion responde **404** (AC-3).
    * Un Bodeguero solo opera su `usuario.sede_id`: otra sede -propia o ajena-
      responde **404** sin mutar; sin sede asignada, **409** (AC-7).
    * `SALIDA` por encima del saldo responde **409** y no deja auditoria (AC-7).

    Feature 014 (AC-6): el movimiento adquiere el bloqueo del **producto antes
    que la fila de stock**, el mismo orden que la transicion del catalogo
    (categoria -> producto -> stock). Asi la entrada de stock y la baja de
    producto se serializan y nunca queda un producto inactivo con saldo
    positivo. La comprobacion de que el producto sigue activo se agrega en T8.
    """
    referencia = db.get(StockSede, movimiento.stock_sede_id)
    detalle = "Stock por sede no encontrado"
    if referencia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)
    ambito_service.exigir_pertenencia(
        referencia.institucion_id, institucion_id, detalle=detalle
    )

    if permisos.nombre_rol_de(identidad) == _BODEGUERO:
        sede_rol = sede_del_alcance_por_rol(db, identidad)
        if referencia.sede_id != sede_rol:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)

    # Orden de bloqueo: producto antes que stock_sede (AC-6/AC-16). El estado se
    # comprueba con el producto ya bloqueado, de modo que una baja concurrente no
    # pueda intercalarse entre la verificacion y la mutacion del saldo.
    producto = (
        db.query(Producto)
        .filter(Producto.producto_id == referencia.producto_id)
        .with_for_update()
        .first()
    )
    if producto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)
    if not producto.activo:
        # Feature 014 (AC-9): un producto retirado no admite movimientos nuevos.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede registrar un movimiento sobre un producto inactivo",
        )
    fila = (
        db.query(StockSede)
        .filter(StockSede.stock_sede_id == referencia.stock_sede_id)
        .with_for_update()
        .one()
    )

    tipo = movimiento.tipo_movimiento.upper()
    if tipo == TIPO_ENTRADA:
        fila.stock_actual += movimiento.cantidad
    elif tipo == TIPO_SALIDA:
        if fila.stock_actual < movimiento.cantidad:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stock insuficiente para realizar la salida",
            )
        fila.stock_actual -= movimiento.cantidad
    else:
        raise HTTPException(
            status_code=400,
            detail="Tipo de movimiento invalido (Use 'ENTRADA' o 'SALIDA')",
        )

    db.add(
        MovimientoInventario(
            tipo_movimiento=tipo,
            cantidad=movimiento.cantidad,
            observacion=movimiento.observacion,
            stock_sede_id=fila.stock_sede_id,
        )
    )
    db.commit()
    db.refresh(fila)
    return fila
