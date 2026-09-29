#!/usr/bin/env bash
# Yedi servisi Cloud Run'a ayrı ayrı dağıtır (ADR 0020).
#
#   ./deploy-cloudrun.sh [TAG]        # TAG: cloudbuild.yaml'ın _TAG'i (varsayılan v1)
#
# Önkoşul: `gcloud builds submit services --config services/cloudbuild.yaml`.
# Servis adresleri DETERMİNİSTİK (https://<servis>-<proje no>.<bölge>.run.app),
# bu yüzden servisler birbirinin adresini dağıtımdan önce bilir.
set -euo pipefail

PROJECT=nabiz-trainer
PROJECT_NUMBER=932371692737
REGION=europe-west1
TAG=${1:-v1}
IMAGE=$REGION-docker.pkg.dev/$PROJECT/nabiz
url() { echo "https://$1-$PROJECT_NUMBER.$REGION.run.app"; }

# Servisler arası anahtar Secret Manager'da; ilk dağıtımda üretilir, ekrana basılmaz.
if ! gcloud secrets describe internal-api-key --project $PROJECT >/dev/null 2>&1; then
  python -c "import secrets; print(secrets.token_urlsafe(32), end='')" \
    | gcloud secrets create internal-api-key --project $PROJECT --replication-policy=automatic --data-file=-
fi
gcloud secrets add-iam-policy-binding internal-api-key --project $PROJECT \
  --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor >/dev/null

SUBSCRIBERS=$(printf '{"workout.session":{"analytics-workout-v1":"%s/internal/events","social-workout-v1":"%s/internal/events","user-referral-v1":"%s/internal/events"}}' \
  "$(url analytics)" "$(url social)" "$(url user)")

deploy() {
  local svc=$1; shift
  gcloud run deploy "$svc" --project $PROJECT --region $REGION \
    --image "$IMAGE/$svc:$TAG" \
    --allow-unauthenticated \
    --min-instances 0 --max-instances 2 --memory 512Mi --cpu 1 \
    --set-secrets INTERNAL_API_KEY=internal-api-key:latest \
    --quiet "$@"
}

deploy user
deploy health
deploy analytics
deploy social
deploy workout --set-env-vars "^@^OUTBOX_DISPATCHER_ENABLED=false@OUTBOX_HTTP_SUBSCRIBERS=$SUBSCRIBERS"
deploy chat --set-env-vars "SOCIAL_SERVICE_URL=$(url social)"
deploy auth --set-env-vars "USER_SERVICE_URL=$(url user),WORKOUT_SERVICE_URL=$(url workout),HEALTH_SERVICE_URL=$(url health),ANALYTICS_SERVICE_URL=$(url analytics),SOCIAL_SERVICE_URL=$(url social),CHAT_SERVICE_URL=$(url chat)"

# Arka plan döngülerinin yerini alan zamanlayıcılar (ücretsiz: 3 iş).
KEY=$(gcloud secrets versions access latest --secret internal-api-key --project $PROJECT)
schedule() {
  local name=$1 cron=$2 target=$3
  local op=create
  gcloud scheduler jobs describe "$name" --project $PROJECT --location $REGION >/dev/null 2>&1 && op=update
  gcloud scheduler jobs $op http "$name" --project $PROJECT --location $REGION \
    --schedule "$cron" --uri "$target" --http-method POST \
    --$([ $op = create ] && echo headers || echo update-headers) "X-Internal-Key=$KEY" \
    --attempt-deadline 60s --quiet >/dev/null
}
schedule outbox-dispatch "*/5 * * * *" "$(url workout)/internal/outbox/dispatch"
schedule social-sweep "*/15 * * * *" "$(url social)/internal/sweep"
unset KEY

for s in user health workout analytics social chat auth; do
  printf '%-10s %s\n' "$s" "$(url "$s")"
done
