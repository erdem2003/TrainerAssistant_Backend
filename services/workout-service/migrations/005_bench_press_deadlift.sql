-- Bench press ve deadlift egzersiz katalogüna eklendi (004_squat deseniyle aynı).
--
-- İLK EKİPMANLI EGZERSİZLER (barbell/bench) — önceki dördü (şınav/mekik/squat/
-- pull-up[geri alındı]) ekipmansızdı. `required_view` ikisi de SIDE:
-- bench press yatay govde geometrisi push-up'la özdeş; deadlift kalça
-- menteşesi squat'la aynı SIDE ölçüm mantığını paylaşıyor.
INSERT INTO exercises (id, display_name, required_view)
VALUES
  ('bench_press', 'Bench Press', 'SIDE'),
  ('deadlift', 'Deadlift', 'SIDE')
ON CONFLICT (id) DO NOTHING;
