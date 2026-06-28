# 🧠 English Exam Bot

A professional Telegram bot that generates **konkoor-style English exams** —
either freshly written by **OpenAI** or drawn from a bank of **real past konkoor
questions** OCR'd from previous years. It features a per-exam **timer**, full
**navigation**, post-exam **review**, and a **score tracker with charts**.

---

## ✨ Features

| | |
|---|---|
| 🤖 **AI-generated exams** | Fresh 25/30-question exams written by OpenAI in konkoor style (grammar, vocabulary, cloze, reading). |
| 📚 **Real past exams** | A question bank built by OCR-ing scanned past konkoor booklets, with correct answers taken from the official answer keys. |
| ⏱ **Custom timer** | The user picks the time limit (e.g. 20 min). The exam **auto-closes** when time runs out — even across bot restarts. |
| 🔢 **Full navigation** | Next / Back, plus a jump-grid to go to any question number. |
| 🧩 **4 options always** | Every question has exactly four options (A–D). |
| 📖 **Passage handling** | Reading/cloze passages stay visible while you answer their questions; the answered question is replaced as you move on (single in-place message). |
| 🔍 **Review mode** | After question 30 (or on finish/timeout) review every answer — correct option + explanation — and jump to any question. |
| 📊 **Score tracker** | Progress line chart, per-skill accuracy bars, and a result donut (matplotlib). |
| 🗄 **Professional data model** | PostgreSQL + SQLAlchemy 2.0 + **Alembic** migrations. State is DB-backed, so restarts never lose an exam. |
| 🌱 **Seeded on deploy** | The extracted question bank ships as a JSON artifact seeded by an Alembic **data migration** — `docker compose up` reproduces the full bank with no PDFs or API calls on the server. |

---

## 🚀 Quick start

```bash
cp .env.example .env       # fill in TELEGRAM_BOT_TOKEN and OPENAI_API_KEY
docker compose up -d --build
```

That's it. On startup the bot container:

1. waits for PostgreSQL,
2. runs `alembic upgrade head` (creates the schema **and** seeds the question bank),
3. starts polling Telegram.

Open Telegram, message your bot, and send `/start`.

```bash
docker compose logs -f bot   # follow logs
docker compose down          # stop (database volume is kept)
```

---

## 🧱 Architecture

```
app/
├── config.py              # env-driven settings (pydantic-settings)
├── db/
│   ├── base.py            # async engine + session factory
│   ├── models.py          # users, passages, questions, exam_sessions, session_questions
│   └── repositories.py    # async data-access helpers
├── services/
│   ├── openai_client.py   # OpenAI exam generation (structured output)
│   ├── exam_service.py    # build a session from the bank or via AI
│   └── charts.py          # matplotlib score visualisations
├── bot/
│   ├── main.py            # wiring, startup timer recovery, polling
│   ├── keyboards.py       # inline keyboards (options, nav, jump grid, review)
│   ├── render.py          # HTML message rendering
│   └── handlers/          # start, exam (setup+nav+timer), review, stats
├── ingestion/
│   ├── answer_keys.py     # parse text answer-key PDFs → {q: option}
│   ├── ocr.py             # OpenAI vision OCR of scanned booklets
│   └── ingest.py          # orchestrator / CLI → seed JSON
└── data/
    ├── answer_keys.json   # real keys extracted from the PDFs (committed)
    └── seed/question_bank.json   # the bank seeded by migration 0002
alembic/                   # 0001 schema, 0002 seed-from-JSON
docker/entrypoint.sh       # wait-for-db → migrate → run
```

### Data model

- **users** — Telegram users.
- **passages** — reading/cloze texts shared by many questions.
- **questions** — one 4-option question (`origin` = `bank` or `ai`), optional `passage_id`, `skill_type`, `correct_index`.
- **exam_sessions** — one attempt: chosen duration, `deadline_at`, status, score, and the Telegram message coordinates (for timer / restart recovery).
- **session_questions** — the ordered snapshot of questions in a session plus the user's answer and correctness.

---

## 📥 Building the real question bank (ingestion)

The past-exam **question booklets are scanned images**, while the **answer keys
are text**. The pipeline therefore:

1. parses the text answer keys → `app/data/answer_keys.json` (already committed —
   11 years, questions 1–30),
2. OCRs the scanned booklets with OpenAI vision to recover the question text and
   four options,
3. attaches the correct option from the matching answer key,
4. writes `app/data/seed/question_bank.json`.

Run it locally (needs the `exams/` PDFs, deps installed, and `OPENAI_API_KEY`):

```bash
make install                 # one-time: local venv + deps
make ingest                  # OCR all booklets that have a matching key
# or target specific years / keep questions without a key:
make ingest ARGS="--years 1399,1396 --allow-unkeyed"
```

Or inside Docker (mounts your local `exams/`):

```bash
make ingest-docker
```

Then commit the updated `app/data/seed/question_bank.json`. On the server,
`docker compose up` (→ `alembic upgrade head`) seeds it automatically. The bot
ships with a small curated sample so it works even before you run ingestion.

> The `exams/` PDFs are **git-ignored** (large scans) and not needed on the
> server once the bank is seeded.

---

## 🛠 Common commands

```bash
make up           # build + start db, migrations, bot
make logs         # tail bot logs
make migrate      # run migrations only
make revision m="add X"   # new autogenerated migration
make ingest       # OCR past exams into the seed bank (local)
make down         # stop
```

---

## ⚙️ Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `OPENAI_API_KEY` | OpenAI key (generation + OCR) |
| `OPENAI_GEN_MODEL` | model for exam generation (default `gpt-4o`) |
| `OPENAI_OCR_MODEL` | vision model for OCR (default `gpt-4o`) |
| `POSTGRES_*` | database connection |
| `DEFAULT_NUM_QUESTIONS` | default exam length |
| `TIME_OPTIONS_MINUTES` | offered timer durations, e.g. `10,15,20,30` |

> ⚠️ **Security:** never commit `.env`. If a token/key was ever shared in plain
> text (chat, screenshot, etc.), **rotate it** — regenerate the Telegram token
> via @BotFather and the OpenAI key in the OpenAI dashboard.
