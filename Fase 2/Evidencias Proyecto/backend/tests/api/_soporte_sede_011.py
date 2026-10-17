"""Soporte compartido de las pruebas rojas de la Feature 011 (modelo organizacional).

Los modulos de T2 comparten cuatro necesidades:

1. **Leer un modelo que todavia no existe.** T3 crea `Sede`, `StockSede` y
   `DepartamentoEncargado`; hasta entonces `modelo()` falla con `pytest.fail` y un
   mensaje que nombra la tarea. La fase roja debe fallar por la capacidad ausente,
   nunca por `ImportError` ni por sintaxis.
2. **Comprobar que la operacion ya esta publicada.** Una prueba que espera un
   `404` pasaria espuriamente si la ruta no existe todavia, asi que `exigir_ruta`
   y `exigir_operacion` fallan explicitamente mientras la Feature 011 no cablee la
   API (T7).
3. **Construir el mundo**: sede, stock por sede, asignacion departamento-sede,
   asignacion Bodeguero-sede y catalogo de estados del flujo.
4. **Observarlo** sin pasar por la API cuando la lectura aun no existe (auditoria,
   sede de un ticket, saldo de una sede).

El contrato de rutas, campos y estados que estas pruebas fijan es el del `plan.md`
§"Servicios, API y autorizacion" de la 011: el plan delega en la implementacion
los nombres concretos, y T2 es la tarea que los fija como contrato observable.
"""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import dependencies
from app.core import permisos
from app.main import app
from app.models import Departamento, EstadoTicket, MovimientoInventario, Ticket, Usuario
from app.services.auth_service import IdentidadAutenticada

# ---------------------------------------------------------------------------
# Contrato de rutas (plan.md §"Servicios, API y permisos" de la Feature 011)
# ---------------------------------------------------------------------------

#: Consulta de sedes del ambito del actor.
RUTA_SEDES = "/api/v1/organizacion/sedes"
#: Asignacion de sede a un departamento (Administrador institucional).
RUTA_SEDE_DE_DEPARTAMENTO = (
    "/api/v1/organizacion/departamentos/{departamento_id}/sede"
)
#: Asignacion de sede a un Bodeguero (Administrador institucional).
RUTA_SEDE_DE_USUARIO = "/api/v1/organizacion/usuarios/{usuario_id}/sede"
#: Asociacion y listado de encargados de departamento (Administrador institucional).
RUTA_ENCARGADOS = "/api/v1/organizacion/departamentos/{departamento_id}/encargados"
RUTA_ENCARGADO = (
    "/api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}"
)

#: Operaciones que la Feature 011 aporta a la matriz central: solo Administrador
#: institucional (spec D-4/D-5; Superadmin no escribe en tenants).
OPERACIONES_ORGANIZACION: tuple[tuple[str, str], ...] = (
    ("GET", RUTA_SEDES),
    ("PUT", RUTA_SEDE_DE_DEPARTAMENTO),
    ("PUT", RUTA_SEDE_DE_USUARIO),
    ("GET", RUTA_ENCARGADOS),
    ("POST", RUTA_ENCARGADOS),
    ("DELETE", RUTA_ENCARGADO),
)
ROLES_ORGANIZACION: frozenset[str] = frozenset({"Administrador"})

#: Rutas de negocio existentes cuyo contrato cambia con la Feature 011.
RUTA_EXISTENCIAS = "/api/v1/inventario/existencias"
RUTA_MOVIMIENTOS = "/api/v1/inventario/movimientos"
RUTA_TICKETS = "/api/v1/tickets/"
RUTA_DASHBOARD = "/api/v1/dashboard/"

#: Version objetivo del DDL tras la Feature 011 (spec AC-12, plan T6).
VERSION_OBJETIVO_011 = "011.1"

#: Nombre de la sede inicial que recibe un tenant recien aprovisionado (spec D-5).
NOMBRE_SEDE_CENTRAL = "Sede Central"

#: Centinela para distinguir "sin autenticar" de "rol ausente" (`None`).
SIN_AUTENTICAR = object()

_CORREO_SONDA = "sonda.sede011@compustock.cl"


# ---------------------------------------------------------------------------
# Guardas de capacidad (fase ROJA del TDD)
# ---------------------------------------------------------------------------


def modelo(nombre: str) -> Any:
    """Modelo ORM por nombre, o `pytest.fail` si la Feature 011 aun no lo creo."""
    modulos = importlib.import_module("app.models")
    encontrado = getattr(modulos, nombre, None)
    if encontrado is None:
        pytest.fail(
            f"capacidad ausente (T3): `app.models.{nombre}` no existe todavia; "
            "la Feature 011 lo crea en T3 y hasta entonces esta prueba esta en rojo."
        )
    return encontrado


def exigir_ruta(ruta: str, metodo: str = "GET") -> None:
    """Falla si la operacion aun no esta publicada en el contrato OpenAPI (T7).

    Sin esta guarda, una prueba que espera `404` pasaria por el motivo equivocado
    (ruta ausente en vez de recurso oculto).
    """
    rutas = app.openapi().get("paths", {})
    operaciones = rutas.get(ruta, {})
    if metodo.lower() not in operaciones:
        pytest.fail(
            f"capacidad ausente (T7): {metodo.upper()} {ruta} no esta publicada en "
            "/openapi.json; la Feature 011 la cablea en T7."
        )


def exigir_operacion(metodo: str, ruta: str) -> None:
    """Falla si la operacion aun no esta declarada en la matriz central (T7)."""
    if (metodo.upper(), ruta) not in permisos.MATRIZ_PERMISOS:
        pytest.fail(
            f"capacidad ausente (T7): MATRIZ_PERMISOS no declara "
            f"{(metodo.upper(), ruta)}; la Feature 011 la agrega en T7."
        )


def existe_columna(entidad: Any, columna: str) -> bool:
    """`True` si la tabla del modelo declara `columna`."""
    return columna in set(entidad.__table__.columns.keys())


def _exigir_campos_schema(schema: Any, campos: set[str], destino: str, tarea: str) -> None:
    """Falla si un DTO aun no declara los campos del contrato de la 011."""
    faltantes = campos - set(getattr(schema, "model_fields", {}))
    if faltantes:
        pytest.fail(
            f"capacidad ausente ({tarea}): `{destino}` no declara {sorted(faltantes)}; "
            "el contrato de la Feature 011 aun no esta implementado."
        )


def exigir_contrato_existencias_por_sede() -> None:
    """Falla si las existencias aun exponen la sede como departamento (T8)."""
    from app.schemas.inventario_schema import SedeExistenciaRespuesta

    _exigir_campos_schema(
        SedeExistenciaRespuesta,
        {"sede_id", "sede_nombre", "stock_actual"},
        "SedeExistenciaRespuesta",
        "T8",
    )


def exigir_contrato_movimiento_por_sede() -> None:
    """Falla si la escritura de stock aun exige `inventario_id` (T8)."""
    from app.schemas.inventario_schema import MovimientoCrear

    _exigir_campos_schema(
        MovimientoCrear, {"stock_sede_id"}, "MovimientoCrear", "T8"
    )


def exigir_contrato_ticket_con_sede() -> None:
    """Falla si la respuesta de ticket no expone la sede almacenada (T9)."""
    from app.schemas.ticket_schema import TicketRespuesta

    _exigir_campos_schema(TicketRespuesta, {"sede_id"}, "TicketRespuesta", "T9")


def exigir_contrato_alerta_por_sede() -> None:
    """Falla si la alerta del dashboard no atribuye la sede (T10)."""
    from app.schemas.dashboard_schema import AlertaStockRespuesta

    _exigir_campos_schema(AlertaStockRespuesta, {"sede_id"}, "AlertaStockRespuesta", "T10")


def exigir_columna(entidad: Any, columna: str, entidad_nombre: str) -> None:
    """Falla si falta una columna del modelo (capacidad ausente de T3)."""
    if not existe_columna(entidad, columna):
        pytest.fail(
            f"capacidad ausente (T3): `{entidad_nombre}.{columna}` no existe "
            "todavia; la Feature 011 lo agrega en T3."
        )


# ---------------------------------------------------------------------------
# Identidad y cliente HTTP
# ---------------------------------------------------------------------------


def identidad(
    rol: str | None,
    departamento_id: int | None,
    usuario_id: int = 9999,
    sede_id: int | None = None,
    correo: str = _CORREO_SONDA,
) -> IdentidadAutenticada:
    """Identidad autenticada de prueba, sin persistir.

    `sede_id` puebla `usuario.sede_id` cuando el modelo ya la declara; si no, se
    asigna como atributo suelto (el ORM no lo persiste y la ausencia de la columna
    la detecta el ayudante que la lee).
    """
    usuario = Usuario(
        usuario_id=usuario_id,
        nombre="Sonda",
        apellido="Sede011",
        correo=correo,
        departamento_id=departamento_id,
        rol_id=1,
    )
    if rol is not None:
        usuario.rol = _rol_de_prueba(rol)
    if sede_id is not None:
        setattr(usuario, "sede_id", sede_id)
    return IdentidadAutenticada(usuario=usuario, sub="sub-sede-011")


def _rol_de_prueba(nombre_rol: str) -> Any:
    """`Rol` suelto con el nombre pedido (no se persiste: solo autoriza)."""
    from app.models import Rol

    return Rol(nombre_rol=nombre_rol)


@contextmanager
def cliente(
    motor,
    rol: Any = SIN_AUTENTICAR,
    *,
    departamento_id: int | None = None,
    usuario_id: int = 9999,
    sede_id: int | None = None,
    correo: str = _CORREO_SONDA,
):
    """`TestClient` del `app` real con `get_db` en el motor de prueba.

    Con `rol=SIN_AUTENTICAR` no se overridea `get_current_user`, de modo que la
    sesion ausente ejerce el 401 real. `raise_server_exceptions=False` permite
    observar un 500 como 500 en vez de una excepcion relanzada.
    """
    Fabrica = sessionmaker(autocommit=False, autoflush=False, bind=motor)

    def _db_de_prueba():
        db = Fabrica()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[dependencies.get_db] = _db_de_prueba
    if rol is not SIN_AUTENTICAR:
        app.dependency_overrides[dependencies.get_current_user] = (
            lambda: identidad(rol, departamento_id, usuario_id, sede_id, correo)
        )
    try:
        with TestClient(app, raise_server_exceptions=False) as cliente_http:
            yield cliente_http
    finally:
        app.dependency_overrides.clear()


@contextmanager
def sesion(motor) -> Session:
    """Sesion directa contra el motor de prueba (observacion de lo persistido)."""
    db = sessionmaker(bind=motor)()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Construccion del mundo
# ---------------------------------------------------------------------------


def _valores_validos(entidad: Any, valores: dict) -> dict:
    """Filtra `valores` a las columnas que la entidad declara."""
    columnas = set(entidad.__table__.columns.keys())
    return {clave: valor for clave, valor in valores.items() if clave in columnas}


def crear_sede(
    motor, *, institucion_id: str, nombre: str = "Sede QA", direccion: str | None = None
) -> int:
    """Crea una sede de la institucion dada y devuelve su `sede_id`."""
    Sede = modelo("Sede")
    for columna in ("sede_id", "nombre", "institucion_id"):
        exigir_columna(Sede, columna, "sede")
    fila = Sede(
        **_valores_validos(
            Sede,
            {"nombre": nombre, "institucion_id": institucion_id, "direccion": direccion},
        )
    )
    with sesion(motor) as db:
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.sede_id


def crear_stock_sede(
    motor,
    *,
    sede_id: int,
    producto_id: int,
    stock_actual: int,
    institucion_id: str,
) -> int:
    """Crea la fila de existencias de un producto en una sede."""
    StockSede = modelo("StockSede")
    for columna in ("stock_sede_id", "sede_id", "producto_id", "stock_actual"):
        exigir_columna(StockSede, columna, "stock_sede")
    fila = StockSede(
        **_valores_validos(
            StockSede,
            {
                "sede_id": sede_id,
                "producto_id": producto_id,
                "stock_actual": stock_actual,
                "institucion_id": institucion_id,
            },
        )
    )
    with sesion(motor) as db:
        db.add(fila)
        db.commit()
        db.refresh(fila)
        return fila.stock_sede_id


def asignar_sede_a_departamento(motor, departamento_id: int, sede_id: int | None) -> None:
    """Asigna (o limpia, con `None`) la sede de un departamento."""
    exigir_columna(Departamento, "sede_id", "departamento")
    with sesion(motor) as db:
        departamento = db.get(Departamento, departamento_id)
        if departamento is None:
            pytest.fail(f"departamento {departamento_id} inexistente en la fixture")
        departamento.sede_id = sede_id
        db.commit()


def asignar_sede_a_usuario(motor, usuario_id: int, sede_id: int | None) -> None:
    """Asigna (o limpia, con `None`) la sede de un Bodeguero."""
    exigir_columna(Usuario, "sede_id", "usuario")
    with sesion(motor) as db:
        usuario = db.get(Usuario, usuario_id)
        if usuario is None:
            pytest.fail(f"usuario {usuario_id} inexistente en la fixture")
        usuario.sede_id = sede_id
        db.commit()


def asegurar_sede_de_departamento(
    motor, datos_base, *, nombre: str = "Sede Base", stocks=None
) -> dict:
    """Garantiza que el departamento de `datos_base` tenga sede (Feature 011).

    Crea una sede de la institucion de `datos_base`, la asigna a su departamento y,
    opcionalmente, siembra existencias por sede (`stocks`: `{producto_id: cantidad}`).
    Es la precondicion que el alta de ticket exige desde T9 (spec D-5/AC-9): los
    tests previos que crean tickets o despachan deben declararla.

    Devuelve `{"sede_id": ..., "stock_sede_ids": {producto_id: stock_sede_id}}`.
    """
    sede_id = crear_sede(
        motor, institucion_id=datos_base["institucion_id"], nombre=nombre
    )
    asignar_sede_a_departamento(motor, datos_base["departamento_id"], sede_id)
    stock_sede_ids = {
        producto_id: crear_stock_sede(
            motor,
            sede_id=sede_id,
            producto_id=producto_id,
            stock_actual=cantidad,
            institucion_id=datos_base["institucion_id"],
        )
        for producto_id, cantidad in (stocks or {}).items()
    }
    return {"sede_id": sede_id, "stock_sede_ids": stock_sede_ids}



def asociar_encargado_en_bd(motor, departamento_id: int, usuario_id: int) -> None:
    """Inserta la asociacion departamento-encargado directamente en la tabla puente."""
    DepartamentoEncargado = modelo("DepartamentoEncargado")
    fila = DepartamentoEncargado(
        **_valores_validos(
            DepartamentoEncargado,
            {"departamento_id": departamento_id, "usuario_id": usuario_id},
        )
    )
    with sesion(motor) as db:
        db.add(fila)
        db.commit()


def instalar_catalogo_estados(motor, nombres) -> dict[str, int]:
    """Reemplaza el catalogo de estados por `nombres`, en ese orden de ids.

    Es el mismo patron de `test_despacho_transaccional.py`: el orden de insercion
    es el del flujo (`estado_id` ascendente), que es como lo consumen las reglas de
    despacho.
    """
    with sesion(motor) as db:
        db.query(EstadoTicket).delete()
        db.flush()
        ids = {}
        for nombre in nombres:
            estado = EstadoTicket(nombre=nombre, descripcion=f"Estado {nombre}")
            db.add(estado)
            db.flush()
            ids[nombre] = estado.estado_id
        db.commit()
        return ids


# ---------------------------------------------------------------------------
# Observacion de lo persistido
# ---------------------------------------------------------------------------


def leer_sede_de_departamento(motor, departamento_id: int) -> int | None:
    exigir_columna(Departamento, "sede_id", "departamento")
    with sesion(motor) as db:
        departamento = db.get(Departamento, departamento_id)
        return None if departamento is None else departamento.sede_id


def leer_sede_de_usuario(motor, usuario_id: int) -> int | None:
    exigir_columna(Usuario, "sede_id", "usuario")
    with sesion(motor) as db:
        usuario = db.get(Usuario, usuario_id)
        return None if usuario is None else usuario.sede_id


def leer_sede_de_ticket(motor, ticket_id: int) -> int | None:
    exigir_columna(Ticket, "sede_id", "ticket")
    with sesion(motor) as db:
        ticket = db.get(Ticket, ticket_id)
        return None if ticket is None else ticket.sede_id


def leer_stock_sede(motor, sede_id: int, producto_id: int) -> int | None:
    """Saldo vigente de un producto en una sede, o `None` si no hay fila."""
    StockSede = modelo("StockSede")
    with sesion(motor) as db:
        fila = db.execute(
            select(StockSede).where(
                StockSede.sede_id == sede_id,
                StockSede.producto_id == producto_id,
            )
        ).scalar_one_or_none()
        return None if fila is None else fila.stock_actual


def leer_estado_de_ticket(motor, ticket_id: int) -> int | None:
    with sesion(motor) as db:
        ticket = db.get(Ticket, ticket_id)
        return None if ticket is None else ticket.estado_id


def contar_en(motor, modelo_o_nombre: Any, **filtros) -> int:
    """Cuenta filas de un modelo en el motor de prueba."""
    entidad = (
        modelo(modelo_o_nombre) if isinstance(modelo_o_nombre, str) else modelo_o_nombre
    )
    consulta = select(func.count()).select_from(entidad)
    for columna, valor in filtros.items():
        consulta = consulta.where(getattr(entidad, columna) == valor)
    with sesion(motor) as db:
        return db.execute(consulta).scalar_one()


def contar_movimientos(motor, **filtros) -> int:
    """Cuenta filas de auditoria, con filtros opcionales por columna."""
    consulta = select(func.count()).select_from(MovimientoInventario)
    for columna, valor in filtros.items():
        consulta = consulta.where(getattr(MovimientoInventario, columna) == valor)
    with sesion(motor) as db:
        return db.execute(consulta).scalar_one()


def movimientos_con_stock_sede(motor) -> list[MovimientoInventario]:
    """Movimientos que referencian stock por sede (referencia nueva de la 011)."""
    exigir_columna(MovimientoInventario, "stock_sede_id", "movimiento_inventario")
    with sesion(motor) as db:
        return list(
            db.execute(
                select(MovimientoInventario).where(
                    MovimientoInventario.stock_sede_id.is_not(None)
                )
            )
            .scalars()
            .all()
        )


def producto_de_existencias(cuerpo: list[dict], producto_id: int) -> dict:
    """Localiza el producto pedido en la respuesta de `GET /inventario/existencias`."""
    for fila in cuerpo:
        if fila["producto_id"] == producto_id:
            return fila
    pytest.fail(f"el producto {producto_id} no aparece en las existencias")
