# USA Atlas API credentials — implementation plan

## Final goal

Create, activate, store, integrate, and verify the six credential sets required by
the USA Atlas pilot without exposing any secret or personal email in the repository,
saved URLs, command output, or assistant messages.

## Before

- Census and EPA stop at `credential_required`.
- EIA uses `DEMO_KEY` and persists the request URL including `api_key`.
- BLS does not send `registrationkey` and Socrata does not send `X-App-Token`.
- The pilot has no BEA API credential probe.
- There is no protected shared credential file for this project.

## After / Will be done

1. **K1 — Safety.** The pilot removes `key`, `api_key`, `registrationkey`,
   `UserID`, app-token fields, and email values from persisted provenance and error
   data. The credential file exists only at
   `/Users/dmitrijrybkin/.config/usa-atlas/credentials.env`, has mode `600`, is never
   printed, and no credential value occurs anywhere under the project root. This
   boundary covers stdout, stderr, persisted results, provenance, raw artifacts,
   exception text, URLs, URL-encoded values, request bodies, headers, and provider
   responses that echo credentials. Authenticated raw responses are saved only after
   recursive field/value sanitization; providers whose safe response shape cannot be
   established are validated in memory and persist only a minimal derived result.
2. **K2 — Registration.** Personal credentials are created and activated through
   the official Census, EPA AQS, EIA, BLS, Socrata/Tyler, and BEA services. The user
   performs email/password/CAPTCHA/confirmation-code entry and confirms each final
   submission in the browser.
3. **K3 — Integration.** The pilot reads the protected credential file without
   printing it. Census and EIA persist canonical URLs without keys; BLS sends its key
   only in the POST body; Socrata sends its token only through `X-App-Token`; EPA
   persists neither email nor key; BEA does not persist an unsanitized response that
   may echo `UserID`. Successful EIA output says `project key`, never `DEMO_KEY`.
4. **K4 — Verification.** One live minimal request succeeds for each credentialed
   service: Census ACS Alameda County, EPA availability plus a small Alameda PM2.5
   request, EIA residential retail price, BLS LAUS v2, CDC PLACES with a Socrata app
   token, and BEA `GetDataSetList`. The full credentialed pilot exits `0` only when
   all six credentialed probes are `pass`; a missing/invalid credential or auth
   failure makes the run exit nonzero. Unrelated explicitly blocked or unselected
   catalog sources do not mask or override this rule.

## Verification method

- **K1:** permissions check; automated sanitization tests covering plain and
  URL-encoded secret values in stdout, stderr, exceptions, raw responses, URLs,
  request bodies, and headers; secret-value scan that
  reports only variable names and match counts/paths, never values; inspect persisted
  URLs and results for forbidden credential parameter names.
- **K2:** before opening a registration flow, verify the provider's current official
  documentation for activation and credential transport; then observe each official
  service's successful confirmation/activation state. Never record credential values
  or personal email in the task packet.
- **K3:** review the exact pilot diff and run targeted tests proving transport and
  persistence behavior.
- **K4:** test the exit rule with missing/failed credentials, then run the full pilot
  with the protected env loaded, require six credentialed `pass` statuses plus exit
  code `0`, and repeat the K1 scan.

## Scope and exclusions

- In scope: `run_pilot.py`, small deterministic tests, protected env-file setup,
  the operator instructions and credential inventory in `DATA-COLLECTION-PLAN.md`,
  official-registration preflight against current provider documentation, six live
  credential probes, and regenerated pilot output.
- Out of scope: proxy rotation, distributed scraping, quota circumvention, production
  deployment, paid plans, Forbes licensing, and unrelated blocked/unselected sources.
- No registration form is finally submitted without an immediate user confirmation.
- No email, password, CAPTCHA, one-time code, or key is entered by the agent unless
  the user explicitly takes over or separately authorizes that exact sensitive input.

## Maintainability impact checklist

1. Outcome: the smallest operator flow is protected file → one sequential pilot run
   → six credentialed `pass` results; baseline and delta are stated above.
2. Ownership/interfaces: environment variables own secrets; source adapters own
   request construction; normalized records own canonical public provenance URLs.
3. Failure/rollback: missing credentials remain explicit; malformed or overly
   permissive credential files fail before network use; removing the file restores
   credential-required behavior without data migration.
4. Reuse/dependencies: Python standard library only; no runtime dependency added.
5. Tests/evidence: deterministic sanitization/transport tests plus six minimal live
   probes, missing/invalid-credential exit-policy tests, and a complete pilot run.
6. Docs/contracts: update the existing data-collection plan with all six credential
   sets, the protected-file workflow, and removal of `DEMO_KEY`; README and repository
   AGENTS are not affected because no project-level setup file or contributor contract
   currently exists.

## After final verification we will get

A repeatable, policy-compliant pilot that uses six active personal credentials from a
mode-`600` file outside the project, proves one real request per provider, exits `0`,
and leaves no credential value or personal email in project artifacts.
