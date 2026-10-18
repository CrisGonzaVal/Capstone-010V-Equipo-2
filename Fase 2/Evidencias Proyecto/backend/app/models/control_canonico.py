"""Modelo ORM canonico del esquema de control (Feature 012).

La Feature 012 separa el **registro institucional canonico** (que vive solo en
`control`, con estado de ciclo de vida `activo`) y las **capacidades funcionales**
por institucion (`funcion_institucion`) del **espejo tenant** de `institucion`
(limitado a `institucion_id` + `nombre`). Justificacion aprobada en
`docs/spec/stack.md` §"Gestion del ciclo de vida institucional y capacidades
funcionales (Feature 012)"; diseno ORM fijado en
`docs/spec/features/012-gestion-administrativa/diseno-tecnico.md` §3.

Por que un `MetaData` propio (`BaseControl`) y no `Base`: `InstitucionControl`
declara la tabla `institucion` igual que el espejo tenant `Institucion`
(`app/models/institucion.py`), pero SQLAlchemy no admite dos modelos con el mismo
nombre de tabla y `schema=None` dentro de un unico `MetaData`. Un declarativo
separado evita la colision **sin** fijar `schema="control"` explicito (que
romperia la suite SQLite, donde el esquema `control` no existe). Ademas,
`BaseControl.metadata` no participa del `create_all` de los tenants, de modo que
`activo` y `funcion_institucion` **nunca** se materializan en un esquema tenant.
"""

from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, true
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

#: Conjunto cerrado de capacidades funcionales por institucion (D-6/AC-5). Es una
#: lista fija del codigo, no un catalogo configurable: no se crea tabla de
#: catalogo ni se infiere disponibilidad a partir de roles o datos existentes.
CAPACIDADES: frozenset[str] = frozenset(
    {
        "catalogo",
        "inventario",
        "tickets",
        "kanban",
        "dashboard",
        "gestion_organizacional",
    }
)

#: Declarativo propio del contexto de control. Su `metadata` solo contiene el
#: canonico (`institucion`) y el auxiliar de capacidades (`funcion_institucion`).
BaseControl = declarative_base()

#: Literales del `CHECK` de `funcion_institucion.funcion`, derivados de la unica
#: fuente de verdad `CAPACIDADES` (no se duplica la lista).
_LITERALES_FUNCION = ", ".join(f"'{funcion}'" for funcion in sorted(CAPACIDADES))


class InstitucionControl(BaseControl):
    """Registro institucional canonico (solo `control`).

    Es la fuente de verdad del ciclo de vida institucional: `activo` permite
    suspender y reactivar una institucion sin borrar su tenant, sus mapas, datos
    ni historial. El espejo tenant (`Institucion`, dos columnas) nunca recibe
    `activo` (D-1/D-2).
    """

    __tablename__ = "institucion"

    institucion_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    rut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    direccion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: Estado de ciclo de vida institucional. `default` (lado Python) cubre los
    #: INSERT del ORM; `server_default` cubre los INSERT que no nombran la columna
    #: (p. ej. el espejo tenant en SQLite, donde la tabla es un superset).
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )


class FuncionInstitucion(BaseControl):
    """Capacidad funcional habilitada/deshabilitada por institucion (solo `control`).

    Estructura auxiliar con una fila por pareja `(institucion_id, funcion)` (PK
    compuesta), FK local a `institucion.institucion_id` y estado `habilitada`
    explicito. No es entidad de dominio, permiso de usuario ni capacidad de rol;
    el conjunto de identificadores es cerrado (`CAPACIDADES`).
    """

    __tablename__ = "funcion_institucion"
    __table_args__ = (
        CheckConstraint(
            f"funcion IN ({_LITERALES_FUNCION})",
            name="funcion_institucion_funcion_ck",
        ),
    )

    institucion_id: Mapped[str] = mapped_column(
        String(20),
        ForeignKey("institucion.institucion_id"),
        primary_key=True,
    )
    funcion: Mapped[str] = mapped_column(String(50), primary_key=True)
    habilitada: Mapped[bool] = mapped_column(Boolean, nullable=False)
