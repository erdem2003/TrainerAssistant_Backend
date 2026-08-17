-- Squat egzersiz kataloğuna eklendi (002_sit_up deseniyle aynı).
--
-- `required_view` SIDE: çömelme derinliği ve gövde açısı ancak profilden
-- ölçülebilir. `squat.md` iki hatayı (`KNEE_VALGUS`, `ASYMMETRY`) FRONT görüş
-- gerektirdiği için işaretlemiş; onlar bu turda uygulanmıyor.
INSERT INTO exercises (id, display_name, required_view)
VALUES ('squat', 'Squat', 'SIDE')
ON CONFLICT (id) DO NOTHING;
