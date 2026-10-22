# Writing tests in `tests/`

These rules apply when you read, add, or change files in this folder.

- **Test through the public API only.** Use `TestClient(app)` and real HTTP calls
  (`client.post("/shorten", ...)`, `client.get(f"/{code}", follow_redirects=False)`).
  Do not call helpers like `encode()` or query `links.db` directly in a test.
- **Cover success and failure.** Every new behavior gets at least one test for the
  happy path and one for a rejection or edge case, asserting the exact status code
  (e.g. 200, 400, 404, 409, 410, 422) and the relevant JSON fields.
- **Keep tests independent.** Each test creates the data it needs and must pass
  alone, in any order, and when the suite is run twice in a row.
- **The database persists between runs.** Tests write to the real `links.db`, which
  is not reset. Any value that must be unused, such as a custom alias, must be
  unique per run: build it with `uuid.uuid4().hex`, never a fixed string like
  `"my-link"`, or the second run will fail with a conflict.
- **Assert behavior, not implementation.** Check responses and redirects, not SQL,
  internal variables, or how a code was generated.
- **Name tests after the behavior**, e.g. `test_custom_alias_conflict_returns_409`.
- Keep the three original tests unchanged unless a task explicitly changes their
  behavior.
- Run `pytest -q` from the project folder (not from `tests/`) so `pytest.ini`
  applies.
