from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Categoria, Departamento, Inventario, MovimientoInventario, Producto
from app.schemas.inventario_schema import (
    MovimientoCrear,
    MovimientoInventarioRespuesta,
    ProductoExistenciaRespuesta,
    SedeExistenciaRespuesta,
)
from app.schemas.producto_schema import ProductoCrear
from app.services import ambito_service
from app.services.auth_service import IdentidadAutenticada

TIPO_ENTRADA = "ENTRADA"
TIPO_SALIDA = "SALIDA"


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


def listar_inventario(
    db: Session,
    departamento_id: Optional[int] = None,
    identidad: IdentidadAutenticada | None = None,
) -> List[Inventario]:
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    if departamento_id:
        ambito_service.validar_departamento_en_alcance(
            db, departamento_id, institucion_id
        )

    consulta = db.query(Inventario)
    if institucion_id is not None:
        consulta = consulta.join(
            Departamento, Inventario.departamento_id == Departamento.departamento_id
        ).filter(Departamento.institucion_id == institucion_id)
    if departamento_id:
        consulta = consulta.filter(Inventario.departamento_id == departamento_id)
    return consulta.order_by(Inventario.inventario_id).all()


def listar_existencias(
    db: Session,
    q: Optional[str] = None,
    categoria_id: Optional[int] = None,
    departamento_id: Optional[int] = None,
    solo_criticos: bool = False,
    identidad: IdentidadAutenticada | None = None,
) -> List[ProductoExistenciaRespuesta]:
    """Un elemento por producto del catalogo, con su stock y el desglose por sede.

    Es la unica lectura que cruza varias tablas, asi que -a diferencia del resto
    del servicio- usa `select()` de SQLAlchemy 2.0 con los onclause explicitos
    (`plan.md` §3.2.2). `categoria` entra con join interno porque
    `producto.categoria_id` es NOT NULL con FK; `inventario` y `departamento`
    entran con `outerjoin` para que un producto sin existencias no desaparezca
    del catalogo (spec D-4).

    Ambito institucional (`ambito_service`, D-1/D-4/AC-5/AC-8): el catalogo es
    institucional, asi que un rol limitado solo ve los productos de su
    institucion, y su `outerjoin` de inventario solo acepta las existencias de su
    institucion (un producto propio sin existencias aparece con `sedes` vacio y
    `stock_total` 0). Superadmin ve el catalogo global y cada elemento queda
    atribuido por `institucion_id`. Un `departamento_id` explicito de otra
    institucion responde 403.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)
    if departamento_id is not None:
        ambito_service.validar_departamento_en_alcance(
            db, departamento_id, institucion_id
        )

    condicion_inventario = Producto.producto_id == Inventario.producto_id
    if institucion_id is not None:
        departamentos_propios = select(Departamento.departamento_id).where(
            Departamento.institucion_id == institucion_id
        )
        condicion_inventario = and_(
            condicion_inventario,
            Inventario.departamento_id.in_(departamentos_propios),
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
            Inventario.inventario_id,
            Inventario.stock_actual,
            Inventario.ubicacion,
            Departamento.departamento_id,
            Departamento.nombre_dep,
        )
        .join(Categoria, Producto.categoria_id == Categoria.categoria_id)
        .outerjoin(Inventario, condicion_inventario)
        .outerjoin(Departamento, Inventario.departamento_id == Departamento.departamento_id)
    )

    if institucion_id is not None:
        # El catalogo ya es institucional (D-1/AC-5): un rol limitado solo ve los
        # productos de su institucion, no uno ajeno con `sedes` vacio.
        consulta = consulta.where(Producto.institucion_id == institucion_id)

    if q:
        patron = f"%{q.strip()}%"
        consulta = consulta.where(Producto.nombre.ilike(patron) | Producto.descripcion.ilike(patron))
    if categoria_id is not None:
        consulta = consulta.where(Categoria.categoria_id == categoria_id)
    if departamento_id is not None:
        # Degrada el `outerjoin` de inventario a INNER: aqui solo interesan los
        # productos que tienen existencias en esa sede.
        consulta = consulta.where(Inventario.departamento_id == departamento_id)

    consulta = consulta.order_by(
        Producto.nombre,
        Producto.producto_id,
        Departamento.nombre_dep,
        Departamento.departamento_id,
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

        # `inventario_id` llega en None cuando el producto no tiene existencias.
        if fila.inventario_id is not None:
            acumulador["stock_total"] += fila.stock_actual
            acumulador["sedes"].append(
                SedeExistenciaRespuesta(
                    inventario_id=fila.inventario_id,
                    departamento_id=fila.departamento_id,
                    departamento_nombre=fila.nombre_dep,
                    stock_actual=fila.stock_actual,
                    ubicacion=fila.ubicacion,
                )
            )

    # `dict` conserva el orden de insercion, asi que el `ORDER BY` se propaga
    # solo y no hay que reordenar.
    existencias = [
        ProductoExistenciaRespuesta(
            **acumulador,
            es_critico=es_stock_critico(acumulador["stock_total"], acumulador["stock_minimo"]),
        )
        for acumulador in acumuladores.values()
    ]

    # `solo_criticos` no cabe en el `WHERE`: es un predicado sobre `stock_total`,
    # que no existe hasta agrupar. La base ya filtro por texto, categoria y sede.
    if solo_criticos:
        existencias = [existencia for existencia in existencias if existencia.es_critico]

    return existencias


def listar_movimientos(
    db: Session, identidad: IdentidadAutenticada | None = None
) -> List[MovimientoInventarioRespuesta]:
    """Historial de movimientos con sus datos asociados (plan §3.4, AC-17..AC-20).

    Como `listar_existencias`, cruza varias tablas, asi que usa `select()` de
    columnas con los onclause explicitos y ejecuta con `.mappings()`: al no haber
    entidad en el `FROM`, SQLAlchemy no puede deducir los joins por si sola. Las
    etiquetas de las columnas que no coinciden con el nombre del campo del DTO
    (`Producto.nombre` -> `producto_nombre`, `Departamento.nombre_dep` ->
    `departamento_nombre`) se asignan con `.label()`, de modo que cada mapping se
    convierte en `MovimientoInventarioRespuesta` con `**fila`.

    Los joins son internos porque cada movimiento persistido resuelve su
    inventario, producto y departamento por FK. El orden `fecha_movimiento DESC,
    movimiento_id DESC` es determinista incluso ante empates de fecha (AC-19); no
    hay paginacion.

    Ambito institucional (D-4/AC-8): un rol limitado solo ve los movimientos cuyo
    inventario pertenece a un departamento de su institucion.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

    consulta = (
        select(
            MovimientoInventario.movimiento_id,
            MovimientoInventario.tipo_movimiento,
            MovimientoInventario.cantidad,
            MovimientoInventario.fecha_movimiento,
            MovimientoInventario.observacion,
            MovimientoInventario.inventario_id,
            Inventario.producto_id,
            Producto.nombre.label("producto_nombre"),
            Inventario.departamento_id,
            Departamento.nombre_dep.label("departamento_nombre"),
            Departamento.institucion_id,
            Inventario.ubicacion,
        )
        .join(Inventario, MovimientoInventario.inventario_id == Inventario.inventario_id)
        .join(Producto, Inventario.producto_id == Producto.producto_id)
        .join(Departamento, Inventario.departamento_id == Departamento.departamento_id)
        .order_by(
            MovimientoInventario.fecha_movimiento.desc(),
            MovimientoInventario.movimiento_id.desc(),
        )
    )

    if institucion_id is not None:
        consulta = consulta.where(Departamento.institucion_id == institucion_id)

    return [
        MovimientoInventarioRespuesta(**fila)
        for fila in db.execute(consulta).mappings()
    ]


def registrar_movimiento(
    db: Session,
    movimiento: MovimientoCrear,
    identidad: IdentidadAutenticada | None = None,
) -> Inventario:
    """Aplica un movimiento de stock y deja rastro en `movimiento_inventario`.

    Trazabilidad Absoluta (`constitucion.md` §2): el registro de auditoria se
    escribe en la misma transaccion que la mutacion del stock, o no se escribe.

    Ambito institucional (D-4/AC-8): un rol limitado solo puede mover stock de un
    inventario de su institucion; un inventario de otra institucion responde 403
    sin mutar el stock.
    """
    institucion_id = ambito_service.alcance_institucional(db, identidad)

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
