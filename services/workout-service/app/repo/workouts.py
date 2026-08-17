"""workouts / sets / reps / rep_form_errors tablolarinin SQL'i."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import asyncpg

# --- Yazma ------------------------------------------------------------------

# ON CONFLICT DO NOTHING: ayni id ikinci kez geldiginde YENI SATIR ACILMAZ ve
# hata da firlatilmaz. Cagiran taraf donen satirin bos olmasindan "bu bir tekrar"
# sonucunu cikarir ve icerik ozetini karsilastirir (service-contract §4).
INSERT_WORKOUT = """
INSERT INTO workouts (id, user_id, exercise_id, started_at, ended_at, content_hash)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (id) DO NOTHING
RETURNING id
"""

INSERT_SET = """
INSERT INTO sets (workout_id, set_index, started_at, ended_at)
VALUES ($1, $2, $3, $4)
RETURNING id
"""

INSERT_REP = """
INSERT INTO reps (set_id, rep_index, duration_s, eccentric_s, concentric_s, rom)
VALUES ($1, $2, $3, $4, $5, $6)
RETURNING id
"""

INSERT_FORM_ERROR = """
INSERT INTO rep_form_errors (rep_id, error)
VALUES ($1, $2)
ON CONFLICT DO NOTHING
"""

# --- Okuma ------------------------------------------------------------------

SELECT_OWNER_AND_HASH = """
SELECT user_id, content_hash FROM workouts WHERE id = $1
"""

# Tek antrenmanin tamami. Setler ve tekrarlar TEK SORGUDA aliniyor:
# set basina ayri sorgu atmak N+1 olurdu ve 10 setlik bir antrenman 11 gidis
# donus demekti.
SELECT_WORKOUT_DETAIL = """
SELECT w.id, w.exercise_id, w.started_at, w.ended_at,
       s.set_index, s.started_at AS set_started, s.ended_at AS set_ended,
       r.id AS rep_id, r.rep_index, r.duration_s, r.eccentric_s,
       r.concentric_s, r.rom,
       e.error
  FROM workouts w
  LEFT JOIN sets s ON s.workout_id = w.id
  LEFT JOIN reps r ON r.set_id = s.id
  LEFT JOIN rep_form_errors e ON e.rep_id = r.id
 WHERE w.id = $1 AND w.user_id = $2
 ORDER BY s.set_index, r.rep_index, e.error
"""

# Gecmis listesi — cursor sayfalama (service-contract §5).
#
# NEDEN OFFSET DEGIL: offset sayfalama, araya yeni kayit girdiginde satir atlar
# veya tekrarlar. Antrenman listesi tam olarak boyle bir liste — en yeni ustte ve
# surekli ekleniyor.
#
# `(started_at, id) < (cursor_started_at, cursor_id)` bilesik karsilastirmasi,
# ayni anda baslamis iki antrenmanda bile kararli bir sira uretiyor.
SELECT_WORKOUT_PAGE = """
SELECT w.id, w.exercise_id, w.started_at, w.ended_at,
       COUNT(DISTINCT s.id)                                   AS total_sets,
       COUNT(DISTINCT r.id)                                   AS total_reps,
       COUNT(DISTINCT r.id) FILTER (WHERE e.rep_id IS NOT NULL) AS reps_with_errors,
       -- ★ ALT SORGU, ANA JOIN'DE SUM DEGIL ★
       -- Bu sorgu set × tekrar × hata kartezyeni uretiyor; set surelerini ana
       -- JOIN icinde toplamak her seti tekrar sayisi kadar sayar ve degeri kat
       -- kat sisirirdi. `COUNT(DISTINCT ...)` bu tuzagi sayimlar icin cozuyor
       -- ama TOPLAMA icin DISTINCT bir cozum degil.
       COALESCE((
           SELECT SUM(EXTRACT(EPOCH FROM (s2.ended_at - s2.started_at)))
             FROM sets s2 WHERE s2.workout_id = w.id
       ), 0)                                                  AS active_seconds,
       -- Bu antrenmandaki EN KALABALIK setin tekrar sayisi.
       -- Kisisel rekor ("tek sette en cok tekrar") yalnizca bu sayidan
       -- hesaplanabiliyor; liste yaniti set kirilimini tasimiyor ve her
       -- antrenmanin ayrintisini cekmek 200 istek demekti.
       COALESCE((
           SELECT MAX(cnt) FROM (
               SELECT COUNT(r3.id) AS cnt
                 FROM sets s3 LEFT JOIN reps r3 ON r3.set_id = s3.id
                WHERE s3.workout_id = w.id
                GROUP BY s3.id
           ) per_set
       ), 0)                                                  AS best_set_reps
  FROM workouts w
  LEFT JOIN sets s ON s.workout_id = w.id
  LEFT JOIN reps r ON r.set_id = s.id
  LEFT JOIN rep_form_errors e ON e.rep_id = r.id
 WHERE w.user_id = $1
   AND ($2::timestamptz IS NULL OR (w.started_at, w.id) < ($2, $3))
 GROUP BY w.id
 ORDER BY w.started_at DESC, w.id DESC
 LIMIT $4
"""

DELETE_BY_USER = "DELETE FROM workouts WHERE user_id = $1"


@dataclass(frozen=True)
class ExistingWorkout:
    user_id: uuid.UUID
    content_hash: str


@dataclass(frozen=True)
class WorkoutSummaryRow:
    id: uuid.UUID
    exercise_id: str
    started_at: datetime
    ended_at: datetime | None
    total_sets: int
    total_reps: int
    reps_with_errors: int
    # Setlerin toplam suresi — setler ARASI dinlenme HARIC. Kalori girdisi.
    active_seconds: float
    # Bu antrenmandaki en kalabalik setin tekrar sayisi (kisisel rekor icin).
    best_set_reps: int


async def find_existing(
    conn: asyncpg.Connection, workout_id: uuid.UUID
) -> ExistingWorkout | None:
    row = await conn.fetchrow(SELECT_OWNER_AND_HASH, workout_id)
    if row is None:
        return None
    return ExistingWorkout(user_id=row["user_id"], content_hash=row["content_hash"])


async def insert_full(
    conn: asyncpg.Connection,
    *,
    workout_id: uuid.UUID,
    user_id: uuid.UUID,
    exercise_id: str,
    started_at: datetime,
    ended_at: datetime | None,
    content_hash: str,
    sets: list,
) -> bool:
    """Antrenmani setleri ve tekrarlariyla birlikte yazar.

    `True` = yeni kayit acildi. `False` = bu id zaten vardi, hicbir sey yazilmadi.

    CAGIRAN TARAF TRANSACTION ACMALI: yarim yazilmis bir antrenman (setleri olan
    ama tekrarlari olmayan) sessizce yanlis veri olurdu.
    """
    created = await conn.fetchval(
        INSERT_WORKOUT, workout_id, user_id, exercise_id,
        started_at, ended_at, content_hash,
    )
    if created is None:
        return False

    for set_in in sets:
        set_id = await conn.fetchval(
            INSERT_SET, workout_id, set_in.index,
            set_in.started_at, set_in.ended_at,
        )
        for rep in set_in.reps:
            rep_id = await conn.fetchval(
                INSERT_REP, set_id, rep.index, rep.duration_seconds,
                rep.eccentric_seconds, rep.concentric_seconds, rep.rom,
            )
            for error in rep.form_errors:
                await conn.execute(INSERT_FORM_ERROR, rep_id, error)

    return True


async def fetch_detail(
    conn: asyncpg.Connection, workout_id: uuid.UUID, user_id: uuid.UUID
) -> list[asyncpg.Record]:
    return await conn.fetch(SELECT_WORKOUT_DETAIL, workout_id, user_id)


async def fetch_page(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    *,
    cursor_started_at: datetime | None,
    cursor_id: uuid.UUID | None,
    limit: int,
) -> list[WorkoutSummaryRow]:
    rows = await conn.fetch(
        SELECT_WORKOUT_PAGE, user_id, cursor_started_at, cursor_id, limit
    )
    return [
        WorkoutSummaryRow(
            id=row["id"],
            exercise_id=row["exercise_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            total_sets=row["total_sets"],
            total_reps=row["total_reps"],
            reps_with_errors=row["reps_with_errors"],
            # `EXTRACT(EPOCH ...)` numeric doner, asyncpg Decimal'e cevirir.
            active_seconds=float(row["active_seconds"]),
            best_set_reps=row["best_set_reps"],
        )
        for row in rows
    ]


async def delete_by_user(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    """Kullanicinin tum antrenmanlarini siler (hesap silme zinciri).

    `sets`, `reps` ve `rep_form_errors` CASCADE ile birlikte gidiyor.
    """
    result = await conn.execute(DELETE_BY_USER, user_id)
    return int(result.rsplit(" ", 1)[1])
