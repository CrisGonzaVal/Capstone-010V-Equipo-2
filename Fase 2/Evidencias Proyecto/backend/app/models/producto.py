from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base

# Feature 008 (D-1): el catalogo deja de ser global. `institucion_id` ancla cada
# categoria/producto a una institucion y participa de las claves compuestas que
# el esquema usa para rechazar referencias cruzadas (AC-2, AC-4). La PK simple se
# conserva: los identificadores publicos no cambian (stack.md §"Modelo relacional
# y particionamiento por institucion").
#
# Las columnas institucionales son `nullable=True` **en el modelo ORM** a
# proposito durante esta tarea: en T2 los servicios aun no las pueblan (lo hacen
# T5-T7) y la suite SQLite debe seguir verde. El DDL de instalacion nueva
# (`database/01_esquema.sql`) las declara `NOT NULL`, que es la autoridad para
# datos reales. Las relaciones ORM se fijan al id simple (`primaryjoin`) para que
# sigan resolviendo filas antiguas sin institucion.


class Categoria(Base):
    __tablename__ = "categoria"
    __table_args__ = (
        # Destino de la FK compuesta `producto -> categoria` (AC-2).
        UniqueConstraint(
            "institucion_id", "categoria_id", name="categoria_institucion_uk"
        ),
    )

    categoria_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre_cat = Column(String(100), nullable=False)
    descripcion_cat = Column(String(200))
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"))
    #: Estado de ciclo de vida del catalogo (Feature 014, spec D-3/AC-13).
    #: `True` = vigente; `False` = retirada sin borrado fisico ni perdida de
    #: referencias. Nace activa y la transicion es reversible; alineado con
    #: `sede`/`departamento` (default de aplicacion y de servidor `TRUE`).
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    productos = relationship(
        "Producto",
        back_populates="categoria",
        primaryjoin="Categoria.categoria_id == Producto.categoria_id",
        foreign_keys="Producto.categoria_id",
    )
    historiales_transiciones = relationship(
        "HistorialTransicionCategoria",
        back_populates="categoria",
        primaryjoin="Categoria.categoria_id == HistorialTransicionCategoria.categoria_id",
        foreign_keys="HistorialTransicionCategoria.categoria_id",
    )


class Producto(Base):
    __tablename__ = "producto"
    __table_args__ = (
        # Sustituye a la FK simple `producto.categoria_id -> categoria`: ahora el
        # producto solo puede apuntar a una categoria de su misma institucion
        # (AC-2). La relacion ORM se fija a `categoria_id` para seguir resolviendo
        # filas sin institucion.
        ForeignKeyConstraint(
            ["institucion_id", "categoria_id"],
            ["categoria.institucion_id", "categoria.categoria_id"],
            name="producto_categoria_institucion_fk",
        ),
        # Destino de las FK compuestas `inventario -> producto` y
        # `detalle_ticket -> producto` (AC-2, AC-4).
        UniqueConstraint(
            "institucion_id", "producto_id", name="producto_institucion_uk"
        ),
    )

    producto_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    nombre = Column(String(150), nullable=False)
    descripcion = Column(String(250))
    unidad_medida = Column(String(30))
    stock_minimo = Column(Integer, nullable=False, default=0)
    categoria_id = Column(Integer, nullable=False)
    institucion_id = Column(String(20), ForeignKey("institucion.institucion_id"))
    #: Estado de ciclo de vida del producto (Feature 014, spec D-3/AC-13). Un
    #: producto inactivo no participa del catalogo operativo, pero conserva sus
    #: referencias historicas. Solo puede desactivarse con saldo cero en
    #: `stock_sede` (regla del servicio, no del DDL).
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    categoria = relationship(
        "Categoria",
        back_populates="productos",
        primaryjoin="Producto.categoria_id == Categoria.categoria_id",
        foreign_keys="Producto.categoria_id",
    )
    inventarios = relationship(
        "Inventario",
        back_populates="producto",
        primaryjoin="Producto.producto_id == Inventario.producto_id",
        foreign_keys="Inventario.producto_id",
    )
    detalles = relationship(
        "DetalleTicket",
        back_populates="producto",
        primaryjoin="Producto.producto_id == DetalleTicket.producto_id",
        foreign_keys="DetalleTicket.producto_id",
    )
    historiales_transiciones = relationship(
        "HistorialTransicionProducto",
        back_populates="producto",
        primaryjoin="Producto.producto_id == HistorialTransicionProducto.producto_id",
        foreign_keys="HistorialTransicionProducto.producto_id",
    )


class HistorialTransicionProducto(Base):
    """Historial inmutable de transiciones del ciclo de vida de un producto.

    Feature 014 (spec D-8, AC-7/AC-12): una fila por cambio **real** de vigencia
    (baja o reactivacion). Cada fila se escribe en la MISMA transaccion que el
    cambio de estado que representa (constitucion.md, seccion 3) y el servicio no
    crea historial en una repeticion idempotente (AC-8). Es la 16.ª entidad de
    dominio (docs/spec/stack.md §2, apartado 014).

    Tabla de negocio por esquema tenant; aqui se modela una sola (contexto logico
    unico, igual que el resto del dominio) y el DDL de instalacion nueva la crea
    en `control` por paridad estructural. No lleva `institucion_id`: su
    aislamiento es el de su esquema, con la misma defensa que
    `historial_transicion_ticket`.
    """

    __tablename__ = "historial_transicion_producto"

    historial_producto_id = Column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    producto_id = Column(Integer, ForeignKey("producto.producto_id"), nullable=False)
    #: Actor autenticado de la transicion.
    usuario_id = Column(Integer, ForeignKey("usuario.usuario_id"), nullable=False)
    fecha_transicion = Column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    #: Estado de vigencia antes y despues de la transicion (AC-7).
    activo_origen = Column(Boolean, nullable=False)
    activo_destino = Column(Boolean, nullable=False)
    #: Motivo libre obligatorio de hasta 500 caracteres (spec D-8). La validacion
    #: de contenido (no vacio/solo espacios) vive en el servicio para respetar el
    #: orden 404 -> idempotencia -> 422 -> 409 (AC-3).
    motivo = Column(String(500), nullable=False)

    producto = relationship(
        "Producto",
        back_populates="historiales_transiciones",
        primaryjoin="HistorialTransicionProducto.producto_id == Producto.producto_id",
        foreign_keys="HistorialTransicionProducto.producto_id",
    )
    usuario = relationship(
        "Usuario",
        primaryjoin="HistorialTransicionProducto.usuario_id == Usuario.usuario_id",
        foreign_keys="HistorialTransicionProducto.usuario_id",
    )


class HistorialTransicionCategoria(Base):
    """Historial inmutable de transiciones del ciclo de vida de una categoria.

    Feature 014 (spec D-8, AC-7/AC-12): tabla hermana de
    `HistorialTransicionProducto`, con FK real a `categoria` en lugar de
    `producto`. Es la 17.ª entidad de dominio (docs/spec/stack.md §2, apartado
    014) y conserva la misma paridad estructural control/tenant y las mismas
    reglas de inmutabilidad y atomicidad.
    """

    __tablename__ = "historial_transicion_categoria"

    historial_categoria_id = Column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    categoria_id = Column(Integer, ForeignKey("categoria.categoria_id"), nullable=False)
    #: Actor autenticado de la transicion.
    usuario_id = Column(Integer, ForeignKey("usuario.usuario_id"), nullable=False)
    fecha_transicion = Column(
        TIMESTAMP, nullable=False, server_default=func.current_timestamp()
    )
    #: Estado de vigencia antes y despues de la transicion (AC-7).
    activo_origen = Column(Boolean, nullable=False)
    activo_destino = Column(Boolean, nullable=False)
    #: Motivo libre obligatorio de hasta 500 caracteres (spec D-8).
    motivo = Column(String(500), nullable=False)

    categoria = relationship(
        "Categoria",
        back_populates="historiales_transiciones",
        primaryjoin="HistorialTransicionCategoria.categoria_id == Categoria.categoria_id",
        foreign_keys="HistorialTransicionCategoria.categoria_id",
    )
    usuario = relationship(
        "Usuario",
        primaryjoin="HistorialTransicionCategoria.usuario_id == Usuario.usuario_id",
        foreign_keys="HistorialTransicionCategoria.usuario_id",
    )
