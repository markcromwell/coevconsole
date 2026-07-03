# Program Map: CoEv2 Console

<!--GENERATED:BEGIN hash=2bc7b192d221b3dc47ee28bef83db70112881ad21047d758000becad567c5fe2 sig= job=0 commit=ac6b81ee91b1f10c21f6a979a2b14b363dd55cf7-->
<!--Generated 2026-07-03T03:07:36.521416+00:00. Do not edit — will be overwritten.-->

## II. Canonical Data Schema [GENERATED — do not edit]

### `items`

| Column | Type | Nullable | Default |
|--------|------|----------|---------|

### `submissions`

| Column | Type | Nullable | Default |
|--------|------|----------|---------|

## III. File and Module Map [GENERATED — do not edit]

```
.dockerignore
.env.example
.github/workflows/ci.yml
.gitignore
Dockerfile
PROGRAM_MAP.md
README.md
alembic.ini
alembic/env.py
alembic/versions/0001_initial.py
alembic/versions/0002_submissions.py
app/__init__.py
app/auth.py
app/coev2_client.py
app/config.py
app/db.py
app/health.py
app/models.py
app/routers/__init__.py
app/routers/bff.py
app/routers/items.py
app/routers/web.py
deploy/dev.env
deploy/prod.env
deploy/qual.env
deploy/uat.env
docker-compose.bluegreen.yml
docker-compose.yml
main.py
pyproject.toml
requirements.in
requirements.lock
scripts/__init__.py
scripts/setup.py
scripts/smoke_boot.py
scripts/test_auth_enforcement.py
scripts/test_e2e_playwright.py
scripts/test_unit.py
templates/index.html
```

## IV. API Surface [GENERATED — do not edit]

| Method | Path | Status Code |
|--------|------|-------------|
| GET | `` | 200 |
| POST | `` | 201 |
| GET | `/` | 200 |
| POST | `/grade/confirm` | 200 |
| POST | `/grade/prepare` | 200 |
| GET | `/health` | 200 |
| GET | `/loading` | 200 |
| GET | `/submissions` | 200 |
| GET | `/submissions/{console_id}` | 200 |

<!--GENERATED:END-->

---

## V. Architectural Decisions [CURATED]
_No decisions recorded yet._

---

## VI. Planned Work [CURATED]
_To be populated by the spec planner._
