"""asyncpg baglanti havuzu ve .sql migration uygulayici. ORM ve Alembic yok."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

# Migration takip tablosu. Migration'ların kendisinden ÖNCE oluşturulmak zorunda,
# o yüzden burada duruyor ve bir migration dosyası değil.
_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_APPLIED_VERSIONS = "SELECT version FROM schema_migrations"

_RECORD_MIGRATION = "INSERT INTO schema_migrations (version) VALUES ($1)"


class Database:
    """asyncpg havuzunu tutan ince sarmalayıcı."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Havuz açılmadı: connect() çağrılmalı")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            # Sorgu planlarının önbelleklenmesi migration sonrası eski şemayı
            # kullanmaya yol açabiliyor; bu servis için kazancı ihmal edilebilir.
            statement_cache_size=0,
        )
        logger.info("veritabanı havuzu açıldı")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("veritabanı havuzu kapandı")

    async def healthy(self) -> bool:
        """`/health/ready` için: bağlantı gerçekten çalışıyor mu."""
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
            logger.exception("veritabanı sağlık kontrolü başarısız")
            return False

    async def migrate(self) -> None:
        """Uygulanmamış migration'ları sırayla çalıştırır."""
        async with self.pool.acquire() as conn:
            await conn.execute(_CREATE_MIGRATIONS_TABLE)
            applied = {row["version"] for row in await conn.fetch(_APPLIED_VERSIONS)}

            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = path.stem
                if version in applied:
                    continue

                logger.info("migration uygulanıyor: %s", version)
                async with conn.transaction():
                    await conn.execute(path.read_text(encoding="utf-8"))
                    await conn.execute(_RECORD_MIGRATION, version)

        logger.info("migration'lar güncel")

db = Database()
