"""Project paths and settings, read from .env (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    raw_data_path: Path
    processed_dir: Path
    store_db_path: Path
    model_dir: Path


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def get_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        raw_data_path=_resolve(os.getenv("RAW_DATA_PATH", "data/raw/sample_data.csv")),
        processed_dir=_resolve(os.getenv("PROCESSED_DIR", "data/processed")),
        store_db_path=_resolve(os.getenv("STORE_DB_PATH", "data/store/sciplay.sqlite")),
        model_dir=_resolve(os.getenv("MODEL_DIR", "models")),
    )
