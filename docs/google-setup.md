# Google account setup

This is the live setup still required around the tested connector in issue `#13`.
Use a fresh project and a personal Gmail test account. Never paste OAuth tokens,
client secrets, or downloaded credentials into Git, logs, screenshots, browser
storage, or Firestore.

## 1. Create the project and runtime identity

Choose globally unique values, then authenticate `gcloud` interactively:

```sh
gcloud auth login
gcloud projects create STUDYAGENT_PROJECT_ID --name="StudyAgent Hackathon"
gcloud billing projects link STUDYAGENT_PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
gcloud config set project STUDYAGENT_PROJECT_ID
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  calendar-json.googleapis.com \
  gmail.googleapis.com
gcloud iam service-accounts create studyagent-runtime \
  --display-name="StudyAgent Cloud Run runtime"
```

Create Firestore in Native mode and a private Cloud Storage bucket in the same
region as Cloud Run. Those resources are shared with later connector issues.

## 2. Configure OAuth

In Google Auth Platform in the Cloud console:

1. Configure the app name, support email, and developer contact.
2. Choose **External** audience, leave publishing status at **Testing** for the
   hackathon, and add the one personal Gmail address as a test user.
3. Declare exactly these scopes:
   - `openid`
   - `email`
   - `profile`
   - `https://www.googleapis.com/auth/calendar.app.created`
   - `https://www.googleapis.com/auth/gmail.send`
4. Create a **Web application** OAuth client.
5. Add the deployed callback exactly as an authorized redirect URI:
   `https://CLOUD_RUN_HOST/api/auth/google/callback`.

The authorization adapter must pass `access_type=offline`,
`include_granted_scopes=true`, and `prompt=consent`. The connector rejects a
callback that lacks a refresh token or any required scope.

Testing-mode warning: for an External app requesting Calendar/Gmail access,
Google currently expires refresh tokens after seven days. That is acceptable for
the hackathon. A durable student deployment must move the app to production and
complete the applicable brand/data-access verification; it must also handle
revocation and refresh failure by asking the user to reconnect.

## 3. Store credentials with least privilege

Create two secrets:

- `google-oauth-client`: OAuth client ID and client secret.
- `google-oauth-token`: versions written by the callback; each value contains
  the refresh token and current token metadata.

Grant the Cloud Run runtime service account only:

- `roles/secretmanager.secretAccessor` on those two secrets;
- `roles/secretmanager.secretVersionAdder` on `google-oauth-token` only;
- `roles/datastore.user` for non-secret connection metadata in Firestore.

Do not grant project-wide Secret Manager access. Pass only non-secret resource
names and the callback URL as Cloud Run environment variables. The runtime
resolves Secret Manager references internally.

Persist these non-secret fields in one Firestore connection document:

- Secret Manager token version reference;
- authenticated email address;
- app-created Calendar ID.

Persist one-time OAuth state digests with a ten-minute expiry in Firestore. The
in-memory implementation in this PR is for local/single-instance tests only.

## 4. Wire and verify

The integration layer must implement the protocols in
`backend/studyagent/connectors/google.py`, include the router from
`backend/studyagent/api/google.py`, and then deploy the existing single container.

Verify using the setup wizard:

1. Start Google sign-in and inspect the consent screen for exactly the five
   scopes above.
2. Finish the callback and confirm `StudyAgent — Fall 2026` exists in Google
   Calendar with `America/Los_Angeles` as its timezone.
3. Reconnect and confirm the stored Calendar ID is recovered rather than a
   second calendar being created.
4. Click the explicit test-email action and confirm the message arrives at the
   authenticated address.
5. Inspect API responses, Cloud Run logs, Firestore, and screenshots to confirm
   no OAuth token or client secret appears.

Calendar recovery deliberately uses the persisted calendar ID. The narrow
`calendar.app.created` scope can create and access app-created calendars, but it
cannot list the user's entire calendar list to search by name.

## Primary references

- [Google OAuth for web-server applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
- [Calendar `calendars.insert`](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/insert)
- [Calendar `calendars.get`](https://developers.google.com/workspace/calendar/api/v3/reference/calendars/get)
- [Calendar `calendarList.list` scopes](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list)
- [Gmail API scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Cloud Run secret configuration](https://cloud.google.com/run/docs/configuring/services/secrets)
- [Secret Manager access control](https://cloud.google.com/secret-manager/docs/access-control)
