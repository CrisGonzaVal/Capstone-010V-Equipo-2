from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api import dependencies
from app.schemas.inventario_schema import (
    InventarioRespuesta,
    MovimientoCrear,
    MovimientoInventarioRespuesta,
    ProductoExistenciaRespuesta,
)
from app.schemas.producto_schema import (
    CategoriaRespuesta,
    ProductoCrear,
    ProductoRespuesta,
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
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/inventario/categorias"))
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
        "ajeno se oculta con **404**, igual que uno inexistente (Feature 008, D-4)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
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
    responses=dependencies.respuestas_de_autorizacion(),
    dependencies=[
        Depends(dependencies.requiere_operacion("GET", "/api/v1/inventario/productos"))
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
        "ajeno se oculta con **404**, igual que uno inexistente (Feature 008, D-4)."
    ),
    responses={
        **dependencies.respuestas_de_autorizacion(),
        **dependencies.respuesta_recurso_oculto(),
    },
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
        Depends(dependencies.requiere_operacion("POST", "/api/v1/inventario/productos"))
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
        "queda marcado como critico."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
)
def listar_existencias(
    q: Optional[str] = Query(
        default=None,
        description="Busqueda parcial, sin distincion de mayusculas, sobre nombre y descripcion.",
    ),
    categoria_id: Optional[int] = Query(default=None, description="Filtra por categoria."),
    departamento_id: Optional[int] = Query(
        default=None, description="Acota el stock y las sedes a un departamento.",
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
            solo_criticos=solo_criticos,
            identidad=identidad,
        ),
    )


@router.get(
    "/stock",
    response_model=List[InventarioRespuesta],
    status_code=status.HTTP_200_OK,
    summary="Listar existencias, opcionalmente por departamento",
    responses=dependencies.respuestas_de_autorizacion(),
)
def listar_inventario(
    departamento_id: int = None,
    identidad: IdentidadAutenticada = Depends(
        dependencies.requiere_operacion("GET", "/api/v1/inventario/stock")
    ),
    db: Session = Depends(dependencies.get_db_negocio),
):
    return global_service.agregar_lista_global(
        db,
        identidad,
        lambda sesion: inventario_service.listar_inventario(
            sesion, departamento_id, identidad
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
        "inmutable de la trazabilidad de stock."
    ),
    responses=dependencies.respuestas_de_autorizacion(),
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
