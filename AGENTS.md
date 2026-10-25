# Repository contribution boundary

- This is the standalone data pipeline repository. Keep collection, normalization,
  ingestion, database schema/migrations, and data operations here.
- The application consumes admitted `usa_atlas` data through a read-only adapter.
  Do not add app UI behavior, collector dependencies, credentials, or live database
  writes to app-facing code. Keep the reader artifact versioned under
  `database/reader/vN/`; do not create a third repository.
- Code, docs, comments, commits, and generated artifact metadata are English.
- Luna implements the requested change; the parent agent reviews the local commit.
  There are no blanket approval gates. Follow explicit task authorization and
  ordinary repository protections.
- Use Luna with `gpt-6-luna` at the default service tier; keep Fast and Ultrafast
  modes off. The parent reviews implementation, tests, and integration results.
- Before implementation, inspect the worktree, branch, upstream/origin state, and
  applicable instructions. Treat a dirty worktree or an unexpected branch as
  context to preserve and report; do not reset, clean, or overwrite existing work.
- Do not infer production identity from local `main`, an origin branch, or history.
  Public manifest reads may establish the advertised release only within the
  manifest's documented scope. Never read production data or write to live
  databases during reader work.
- Preserve regression coverage and immutable release history. Do not weaken
  loader guards or rewrite a released artifact in place to make a test pass.
- Keep the reader schema contract version and its exported artifact hashes tied
  to each release. Coordinate cross-repository adapter changes against that
  versioned contract; do not fold collector code or source-release versions into
  the reader contract version.
- When a reader release needs an app rollout, reference the application
  repository's release-command documentation instead of duplicating commands
  here. Do not add or execute app release commands or app UI behavior here.
- Avoid stale claims that name a current source release or deployed binding unless
  the claim is supported by a fresh, appropriately scoped public manifest. Keep
  deployment identity marked unverified when it has not been established.
- Require a pull request for changes to protected `main`; do not bypass branch
  protection. No remote operations are part of ordinary reader implementation.
- Keep collector code version, reader schema contract version, and admitted
  observation/source release versions separate.
- Never treat local `main` history as proof of deployed production identity.
- Do not run collectors or access/change live databases as part of reader work.
