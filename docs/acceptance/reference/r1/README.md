# Reference HTTP acceptance r1

## 入口与修订

Method revision: `reference-http-r1.1`. Requirement revision: `reference-requirements-r1`.

This independent checker is authored from [`reference-requirements-r1`](../../../implementation/reference-requirements-r1.md). It targets a disposable local reference instance through HTTP. It does not import or inspect candidate source, migration files, or build context.

## 运行方式

Run from the repository root with Python 3.10 or later:

```sh
python3 docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:8000
python3 docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:8000 --phase seed
# Restart only the API process while retaining the same PostgreSQL data.
python3 docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:8000 --phase verify-persisted
```

`baseline` is the default phase. It checks health/readiness, the HTTP note contract and validation boundaries, exact-marker cleanup, plus HTTP 200 for the frontend root HTML and one same-origin JavaScript bundle. It does not claim the UI is interactive or provide Tauri/WebView native acceptance.

Run `seed`, restart the API process without recreating its database, then run `verify-persisted` to check database persistence across API process reconstruction. The harness observes the marker after the operator's restart; it cannot prove that a restart occurred, so bind both outputs to the operator's restart evidence. The verification phase deletes only the exact reserved persistence marker after checking it. `baseline` also deletes its fixed reserved titles and that persistence marker before and after its own cases. Keep the instance and database isolated from user data.

For REF-06 dependency rejection, prepare a disposable instance once with the database unavailable and once with the required migration head unavailable. Run this phase separately in each prepared state:

```sh
python3 docs/acceptance/reference/r1/verify_http.py --base-url http://127.0.0.1:8000 --phase not-ready
```

Each invocation requires `/health` to return 200 and `/ready` to return 503. The harness observes those statuses; the operator must bind each saved result to the actual database or migration fault setup. Do not run fault setup against user data.

## 结果绑定

The process prints one compact JSON result with the method and requirement revisions, case totals, and passed/failed case names. A failed case exits nonzero. Response bodies and exception text are not printed. The checker screens returned HTTP bodies for a small set of credential-shaped literals; this is a narrow leak check, not proof that all possible secrets are absent.

## 断言范围与限制

Coverage and limits:

- HTTP assertions cover REF-02 through REF-04 note routes, CRUD, sorting, server-generated integer IDs, title trimming and limits, body size/default, PATCH field rules, 404 behavior, UTC response timestamps, and persistence across API restart.
- The baseline checks a reverse-lexical title pair by returned IDs before deleting the CRUD core note, then checks the records that remain live; the deleted core note is checked separately for 404.
- REF-06 coverage observes `/health` and `/ready` status behavior in healthy and externally prepared dependency-failure states. It does not independently identify which fault was prepared.
- HTTP checks cannot establish the Alembic graph, table definition, application startup behavior, PostgreSQL write path, or prove that an API process restart occurred. Bind the persistence run to a disposable PostgreSQL instance and the operator's restart evidence; inspect public migration/tool evidence separately.
- REF-01 coverage is limited to the root HTML and a same-origin JavaScript bundle existing over HTTP. UI interaction, understandable error presentation, and native Desktop isolation are outside this method.
- REF-05 migration structure and REF-07 dependency locks/Compose/build separation are not covered here.
- No human acceptance, real independent-machine delivery acceptance, commit, immutable candidate hash, InputSet, or execution result is asserted by these files.

Changes to these assertions require a new method revision and a new InputSet after the candidate and inputs are frozen.
