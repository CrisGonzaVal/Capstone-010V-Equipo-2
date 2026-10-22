from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoriaRespuesta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    categoria_id: int
    nombre_cat: str
    descripcion_cat: Optional[str] = None
    # Feature 008 (AC-8): atribucion institucional para las lecturas globales del
    # Superadmin. Campo informativo; el servidor no acepta institucion del cliente.
    institucion_id: Optional[str] = None
    # Feature 014 (AC-15): estado vigente del catalogo. La transicion (baja o
    # reactivacion) responde con el recurso y este campo ya persistido.
    activo: bool = True


class ProductoBase(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int = 0
    categoria_id: int


class ProductoCrear(ProductoBase):
    pass


class ProductoRespuesta(ProductoBase):
    model_config = ConfigDict(from_attributes=True)

    producto_id: int
    # Feature 008 (AC-8): institucion de pertenencia del producto, para que las
    # lecturas globales del Superadmin atribuyan cada registro.
    institucion_id: Optional[str] = None
    # Feature 014 (AC-13): el producto nace activo y la transicion devuelve su
    # estado persistido en el mismo recurso.
    activo: bool = True
    categoria: Optional[CategoriaRespuesta] = None


# ---------------------------------------------------------------------------
# Ciclo de vida del catalogo (Feature 014, plan §2.3)
# ---------------------------------------------------------------------------


class TransicionCatalogo(BaseModel):
    """Payload de `PATCH /inventario/productos/{id}/estado` y `.../categorias`.

    Feature 014 (spec D-9, AC-3/AC-7/AC-8): el cuerpo expresa **solo** el estado
    destino (`activo`) y el `motivo` libre de una transicion real.

    `motivo` se declara opcional y **sin** restriccion de contenido ni longitud:
    la validacion (no vacio, no solo espacios, hasta 500 caracteres) es del
    servicio. Si el schema la rechazara, el 422 se dispararia antes del handler y
    se adelantaria al 404 de existencia/pertenencia (AC-3) y a la respuesta 200
    idempotente, que no exige motivo (AC-8). Mismo patron que `TicketMotivo` de la
    Feature 013.

    Un motivo ausente queda en `None` y el servicio decide si esa ausencia es
    valida (repeticion idempotente) o un 422 (transicion efectiva).
    """

    activo: bool = Field(
        description="Estado destino del recurso: `true` reactiva, `false` da de baja."
    )
    motivo: Optional[str] = Field(
        default=None,
        description=(
            "Motivo libre de la transicion efectiva. Obligatorio, no vacio y de "
            "hasta 500 caracteres para un cambio real; lo valida el servicio y no "
            "se exige en una repeticion idempotente."
        ),
    )


class CategoriaGestionRespuesta(BaseModel):
    """Fila de categoria del listado de gestion (Feature 014, AC-15).

    El listado administrativo devuelve **ambos** estados, a diferencia de
    `GET /inventario/categorias`, que sigue filtrado para todos los roles.
    """

    model_config = ConfigDict(from_attributes=True)

    categoria_id: int
    nombre_cat: str
    descripcion_cat: Optional[str] = None
    institucion_id: Optional[str] = None
    activo: bool = True


class ProductoGestionRespuesta(BaseModel):
    """Fila de producto del listado de gestion (Feature 014, AC-15).

    Sin `from_attributes`: `categoria_nombre` y `categoria_activa` no son columnas
    de `producto`, los resuelve el servicio desde la categoria del mismo tenant
    (plan §2.7). El estado de la categoria viaja junto al del producto porque la
    vista administrativa necesita saber que acciones son viables (spec §5: la
    seccion de gestion presenta el estado y las reglas de accion).
    """

    producto_id: int
    nombre: str
    descripcion: Optional[str] = None
    unidad_medida: Optional[str] = None
    stock_minimo: int
    categoria_id: int
    categoria_nombre: str
    categoria_activa: bool
    institucion_id: Optional[str] = None
    activo: bool

