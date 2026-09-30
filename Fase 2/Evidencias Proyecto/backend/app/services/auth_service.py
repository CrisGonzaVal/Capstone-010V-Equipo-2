"""Servicio de autenticacion. Stub deliberado.

`stack.md` §2 define este archivo como "valida contrasenas simuladas y emite JWT".
Esa logica es funcionalidad nueva y corresponde a Feature 006
(`endpoints/auth.py` + emision real de token). La autenticacion actual es
decorativa (`AGENTS.md` §7), asi que aqui no hay nada que ejecutar todavia.
"""


def autenticar(correo: str, contrasena: str) -> dict:
    raise NotImplementedError(
        "Emision de JWT no implementada. Corresponde a Feature 006."
    )
