from pydantic_settings import BaseSettings, SettingsConfigDict

#: Version objetivo del DDL de tenant (stack §5). Es la constante
#: de despliegue compartida por el codigo que resuelve el tenant y por la
#: instalacion limpia: el enrutamiento exige **igualdad exacta** contra
#: este token y se incrementa con cada cambio posterior de DDL. La
#: Feature 011 subio el objetivo de `010.1` a `011.1`; la Feature 012 agrego el
#: estado canonico `control.institucion.activo` y las capacidades por institucion
#: (`control.funcion_institucion`) y el estado logico de sede/departamento, asi
#: que el objetivo subio de `011.1` a `012.1`; la Feature 013 agrega el estado
#: `Anulado` al catalogo replicado y la tabla `historial_transicion_ticket` en
#: control y en cada tenant, de modo que el objetivo sube de `012.1` a `013.1`
#: (spec 013, AC-20/AC-21). La Feature 014 agrega el estado reversible
#: `producto.activo`/`categoria.activo` y los dos historiales de transicion del
#: catalogo (`historial_transicion_producto`/`historial_transicion_categoria`)
#: en control y en cada tenant, de modo que el objetivo sube de `013.1` a
#: `014.1` (spec 014, AC-13/AC-14).
VERSION_ESQUEMA_OBJETIVO = "014.1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    DB_NAME: str = "apt_erp"
    CLERK_PUBLISHABLE_KEY: str = ""
    CLERK_SECRET_KEY: str = ""
    CLERK_ISSUER: str = ""

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"


settings = Settings()
