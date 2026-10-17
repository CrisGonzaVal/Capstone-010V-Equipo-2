from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class StockSedeRespuesta(BaseModel):
    """Read model de `GET /inventario/stock` (Feature 011, T8/B1).

    Serie **plana** del saldo vigente por sede (`stock_sede`): la unica fuente de
    stock operativo (spec D-2). Expone la referencia de escritura
    (`stock_sede_id`) y la sede resuelta (`sede_id`/`sede_nombre`), que
    `GET /inventario/existencias` no entrega al agrupar por producto: sirve para
    localizar el destino de `POST /inventario/movimientos` y filtrar por sede.

    Nunca lee ni proyecta las filas legadas de `inventario` como saldo
    (spec §7); por eso no lleva `inventario_id`, `departamento_id` ni `ubicacion`.
    """

    model_config = ConfigDict(from_attributes=True)

    stock_sede_id: int
    sede_id: int
    sede_nombre: str
    producto_id: int
    stock_actual: int
    # Feature 008 (AC-8): institucion de la fila de stock, para la atribucion de
    # las lecturas globales del Superadmin.
    institucion_id: Optional[str] = None


class MovimientoInventarioRespuesta(BaseModel):
    """Read model de `GET /inventario/movimientos`.

    NO lleva `model_config = ConfigDict(from_attributes=True)`: la consulta cruza
    `movimiento_inventario` con su origen de auditoria (legado o nuevo) y lo arma
    el service a partir de un mapping de columnas (plan §3.4).

    Feature 011 (spec D-2/AC-11): la proyeccion es **unica y compatible** para las
    dos poblaciones. Un movimiento **legado** enlaza `inventario_id` y expone
    `departamento_id`/`departamento_nombre`/`ubicacion`; un movimiento **nuevo**
    enlaza `stock_sede_id` y expone `sede_id`/`sede_nombre`. El conjunto ajeno al
    origen queda `null`, y en ningun caso se expone un saldo departamental legado.
    """

    movimiento_id: int
    tipo_movimiento: str
    cantidad: int
    fecha_movimiento: datetime
    observacion: Optional[str] = None
    inventario_id: Optional[int] = None
    #: Destino nuevo: la fila de `stock_sede` del movimiento (Feature 011).
    stock_sede_id: Optional[int] = None
    producto_id: int
    producto_nombre: str
    departamento_id: Optional[int] = None
    departamento_nombre: Optional[str] = None
    #: Atribucion de sede de un movimiento nuevo (Feature 011).
    sede_id: Optional[int] = None
    sede_nombre: Optional[str] = None
    ubicacion: Optional[str] = None
    # Feature 008 (AC-8): institucion del movimiento, para que las lecturas
    # globales del Superadmin atribuyan cada fila de auditoria.
    institucion_id: Optional[str] = None


class MovimientoCrear(BaseModel):
    """Alta de un movimiento de stock (Feature 002; adaptada por la 011, T8).

    La Feature 011 sustituye el saldo operativo departamental: los movimientos
    **nuevos** referencian la fila de stock por sede (`stock_sede_id`) y dejan
    `inventario_id` nulo (spec D-2 y §7). `inventario_id` se conserva opcional
    para no romper el flujo historico mientras la migracion lo retire; el
    servicio exige exactamente una de las dos referencias.
    """

    tipo_movimiento: str  # 'ENTRADA' o 'SALIDA'
    cantidad: int
    observacion: Optional[str] = None
    #: Destino nuevo: la fila de `stock_sede` (una por sede/producto).
    stock_sede_id: Optional[int] = None
    #: Destino legado: la fila departamental de `inventario`.
    inventario_id: Optional[int] = None


class SedeExistenciaRespuesta(BaseModel):
    """Existencia de un producto en una sede (Feature 011, spec D-6/AC-11).

    `GET /inventario/existencias` expone obligatoriamente la **sede** y su
    **saldo**: la granularidad vigente es `(sede, producto)` y el nombre viaja
    resuelto para que la vista no tenga que cruzar ids contra
    `/organizacion/sedes`. El total institucional se deriva como la suma de las
    sedes de la respuesta, no de un saldo departamental paralelo.
    """

    sede_id: int
    sede_nombre: str
    stock_actual: int


class ProductoExistenciaRespuesta(BaseModel):
    """Read model de `GET /inventario/existencias`.

    NO lleva `model_config = ConfigDict(from_attributes=True)`: lo arma el
    service a mano porque cruza cuatro tablas y agrega. Con `from_attributes`,
    Pydantic buscaria `stock_total`, `es_critico` y `sedes` en el objeto ORM y
    no los encontraria (spec D-7).
    """

    producto_id: int
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int
    categoria_id: int
    categoria_nombre: str
    stock_total: int
    es_critico: bool
    # Feature 008 (AC-8): institucion del producto, para la atribucion de las
    # lecturas globales del Superadmin.
    institucion_id: Optional[str] = None
    sedes: List[SedeExistenciaRespuesta]
