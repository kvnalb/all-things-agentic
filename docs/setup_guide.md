# StudyAgent credential and cloud setup

This guide prepares one Berkeley bCourses account and one personal Google
account for the Fall 2026 hackathon demo. Complete it on the machine where you
will run or deploy StudyAgent.

Do **not** paste tokens, OAuth client JSON, secret values, or private course
content into GitHub, screenshots, logs, or chat. The application needs access
to secrets through your local environment or Google Secret Manager; another
person or coding agent never needs to see their values.

## What this creates

- One bCourses personal access token, used only for read-only Canvas API calls.
- One disposable Google Cloud project with billing enabled.
- Vertex AI, Firestore, Cloud Storage, Secret Manager, Calendar, Cloud Run,
  Cloud Scheduler, Artifact Registry, and Cloud Build APIs.
- One private source bucket and a Firestore Native database.
- Three Secret Manager secrets:
  - `studyagent-canvas-token`
  - `studyagent-google-oauth-client`
  - `studyagent-google-oauth-token`
- One external Google OAuth app in testing mode, restricted to your email.
- One least-privilege Cloud Run service account.

Gmail access is intentionally not requested. Google Calendar access comes from
your end-user OAuth grant; the Cloud Run service account is not given access to
your personal calendar.

## 1. Create the Canvas token

1. Sign in to [bCourses](https://bcourses.berkeley.edu).
2. Open **Account → Settings**.
3. Under **Approved Integrations**, select **New Access Token**.
4. Use purpose `StudyAgent Fall 2026` and choose an expiry after the hackathon.
5. Create the token and copy it immediately. Canvas shows it only once.

Canvas personal tokens do not offer per-scope selection. StudyAgent restricts
its own usage to these read-only `GET` resources:

- current-user profile;
- active courses and syllabus bodies;
- assignments, including the current user's submission state;
- quizzes;
- course calendar events.

It does not submit work, change courses, post discussions, or modify Canvas.

### Store the Canvas token in Secret Manager later

Do not put the token in `.env`. After completing the Google Cloud steps below,
store it without placing the value in shell history:

```sh
read -s STUDYAGENT_CANVAS_TOKEN
printf '%s' "$STUDYAGENT_CANVAS_TOKEN" | gcloud secrets create studyagent-canvas-token \
  --data-file=- \
  --replication-policy=automatic
unset STUDYAGENT_CANVAS_TOKEN
```

If the secret already exists, add a replacement version instead:

```sh
read -s STUDYAGENT_CANVAS_TOKEN
printf '%s' "$STUDYAGENT_CANVAS_TOKEN" | gcloud secrets versions add studyagent-canvas-token \
  --data-file=-
unset STUDYAGENT_CANVAS_TOKEN
```

## 2. Install and authenticate the Google Cloud CLI

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then
open a new terminal and run:

```sh
gcloud auth login
gcloud auth application-default login
```

- `gcloud auth login` authorizes project and deployment commands.
- Application Default Credentials authorize local Vertex AI, Firestore,
  Storage, and Secret Manager clients.

Use the same personal Google account for Cloud Console and local authentication.

## 3. Create the Google Cloud project

Choose a globally unique project ID. The project name need not be unique.

```sh
export STUDYAGENT_PROJECT_ID="replace-with-a-unique-project-id"
export STUDYAGENT_REGION="us-west1"
export STUDYAGENT_SOURCE_BUCKET="${STUDYAGENT_PROJECT_ID}-private-sources"

gcloud projects create "$STUDYAGENT_PROJECT_ID" \
  --name="StudyAgent Hackathon"
gcloud config set project "$STUDYAGENT_PROJECT_ID"
```

Link a billing account in the
[Cloud Billing console](https://console.cloud.google.com/billing/linkedaccount).
Confirm that the selected project at the top of the console is the new
StudyAgent project.

Then make local Application Default Credentials charge quota to this project:

```sh
gcloud auth application-default set-quota-project "$STUDYAGENT_PROJECT_ID"
```

For a disposable personal hackathon project, the fastest setup is for your
account to remain **Project Owner** while provisioning. The deployed runtime
uses the narrower service account configured below.

## 4. Enable the required APIs

```sh
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  calendar-json.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  serviceusage.googleapis.com \
  storage.googleapis.com
```

Why each service exists:

| Service | Use |
| --- | --- |
| Vertex AI | Gemini extraction and bounded agent reasoning |
| Firestore | connection metadata, source revisions, review state, and import runs |
| Cloud Storage | private raw and normalized Canvas/course-site snapshots |
| Secret Manager | Canvas token, OAuth client configuration, and Google refresh token |
| Calendar API | create and update the dedicated StudyAgent calendar |
| Cloud Run | deployed backend and compiled setup wizard |
| Cloud Scheduler | hourly OIDC-authenticated semester sync |
| Artifact Registry / Cloud Build | build and store the Cloud Run container |

No Gmail API is required.

## 5. Create Firestore and the private source bucket

Create the default Firestore database in Native mode:

```sh
gcloud firestore databases create \
  --database="(default)" \
  --location="$STUDYAGENT_REGION" \
  --type=firestore-native
```

If the default database already exists, do not create another one. Verify it:

```sh
gcloud firestore databases describe --database="(default)"
```

Create the source bucket with uniform access and public access prevention:

```sh
gcloud storage buckets create "gs://$STUDYAGENT_SOURCE_BUCKET" \
  --location="$STUDYAGENT_REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention
```

Verify that public access prevention is enforced:

```sh
gcloud storage buckets describe "gs://$STUDYAGENT_SOURCE_BUCKET"
```

## 6. Configure the Google OAuth app

Open the [Google Auth Platform](https://console.cloud.google.com/auth/overview)
and confirm the StudyAgent project is selected.

### Branding and audience

1. Under **Branding**, set the app name to `StudyAgent`.
2. Use your email for user support and developer contact.
3. Under **Audience**, choose **External**.
4. Leave publishing status as **Testing**.
5. Add your personal Google email as a test user.

The connector rejects every authenticated email except the value configured as
`STUDYAGENT_ALLOWED_EMAIL`.

### Data access scopes

Add exactly these scopes:

```text
openid
https://www.googleapis.com/auth/userinfo.email
https://www.googleapis.com/auth/userinfo.profile
https://www.googleapis.com/auth/calendar.app.created
https://www.googleapis.com/auth/calendar.calendarlist.readonly
```

The Calendar scopes allow StudyAgent to manage calendars it created and to
recover the dedicated calendar by its private marker after a partial setup
failure. Do not add `calendar`, `calendar.events`, Drive, or Gmail scopes.

### Create the OAuth client

1. Open **Clients → Create client**.
2. Choose **Web application**.
3. Name it `StudyAgent local and Cloud Run`.
4. Add this local authorized redirect URI exactly:

   ```text
   http://localhost:8080/api/auth/google/callback
   ```

5. After Cloud Run is deployed, add its callback as a second redirect URI:

   ```text
   https://YOUR-CLOUD-RUN-HOST/api/auth/google/callback
   ```

6. Download the client JSON. Treat it as a secret because it contains the
   OAuth client secret.

OAuth testing-mode refresh tokens for external apps may expire after seven
days. Reconnecting before the demo is expected. A public student deployment
would require production publishing and any applicable Google verification.

## 7. Put the OAuth credentials in Secret Manager

Create the client-config secret from the downloaded JSON file:

```sh
gcloud secrets create studyagent-google-oauth-client \
  --data-file="/absolute/path/to/downloaded-oauth-client.json" \
  --replication-policy=automatic
```

Create an empty secret container for refresh-token versions written by the
OAuth callback:

```sh
gcloud secrets create studyagent-google-oauth-token \
  --replication-policy=automatic
```

After confirming the client secret exists in Secret Manager, remove the
downloaded JSON from your local Downloads folder. Do not move it into this
repository.

Verify only secret metadata; do not print secret values:

```sh
gcloud secrets describe studyagent-canvas-token
gcloud secrets describe studyagent-google-oauth-client
gcloud secrets describe studyagent-google-oauth-token
```

## 8. Create the least-privilege runtime service account

```sh
gcloud iam service-accounts create studyagent-runtime \
  --display-name="StudyAgent Cloud Run runtime"

export STUDYAGENT_RUNTIME_SA="studyagent-runtime@${STUDYAGENT_PROJECT_ID}.iam.gserviceaccount.com"
```

Grant project-level runtime roles:

```sh
gcloud projects add-iam-policy-binding "$STUDYAGENT_PROJECT_ID" \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/aiplatform.user"

gcloud projects add-iam-policy-binding "$STUDYAGENT_PROJECT_ID" \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding "$STUDYAGENT_PROJECT_ID" \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/logging.logWriter"

gcloud projects add-iam-policy-binding "$STUDYAGENT_PROJECT_ID" \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/serviceusage.serviceUsageConsumer"
```

Grant object access only on the private source bucket:

```sh
gcloud storage buckets add-iam-policy-binding "gs://$STUDYAGENT_SOURCE_BUCKET" \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/storage.objectAdmin"
```

Grant access to the two input secrets:

```sh
gcloud secrets add-iam-policy-binding studyagent-canvas-token \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding studyagent-google-oauth-client \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor"
```

The runtime must read the exact Google token version referenced by Firestore,
so grant accessor on the token secret as well. It also needs permission to add
new versions during OAuth connection:

```sh
gcloud secrets add-iam-policy-binding studyagent-google-oauth-token \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding studyagent-google-oauth-token \
  --member="serviceAccount:$STUDYAGENT_RUNTIME_SA" \
  --role="roles/secretmanager.secretVersionAdder"
```

Do not grant the runtime `roles/owner`, `roles/editor`, project-wide Secret
Manager Admin, Storage Admin, or any Google Workspace administrator role.

## 9. Record the non-secret configuration

Get the project number and secret resource names:

```sh
export STUDYAGENT_PROJECT_NUMBER="$(gcloud projects describe "$STUDYAGENT_PROJECT_ID" --format='value(projectNumber)')"

printf 'Project: %s\n' "$STUDYAGENT_PROJECT_ID"
printf 'Region: %s\n' "$STUDYAGENT_REGION"
printf 'Bucket: %s\n' "$STUDYAGENT_SOURCE_BUCKET"
printf 'Runtime service account: %s\n' "$STUDYAGENT_RUNTIME_SA"
printf 'Canvas secret: projects/%s/secrets/studyagent-canvas-token\n' "$STUDYAGENT_PROJECT_NUMBER"
printf 'OAuth client secret: projects/%s/secrets/studyagent-google-oauth-client\n' "$STUDYAGENT_PROJECT_NUMBER"
printf 'OAuth token secret: projects/%s/secrets/studyagent-google-oauth-token\n' "$STUDYAGENT_PROJECT_NUMBER"
```

These identifiers are safe configuration; the secret values are not. The app
will use:

```text
STUDYAGENT_ENV=development
STUDYAGENT_ALLOWED_EMAIL=your-personal-google-email
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_GENAI_USE_VERTEXAI=true
STUDYAGENT_GEMINI_MODEL=gemini-3.5-flash
STUDYAGENT_SOURCE_BUCKET=your-private-source-bucket
```

Do not commit a populated `.env`. Export values in the current terminal or use
Cloud Run's non-secret environment-variable configuration.

## 10. Deploy the owner-protected service

The app serves the React UI and FastAPI API from one container. Set the final
Cloud Run URL as `STUDYAGENT_BASE_URL`; it must exactly match the OAuth callback
host configured in Google Auth Platform.

```sh
gcloud run deploy studyagent \
  --source=. \
  --region="$STUDYAGENT_REGION" \
  --service-account="$STUDYAGENT_RUNTIME_SA" \
  --allow-unauthenticated \
  --min=0 \
  --set-env-vars="STUDYAGENT_ENV=production,STUDYAGENT_ALLOWED_EMAIL=your-personal-google-email,GOOGLE_CLOUD_PROJECT=$STUDYAGENT_PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=true,STUDYAGENT_GEMINI_MODEL=gemini-3.5-flash,STUDYAGENT_SOURCE_BUCKET=$STUDYAGENT_SOURCE_BUCKET,CANVAS_BASE_URL=https://bcourses.berkeley.edu"
```

Get the stable service URL, add its exact callback to the OAuth client, and
then redeploy with the base URL:

```sh
export STUDYAGENT_BASE_URL="$(gcloud run services describe studyagent --region="$STUDYAGENT_REGION" --format='value(status.url)')"
gcloud run services update studyagent \
  --region="$STUDYAGENT_REGION" \
  --update-env-vars="STUDYAGENT_BASE_URL=$STUDYAGENT_BASE_URL"
```

Only the landing page and OAuth endpoints are anonymous. The private API uses
the secure owner-session cookie created by the OAuth callback. Open
`$STUDYAGENT_BASE_URL`, select **Connect Google**, and authorize the configured
owner account.

## 11. Create the hourly scheduler

```sh
gcloud iam service-accounts create studyagent-scheduler \
  --display-name="StudyAgent hourly scheduler"

export STUDYAGENT_SCHEDULER_SA="studyagent-scheduler@${STUDYAGENT_PROJECT_ID}.iam.gserviceaccount.com"

gcloud scheduler jobs create http studyagent-hourly-sync \
  --location="$STUDYAGENT_REGION" \
  --schedule="0 * * * *" \
  --uri="$STUDYAGENT_BASE_URL/internal/sync" \
  --http-method=POST \
  --oidc-service-account-email="$STUDYAGENT_SCHEDULER_SA" \
  --oidc-token-audience="$STUDYAGENT_BASE_URL/internal/sync" \
  --paused
```

Leave it paused until one manual sync succeeds. Then enable it:

```sh
gcloud scheduler jobs resume studyagent-hourly-sync \
  --location="$STUDYAGENT_REGION"
```

## 12. Verify readiness without exposing secrets

Run these checks:

```sh
gcloud auth list
gcloud config get-value project
gcloud auth application-default print-access-token >/dev/null
gcloud services list --enabled \
  --filter='name:(aiplatform.googleapis.com calendar-json.googleapis.com cloudscheduler.googleapis.com firestore.googleapis.com run.googleapis.com secretmanager.googleapis.com storage.googleapis.com)'
gcloud firestore databases describe --database="(default)"
gcloud storage buckets describe "gs://$STUDYAGENT_SOURCE_BUCKET"
gcloud secrets describe studyagent-canvas-token
gcloud secrets describe studyagent-google-oauth-client
gcloud secrets describe studyagent-google-oauth-token
```

Then confirm in Google Auth Platform:

- the app is **External / Testing**;
- your exact email is a test user;
- the five scopes above are the only requested scopes;
- the localhost callback matches exactly;
- the deployed Cloud Run callback matches exactly;
- the downloaded OAuth JSON is no longer in the repository or Downloads.

At this point, open the hosted wizard, connect Google, discover Canvas courses,
attach course sites or a syllabus, and run the first sync. Run it again without
changing the inputs: the second run must create zero duplicate Calendar events.
