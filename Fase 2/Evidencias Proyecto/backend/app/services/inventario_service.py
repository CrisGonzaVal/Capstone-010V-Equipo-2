from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import Integer, String, and_, cast, null, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.core import permisos
from app.models import (
    Categoria,
    Departamento,
    Inventario,
    MovimientoInventario,
    Producto,
    Sede,
    StockSede,
)
from app.schemas.inventario_schema import (
    MovimientoCrear,
    MovimientoInventarioRespuesta,
    ProductoExistenciaRespuesta,
    SedeExistenciaRespuesta,
    StockSedeRespuesta,
)
from app.schemas.producto_schema import ProductoCrear
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA = "SALIDA"

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
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Categoria)
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
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    consulta = db.query(Producto).options(selectinload(Producto.categoria))
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
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    categoria = db.get(Categoria, datos.categoria_id)
    if categoria is None:
        raise HTTPException(status_code=404, detail="No existe la categoria indicada")
    # Una categoria de otra institucion no habilita el alta (AC-9/AC-10).
    ambito_service.exigir_pertenencia(
        ambito_service.institucion_de_recurso(categoria),
        institucion_id,
        detalle="No existe la categoria indicada",
    )

    # La institucion del producto es la del usuario; solo si el ambito fuera
    # global (Superadmin, que la matriz 008 no autoriza a escribir) cae a la de
    # la categoria, para no romper la FK compuesta.
    institucion_producto = (
        institucion_id if institucion_id is not None else categoria.institucion_id
    )
    nuevo_producto = Producto(
        **datos.model_dump(), institucion_id=institucion_producto
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

    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(
            Producto.nombre.ilike(patron) | Producto.descripcion.ilike(patron)
        )
    if categoria_id is not None:
        consulta = consulta.where(Categoria.categoria_id == categoria_id)
    if departamento_id is not None:
        # Degrada el `outerjoin` a INNER: solo interesan los productos con
        # existencias en la sede del departamento pedido.
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
    """
    fila = db.get(StockSede, movimiento.stock_sede_id)
    detalle = "Stock por sede no encontrado"
    if fila is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)
    ambito_service.exigir_pertenencia(
        fila.institucion_id, institucion_id, detalle=detalle
    )

    if permisos.nombre_rol_de(identidad) == _BODEGUERO:
        sede_rol = sede_del_alcance_por_rol(db, identidad)
        if fila.sede_id != sede_rol:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detalle)

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
