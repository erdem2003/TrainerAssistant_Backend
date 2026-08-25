"""E-posta govdeleri ve SMTP gonderimi."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from app.config import settings
from app.events import (
    EVENT_ACCOUNT_DELETED,
    EVENT_EMAIL_VERIFICATION_REQUESTED,
    EVENT_PASSWORD_CHANGED,
    EVENT_PASSWORD_RESET_REQUESTED,
)

logger = logging.getLogger(__name__)


class UnknownEventType(Exception):
    """Tanınmayan event. Yeniden denemek düzeltmez; çağıran taraf elemeli."""

# --- Mesaj gövdeleri ---------------------------------------------------------


def _verification_message(payload: dict) -> EmailMessage:
    code = payload["code"]
    minutes = payload.get("expires_in_seconds", settings.code_ttl_seconds) // 60

    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = payload["email"]
    message["Subject"] = "Doğrulama kodun"
    message.set_content(
        f"Merhaba,\n\n"
        f"AI Fitness Coach doğrulama kodun: {code}\n\n"
        f"Kod {minutes} dakika geçerli.\n\n"
        f"Bu isteği sen yapmadıysan bu e-postayı görmezden gelebilirsin.\n"
    )
    # HTML alternatifi: kod büyük ve seçilebilir olsun diye. Düz metin gövdesi
    # korunuyor — HTML'i engelleyen istemcilerde mail boş görünmemeli.
    message.add_alternative(
        f"""<html><body style="font-family:system-ui,sans-serif;color:#12171e">
  <p>Merhaba,</p>
  <p>AI Fitness Coach doğrulama kodun:</p>
  <p style="font-size:32px;font-weight:700;letter-spacing:6px;color:#0f6e78">{code}</p>
  <p style="color:#6b7684">Kod {minutes} dakika geçerli.</p>
  <p style="color:#6b7684;font-size:13px">Bu isteği sen yapmadıysan bu e-postayı
  görmezden gelebilirsin.</p>
</body></html>""",
        subtype="html",
    )
    return message



def _password_reset_message(payload: dict) -> EmailMessage:
    code = payload["code"]
    minutes = payload.get("expires_in_seconds", settings.code_ttl_seconds) // 60

    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = payload["email"]
    message["Subject"] = "Parola sıfırlama kodun"
    message.set_content(
        f"Merhaba,\n\n"
        f"Parola sıfırlama kodun: {code}\n\n"
        f"Kod {minutes} dakika geçerli.\n\n"
        f"Bu isteği sen yapmadıysan parolan DEĞİŞMEDİ ve bir şey yapmana\n"
        f"gerek yok.\n"
    )
    return message


def _password_changed_message(payload: dict) -> EmailMessage:
    """Parola değişti bildirimi."""
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = payload["email"]
    message["Subject"] = "Parolan değişti"
    message.set_content(
        "Merhaba,\n\n"
        "Hesabının parolası az önce değiştirildi ve açık olan tüm oturumlar\n"
        "kapatıldı.\n\n"
        "Bunu sen yapmadıysan hesabın risk altında olabilir: hemen parola\n"
        "sıfırlama iste ve e-posta hesabının güvenliğini kontrol et.\n"
    )
    return message


def _account_deleted_message(payload: dict) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = payload["email"]
    message["Subject"] = "Hesabın silindi"
    message.set_content(
        "Merhaba,\n\n"
        "Hesabın ve antrenman verilerin kalıcı olarak silindi.\n\n"
        "Bizi tercih ettiğin için teşekkürler. İstersen istediğin zaman yeni\n"
        "bir hesap açabilirsin.\n"
    )
    return message

_BUILDERS = {
    EVENT_EMAIL_VERIFICATION_REQUESTED: _verification_message,
    EVENT_PASSWORD_RESET_REQUESTED: _password_reset_message,
    EVENT_PASSWORD_CHANGED: _password_changed_message,
    EVENT_ACCOUNT_DELETED: _account_deleted_message,
}


def build(event_type: str, payload: dict) -> EmailMessage:
    builder = _BUILDERS.get(event_type)
    if builder is None:
        raise UnknownEventType(event_type)

    message = builder(payload)
    _add_transport_headers(message)
    return message


def _add_transport_headers(message: EmailMessage) -> None:
    """`Date` ve `Message-ID` ekler."""
    if "Date" not in message:
        message["Date"] = formatdate(localtime=True)
    if "Message-ID" not in message:
        # Domain, gönderen adresinden türetiliyor; sabit bir uydurma alan adı
        # (ör. trainerasistant.local) filtrelerin baktığı bir tutarsızlık olurdu.
        _, sender_address = parseaddr(settings.mail_from)
        domain = sender_address.rpartition("@")[2] or "localhost"
        message["Message-ID"] = make_msgid(domain=domain)

# --- Gönderim ----------------------------------------------------------------


def _send_sync(message: EmailMessage) -> None:
    """`smtplib` ile gönderim."""
    if settings.smtp_use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_username and settings.smtp_password:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)


async def send(message: EmailMessage) -> None:
    """`smtplib` bloklayıcı; thread'e alınıyor."""
    await asyncio.to_thread(_send_sync, message)


async def deliver(event_type: str, payload: dict) -> None:
    """Tek giriş noktası: event → mail."""
    await send(build(event_type, payload))
    # Log'da e-posta ADRESİ YOK (service-contract §11).
    logger.info("e-posta gönderildi event=%s", event_type)
