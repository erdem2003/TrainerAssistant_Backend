-- analytics_db ilk şema — ADR 0006, Phase 11.
--
-- ★ BU BİR OKUMA MODELİ (READ MODEL), İKİNCİ BİR KAYNAK DEĞİL ★
-- Buradaki her satır `workout.session` olay akışından türedi. Doğruluk kaynağı
-- `workout_db`; burası o akışın bir izdüşümü (projection). Bu ayrım önemli:
-- veri bozulursa çözüm elle düzeltmek DEĞİL, consumer offset'ini sıfırlayıp
-- akışı yeniden oynatmak.

-- ---------------------------------------------------------------------------
-- workout_facts — antrenman başına bir satır
-- ---------------------------------------------------------------------------
-- ★ NEDEN GÜNE GÖRE ÖNCEDEN TOPLANMADI ★
-- İlk tasarım "günlük toplamlar" tablosuydu. Sorun: gün sınırı kullanıcının
-- SAAT DİLİMİNE bağlı (bkz. workout-service `localday.py`) ve olay bu bilgiyi
-- taşımıyor — istemci onu istek anında gönderiyor. Toplamı yazma anında
-- dondurursak UTC'ye göre donar ve İstanbul'da gece 01:00'de yapılan antrenman
-- kalıcı olarak yanlış güne yazılır; sonradan düzeltmek imkânsız olur.
--
-- Bu yüzden ham gerçekler saklanıyor, toplama OKUMA anında yapılıyor. Maliyeti
-- bu ölçekte ihmal edilebilir ve saat dilimi doğruluğu korunuyor.
CREATE TABLE workout_facts (
    -- İstemcide üretilen antrenman id'si. BİRİNCİL ANAHTAR olarak kullanılıyor:
    -- aynı antrenman iki kez yayınlanırsa (Kafka at-least-once verir) ikinci
    -- yazım çakışır ve yutulur.
    workout_id           UUID        PRIMARY KEY,

    user_id              UUID        NOT NULL,
    exercise_id          TEXT        NOT NULL,

    -- UTC. Yerel güne çevrim okuma anında, `tz_offset` parametresiyle.
    started_at           TIMESTAMPTZ NOT NULL,
    ended_at             TIMESTAMPTZ NULL,

    total_sets           SMALLINT    NOT NULL,
    total_reps           SMALLINT    NOT NULL,
    reps_with_errors     SMALLINT    NOT NULL,
    best_set_reps        SMALLINT    NOT NULL,
    -- Setlerin toplam süresi, setler ARASI dinlenme hariç (kalori girdisi).
    total_active_seconds REAL        NOT NULL,
    -- `FormError` adı → o antrenmanda kaç tekrarda görüldü.
    form_errors          JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- Olayın işlendiği an — replay sonrası verinin tazeliğini görmek için.
    projected_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX workout_facts_user_started_idx
    ON workout_facts (user_id, started_at);

-- ---------------------------------------------------------------------------
-- processed_events — idempotent consumer (ADR 0006)
-- ---------------------------------------------------------------------------
-- Kafka AT-LEAST-ONCE veriyor: aynı olay ikinci kez teslim edilebilir.
-- `workout_facts` birincil anahtarı zaten koruyor ama bu tablo GENEL koruma:
-- ileride tabloya yazmayan (ör. yalnızca sayaç artıran) tüketiciler eklendiğinde
-- tek savunma bu olacak.
CREATE TABLE processed_events (
    event_id     UUID        PRIMARY KEY,
    event_type   TEXT        NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX processed_events_processed_at_idx ON processed_events (processed_at);
