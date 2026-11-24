"""Application configuration via Pydantic BaseSettings."""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "CAD Serviceability Assessment System"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./cad_serviceability.db"

    # Upload and test data paths
    max_upload_size_mb: int = 500
    upload_dir: Path = Path("uploads")
    test_data_dir: Path = Path("test_data")

    # Tessellation quality (smaller = finer mesh, slower)
    tessellation_linear_deflection: float = 0.5   # mm
    tessellation_angular_deflection: float = 0.1  # radians

    # CORS origins (comma-separated)
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


settings = Settings()
