"""T2 (Feature 011): asignaciones organizacionales por API — pruebas rojas.

Seam bajo prueba: la **interfaz HTTP del `app` real** (`TestClient`), igual que el
resto de `tests/api/`. Cubre la superficie minima de API que la spec 011 (§2
"Dentro") exige para que el modelo organizacional sea operable, sin CRUD de sedes
(eso es la Feature 012):

  * `GET    /api/v1/organizacion/sedes`
  * `PUT    /api/v1/organizacion/departamentos/{departamento_id}/sede`
  * `PUT    /api/v1/organizacion/usuarios/{usuario_id}/sede`
  * `GET    /api/v1/organizacion/departamentos/{departamento_id}/encargados`
  * `POST   /api/v1/organizacion/departamentos/{departamento_id}/encargados`
  * `DELETE /api/v1/organizacion/departamentos/{departamento_id}/encargados/{usuario_id}`

Trazabilidad AC (spec 011 §5):

  * **AC-1** visibilidad de sede entre tenants via API.
  * **AC-3** identificadores de sede invalidos o ajenos -> 404 sin mutacion.
  * **AC-4** encargados de departamento: varios validos, invalidados con 404/409.
  * **AC-5** administracion de asignaciones por API: 401/403/404/409/422.

Fase ROJA de TDD: ni el router ni el servicio ni los modelos existen todavia
(T3/T7), de modo que cada prueba empieza por `exigir_ruta`/`exigir_operacion` y
falla con un motivo explicito (capacidad ausente), nunca por `ImportError`,
fixtures invalidas ni sintaxis.

Los roles de la matriz se transcriben a mano desde la spec (Administrador
institucional) para no leer la matriz bajo prueba: una prueba que copia su fuente
de verdad no puede contradecirla.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core import permisos
from app.models import Departamento, Rol, Usuario

from ._soporte_sede_011 import (
    OPERACIONES_ORGANIZACION,
    ROLES_ORGANIZACION,
    RUTA_ENCARGADO,
    RUTA_ENCARGADOS,
    RUTA_SEDE_DE_DEPARTAMENTO,
    RUTA_SEDE_DE_USUARIO,
    RUTA_SEDES,
    cliente,
    crear_sede,
    exigir_operacion,
    exigir_ruta,
    leer_sede_de_departamento,
    leer_sede_de_usuario,
    sesion,
)

#: Roles que NO pueden gestionar asignaciones organizacionales (AC-5): el
#: Administrador institucional es el unico. Superadmin no escribe en tenants.
_ROLES_DENEGADOS = ("Bodeguero", "Solicitante", "Superadmin")


# ---------------------------------------------------------------------------
# Helpers locales
# ---------------------------------------------------------------------------


def _crear_departamento(motor, institucion_id: str, nombre: str) -> int:
    with sesion(motor) as db:
        departamento = Departamento(
            nombre_dep=nombre,
            descripcion=f"Departamento {nombre}",
            institucion_id=institucion_id,
        )
        db.add(departamento)
        db.commit()
        db.refresh(departamento)
        return departamento.departamento_id


def _crear_usuario(
    motor, *, departamento_id: int, rol_nombre: str, correo: str
) -> int:
    with sesion(motor) as db:
        rol = (
            db.execute(select(Rol).where(Rol.nombre_rol == rol_nombre))
            .scalars()
            .first()
        )
        if rol is None:
            pytest.fail(f"la fixture no sembro el rol {rol_nombre}")
        usuario = Usuario(
            nombre="Encargable",
            apellido="Sede011",
            correo=correo,
            departamento_id=departamento_id,
            rol_id=rol.rol_id,
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        return usuario.usuario_id


# ---------------------------------------------------------------------------
# AC-5: matriz central y contrato OpenAPI
# ---------------------------------------------------------------------------


def test_operaciones_de_organizacion_se_declaran_solo_para_administrador():
    """AC-5: las seis operaciones existen y solo las concede el Administrador.

    Tambien comprueba que la Feature 011 **no relaja** ninguna operacion previa:
    la matriz anterior (22 operaciones de la Feature 010) sigue igual.
    """
    for metodo, ruta in OPERACIONES_ORGANIZACION:
        exigir_operacion(metodo, ruta)
        assert set(permisos.MATRIZ_PERMISOS[(metodo, ruta)]) == ROLES_ORGANIZACION, (
            metodo,
            ruta,
        )

    previas = {
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/inventario/existencias"),
        ("POST", "/api/v1/tickets/"),
        ("POST", "/api/v1/tickets/{ticket_id}/despacho"),
        ("GET", "/api/v1/dashboard/"),
        ("POST", "/api/v1/control/instituciones/"),
    }
    assert previas <= set(permisos.MATRIZ_PERMISOS), "la 011 no retira operaciones previas"
    assert permisos.MATRIZ_PERMISOS[("POST", "/api/v1/control/instituciones/")] == {
        "Superadmin"
    }, "el alta de institucion sigue siendo solo Superadmin"


def test_openapi_publica_las_operaciones_de_organizacion():
    """AC-5: las seis operaciones estan publicadas en el contrato."""
    for metodo, ruta in OPERACIONES_ORGANIZACION:
        exigir_ruta(ruta, metodo)


# ---------------------------------------------------------------------------
# AC-1: visibilidad acotada a la institucion
# ---------------------------------------------------------------------------


def test_listar_sedes_devuelve_solo_la_institucion_del_administrador(
    motor, dos_instituciones
):
    """AC-1/AC-8: una sede de otra institucion no aparece en la lista del actor."""
    exigir_ruta(RUTA_SEDES, "GET")

    sede_propia = crear_sede(
        motor, institucion_id=dos_instituciones["inst_propia"], nombre="Sede Propia"
    )
    sede_ajena = crear_sede(
        motor, institucion_id=dos_instituciones["inst_ajena"], nombre="Sede Ajena"
    )

    with cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.get(RUTA_SEDES)

    assert respuesta.status_code == 200, respuesta.text
    ids = {fila["sede_id"] for fila in respuesta.json()}
    assert sede_propia in ids
    assert sede_ajena not in ids, "la sede de otro tenant no debe ser visible"
    for fila in respuesta.json():
        assert fila["institucion_id"] == dos_instituciones["inst_propia"]


# ---------------------------------------------------------------------------
# AC-5/AC-6/AC-7: asignaciones de sede
# ---------------------------------------------------------------------------


def test_asignar_sede_a_departamento_persiste_y_responde(motor, datos_base):
    """AC-5/AC-6: el Administrador fija la sede del departamento."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    sede_id = crear_sede(motor, institucion_id=datos_base["institucion_id"])

    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(
                departamento_id=datos_base["departamento_id"]
            ),
            json={"sede_id": sede_id},
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["sede_id"] == sede_id
    assert respuesta.json()["departamento_id"] == datos_base["departamento_id"]
    assert (
        leer_sede_de_departamento(motor, datos_base["departamento_id"]) == sede_id
    ), "la asignacion debe quedar persistida"


def test_asignar_sede_a_bodeguero_persiste_y_responde(motor, dos_instituciones):
    """AC-5/AC-7: el Administrador fija la sede del Bodeguero."""
    exigir_ruta(RUTA_SEDE_DE_USUARIO, "PUT")
    sede_id = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    bodeguero_id = dos_instituciones["usuarios_inst01"]["Bodeguero"]

    with cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_USUARIO.format(usuario_id=bodeguero_id),
            json={"sede_id": sede_id},
        )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["usuario_id"] == bodeguero_id
    assert respuesta.json()["sede_id"] == sede_id
    assert leer_sede_de_usuario(motor, bodeguero_id) == sede_id


def test_asignacion_sin_sesion_responde_401(motor, datos_base):
    """AC-5: sin sesion, la operacion responde 401 (matriz central)."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    with cliente(motor) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(
                departamento_id=datos_base["departamento_id"]
            ),
            json={"sede_id": 1},
        )
    assert respuesta.status_code == 401, respuesta.text


@pytest.mark.parametrize("rol", _ROLES_DENEGADOS)
def test_asignacion_con_rol_no_autorizado_responde_403(motor, datos_base, rol):
    """AC-5: solo el Administrador institucional gestiona asignaciones."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    with cliente(motor, rol, departamento_id=datos_base["departamento_id"]) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(
                departamento_id=datos_base["departamento_id"]
            ),
            json={"sede_id": 1},
        )
    assert respuesta.status_code == 403, (rol, respuesta.text)


def test_asignacion_en_departamento_de_otra_institucion_responde_404(
    motor, dos_instituciones
):
    """AC-1/AC-5: un departamento ajeno se oculta con 404 y no se muta."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    sede_propia = crear_sede(motor, institucion_id=dos_instituciones["inst_propia"])
    ajeno = dos_instituciones["departamento_ajeno_id"]

    with cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(departamento_id=ajeno),
            json={"sede_id": sede_propia},
        )

    assert respuesta.status_code == 404, respuesta.text
    assert leer_sede_de_departamento(motor, ajeno) is None, "no debe mutar el ajeno"


@pytest.mark.parametrize("origen", ["inexistente", "ajena"])
def test_asignacion_con_sede_ajena_o_inexistente_responde_404(
    motor, dos_instituciones, origen
):
    """AC-3: un `sede_id` inexistente o de otro tenant responde 404 sin efecto."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    departamento_id = dos_instituciones["departamento_id"]
    if origen == "inexistente":
        sede_id = 999_999
    else:
        sede_id = crear_sede(motor, institucion_id=dos_instituciones["inst_ajena"])

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(departamento_id=departamento_id),
            json={"sede_id": sede_id},
        )

    assert respuesta.status_code == 404, (origen, respuesta.text)
    assert leer_sede_de_departamento(motor, departamento_id) is None


def test_asignacion_con_payload_invalido_responde_422(motor, datos_base):
    """AC-5: un cuerpo sin `sede_id` (o con tipo invalido) es 422, no 500."""
    exigir_ruta(RUTA_SEDE_DE_DEPARTAMENTO, "PUT")
    with cliente(
        motor, "Administrador", departamento_id=datos_base["departamento_id"]
    ) as cliente_http:
        sin_campo = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(
                departamento_id=datos_base["departamento_id"]
            ),
            json={},
        )
        tipo_invalido = cliente_http.put(
            RUTA_SEDE_DE_DEPARTAMENTO.format(
                departamento_id=datos_base["departamento_id"]
            ),
            json={"sede_id": "no-es-un-id"},
        )
    assert sin_campo.status_code == 422, sin_campo.text
    assert tipo_invalido.status_code == 422, tipo_invalido.text


# ---------------------------------------------------------------------------
# AC-4: encargados de departamento (relacion N:N, rol Solicitante)
# ---------------------------------------------------------------------------


def test_encargados_multiples_del_mismo_departamento(motor, dos_instituciones):
    """AC-4: un departamento admite varios encargados Solicitantes."""
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    exigir_ruta(RUTA_ENCARGADOS, "GET")
    departamento_id = dos_instituciones["departamento_id"]
    solicitante_uno = dos_instituciones["usuarios_inst01"]["Solicitante"]
    solicitante_dos = _crear_usuario(
        motor,
        departamento_id=departamento_id,
        rol_nombre="Solicitante",
        correo="encargado.dos@compustock.cl",
    )

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        alta_uno = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": solicitante_uno},
        )
        alta_dos = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": solicitante_dos},
        )
        listado = cliente_http.get(RUTA_ENCARGADOS.format(departamento_id=departamento_id))

    assert alta_uno.status_code == 201, alta_uno.text
    assert alta_dos.status_code == 201, alta_dos.text
    assert listado.status_code == 200, listado.text
    ids = {fila["usuario_id"] for fila in listado.json()}
    assert ids == {solicitante_uno, solicitante_dos}, (
        "varios encargados conviven; ninguno reemplaza a otro"
    )


@pytest.mark.parametrize("rol", ["Bodeguero", "Administrador"])
def test_encargado_con_rol_distinto_responde_409(motor, dos_instituciones, rol):
    """AC-4: solo un Solicitante puede ser encargado de departamento.

    El encargado no es el Bodeguero/Encargado de Suministros (spec D-4); un
    usuario de otro rol es una asociacion incompatible -> 409.
    """
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    departamento_id = dos_instituciones["departamento_id"]
    candidato = dos_instituciones["usuarios_inst01"][rol]

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": candidato},
        )

    assert respuesta.status_code == 409, (rol, respuesta.text)


def test_encargado_de_otro_departamento_responde_409(motor, dos_instituciones):
    """AC-4: un Solicitante de otro departamento de la misma institucion -> 409."""
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    departamento_id = dos_instituciones["departamento_id"]
    otro_departamento = _crear_departamento(
        motor, dos_instituciones["inst_propia"], "Departamento Ajeno"
    )
    solicitante_ajeno = _crear_usuario(
        motor,
        departamento_id=otro_departamento,
        rol_nombre="Solicitante",
        correo="solicitante.otro.dep@compustock.cl",
    )

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": solicitante_ajeno},
        )

    assert respuesta.status_code == 409, respuesta.text


def test_encargado_de_otra_institucion_responde_404(motor, dos_instituciones):
    """AC-4: un usuario de otro tenant se oculta con 404 (identificador ajeno)."""
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    departamento_id = dos_instituciones["departamento_id"]
    ajeno = dos_instituciones["usuarios_inst02"]["Solicitante"]

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": ajeno},
        )

    assert respuesta.status_code == 404, respuesta.text


def test_encargado_inexistente_responde_404(motor, dos_instituciones):
    """AC-4: un usuario inexistente responde 404 nombrado o no, sin asociacion."""
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    departamento_id = dos_instituciones["departamento_id"]

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": 999_999},
        )

    assert respuesta.status_code == 404, respuesta.text


def test_encargado_duplicado_responde_409(motor, dos_instituciones):
    """AC-4: repetir la misma asociacion es un conflicto, no un duplicado mudo."""
    exigir_ruta(RUTA_ENCARGADOS, "POST")
    departamento_id = dos_instituciones["departamento_id"]
    solicitante = dos_instituciones["usuarios_inst01"]["Solicitante"]

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        primera = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": solicitante},
        )
        repetida = cliente_http.post(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id),
            json={"usuario_id": solicitante},
        )

    assert primera.status_code == 201, primera.text
    assert repetida.status_code == 409, repetida.text


def test_retirar_encargado_deja_de_aparecer(motor, dos_instituciones):
    """AC-5: el retiro afecta solo a la pareja departamento-usuario."""
    exigir_ruta(RUTA_ENCARGADO, "DELETE")
    exigir_ruta(RUTA_ENCARGADOS, "GET")
    departamento_id = dos_instituciones["departamento_id"]
    primero = dos_instituciones["usuarios_inst01"]["Solicitante"]
    segundo = _crear_usuario(
        motor,
        departamento_id=departamento_id,
        rol_nombre="Solicitante",
        correo="encargado.tres@compustock.cl",
    )

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        for usuario_id in (primero, segundo):
            cliente_http.post(
                RUTA_ENCARGADOS.format(departamento_id=departamento_id),
                json={"usuario_id": usuario_id},
            )
        retiro = cliente_http.delete(
            RUTA_ENCARGADO.format(departamento_id=departamento_id, usuario_id=primero)
        )
        listado = cliente_http.get(
            RUTA_ENCARGADOS.format(departamento_id=departamento_id)
        )

    assert retiro.status_code == 204, retiro.text
    assert {fila["usuario_id"] for fila in listado.json()} == {segundo}, (
        "el retiro no debe alcanzar a los demas encargados"
    )


def test_retirar_encargado_inexistente_responde_404(motor, dos_instituciones):
    """AC-5: retirar una asociacion que no existe responde 404."""
    exigir_ruta(RUTA_ENCARGADO, "DELETE")
    departamento_id = dos_instituciones["departamento_id"]

    with cliente(
        motor, "Administrador", departamento_id=departamento_id
    ) as cliente_http:
        respuesta = cliente_http.delete(
            RUTA_ENCARGADO.format(
                departamento_id=departamento_id,
                usuario_id=dos_instituciones["usuarios_inst01"]["Solicitante"],
            )
        )

    assert respuesta.status_code == 404, respuesta.text


def test_listar_encargados_de_departamento_ajeno_responde_404(
    motor, dos_instituciones
):
    """AC-1/AC-5: la lectura de encargados tambien respeta el ambito."""
    exigir_ruta(RUTA_ENCARGADOS, "GET")
    with cliente(
        motor, "Administrador", departamento_id=dos_instituciones["departamento_id"]
    ) as cliente_http:
        respuesta = cliente_http.get(
            RUTA_ENCARGADOS.format(
                departamento_id=dos_instituciones["departamento_ajeno_id"]
            )
        )

    assert respuesta.status_code == 404, respuesta.text
