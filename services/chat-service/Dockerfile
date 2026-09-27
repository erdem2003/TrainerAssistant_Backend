# uv: pip'e gore cok daha hizli cozumleme ve kurulum. Docker katman onbellegiyle
# birlikte yeniden derlemeler saniyeler suruyor.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /srv

# Once yalnizca bagimlilik tanimi kopyalaniyor: kod degistiginde bu katman
# onbellekten gelir ve kurulum tekrar kosmaz.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY migrations ./migrations
COPY app ./app

# Kok olmayan kullanici: konteyner ele gecirilirse yetki yuzeyi dar olsun.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
