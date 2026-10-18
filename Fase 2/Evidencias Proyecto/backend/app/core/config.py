from pydantic_settings import BaseSettings, SettingsConfigDict

#: Version objetivo del DDL de tenant (Feature 012, stack §5). Es la constante
#: de despliegue compartida por el codigo que resuelve el tenant y por el
#: procedimiento de migracion: el enrutamiento exige **igualdad exacta** contra
#: este token y se incrementa con cada cambio posterior de DDL/migracion. La
#: Feature 011 subio el objetivo de `010.1` a `011.1`; la Feature 012 agrega el
#: estado canonico `control.institucion.activo` y las capacidades por institucion
#: (`control.funcion_institucion`) y el estado logico de sede/departamento, asi
#: que el objetivo sube de `011.1` a `012.1` (spec 012, AC-1/AC-2/AC-5/AC-13).
VERSION_ESQUEMA_OBJETIVO = "012.1"


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
