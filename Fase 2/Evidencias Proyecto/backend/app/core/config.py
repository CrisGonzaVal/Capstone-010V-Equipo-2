from pydantic_settings import BaseSettings, SettingsConfigDict

#: Version objetivo del DDL de tenant (Feature 010, stack §5). Es la constante
#: de despliegue compartida por el codigo que resuelve el tenant y por el
#: procedimiento de migracion: el enrutamiento exige **igualdad exacta** contra
#: este token y se incrementa con cada cambio posterior de DDL/migracion.
VERSION_ESQUEMA_OBJETIVO = "010.1"


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
