# Recruitment → onboarding → employee handoff

`test_portal_handoff.py` exercises the real Django routes and forms across
multiple requests. It uses temporary uploads, an in-memory mail backend, and
mocked invitation delivery; it never needs to email a candidate.

Run it against Django's separate test database:

```sh
python manage.py test onboarding.tests.test_portal_handoff --keepdb
```

## Expected handoff

1. A hired candidate appears on the onboarding candidates page.
2. HR starts the initial onboarding stage, with or without a portal invitation.
   Starting without email must not require SMTP or reset an existing portal.
3. The candidate sets a password. Pending account data lives in their shared
   server-side session, keyed to this portal; no user is created yet.
4. The optional profile step and personal-details step can run on any web worker.
5. Saving valid personal details creates the account, employee, work information,
   document links, and candidate-to-employee link in one database transaction.
   The new employee receives own-profile permissions and is signed in.
6. The bank step accepts only the employee belonging to that portal. Invalid
   submissions remain on the form; valid submissions consume the portal and
   open the welcome page. Replayed or unknown portal links return 404.

An invitation resend preserves its active token and progress. A failed delivery
must not be reported as successful or start onboarding for a new candidate.
Managers may only select candidates in recruitments they manage; HR's existing
permission and selected-company restrictions still apply.

## Deployment and remaining verification

- Keep sessions server-side and shared across workers. The current application
  uses Django's database sessions. Pending session data contains a password hash,
  never the plaintext password; do not use signed-cookie sessions for this flow.
- Existing portals at the bank step can resume after the employee signs in.
  Older in-memory-only password steps must be submitted again once after deploy.
- Portal completion is separate from HR's onboarding task/stage completion;
  submitting bank details does not silently mark outstanding HR tasks complete.
- Automated delivery checks are mocked. Real SMTP delivery, public HTTPS portal
  URLs, and browser/mobile interaction still need staging verification.
- These tests do not certify job applications/surveys, the alternative direct
  conversion action, or the attendance/leave/payroll integration.
