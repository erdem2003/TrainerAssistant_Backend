"""outbox tablosunu tarayip event'leri isleyen arka plan sureci."""

from __future__ import annotations

import asyncio
import logging
from email.utils import parseaddr

from app.config import settings
from app.correlation import configure_logging
from app.db import db
from app.repo import outbox
from app.worker import fanout, mailer

logger = logging.getLogger(__name__)


async def process_once() -> int:
    """Bir tur: hazır satırları al, gönder, işaretle."""
    sent = 0
    async with db.pool.acquire() as conn:
        async with conn.transaction():
            rows = await outbox.claim_batch(
                conn, settings.outbox_batch_size, settings.outbox_max_attempts
            )

            for row in rows:
                # SIRA ÖNEMLİ: önce diğer servislere haber, sonra e-posta.
                try:
                    await asyncio.to_thread(
                        fanout.dispatch, str(row.id), row.event_type, row.payload
                    )
                except fanout.FanoutFailed as exc:
                    logger.warning("fanout başarısız id=%s: %s", row.id, exc)
                    await outbox.mark_failed(conn, row.id, f"fanout: {exc}")
                    continue

                try:
                    await mailer.deliver(row.event_type, row.payload)
                except mailer.UnknownEventType:
                    # Yeniden denemek düzeltmez; tavana kadar boşuna denenmesin.
                    logger.error("bilinmeyen event türü: %s", row.event_type)
                    await outbox.mark_failed(conn, row.id, "bilinmeyen event türü")
                    continue
                except Exception as exc:
                    logger.warning("e-posta gönderilemedi id=%s: %s", row.id, exc)
                    await outbox.mark_failed(conn, row.id, str(exc))
                    continue

                await outbox.mark_published(conn, row.id)
                sent += 1

    return sent


def _warn_if_misconfigured() -> None:
    """SMTP kimlik bilgisi eksikse AÇIKÇA uyar."""
    if settings.smtp_use_tls and not (settings.smtp_username and settings.smtp_password):
        logger.error(
            "SMTP_USERNAME / SMTP_PASSWORD BOS — mail gonderilemeyecek. "
            ".env dosyasini doldurun (Gmail icin uygulama sifresi gerekir)."
        )
    if "BURAYA" in (settings.smtp_username or "") or "BURAYA" in (settings.smtp_password or ""):
        logger.error(
            "SMTP ayarlari hala ORNEK DEGERLERDE — .env dosyasindaki "
            "BURAYA_... yer tutucularini gercek degerlerle degistirin."
        )

    # Gmail, From adresinin kimlik dogrulanan hesap (ya da dogrulanmis bir
    # "Send mail as" takma adi) olmasini SART kosar. Uymayan mesaji SMTP
    _, from_address = parseaddr(settings.mail_from)
    if settings.smtp_username and from_address.lower() != settings.smtp_username.lower():
        logger.warning(
            "MAIL_FROM (%s) ile SMTP_USERNAME (%s) AYNI DEGIL. Gmail bu "
            "mesajlari spam sayip reddedebilir; ikisini esitleyin.",
            from_address,
            settings.smtp_username,
        )


async def run() -> None:
    configure_logging(settings.log_level)
    _warn_if_misconfigured()
    await db.connect()
    logger.info("outbox worker başladı (SMTP: %s:%s, TLS: %s)",
                settings.smtp_host, settings.smtp_port, settings.smtp_use_tls)
    try:
        while True:
            try:
                await process_once()
            except Exception:
                logger.exception("worker turu başarısız, devam ediliyor")
            await asyncio.sleep(settings.outbox_poll_seconds)
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(run())
