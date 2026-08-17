# AI Video Assistant

Turn any meeting recording or YouTube link into a transcript, a structured
summary, action items with owners, and a chat window that answers questions
using only what was actually said.

- **Transcription** — OpenAI Whisper, running locally (English), or Sarvam AI
  speech-to-translate for Hinglish
- **Summary & extraction** — Mistral via LangChain LCEL, map-reduced so long
  meetings don't blow past the context window
- **Grounded chat** — transcript passages embedded into Chroma, retrieved per
  question, so answers cite the meeting rather than the model's imagination
- **Two front ends** — a web app (FastAPI + a static site) and a CLI

---

## Quick start (Windows)

```powershell
cd "$env:USERPROFILE\Desktop\AI Video Project"
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Then:

1. **Install ffmpeg** if setup reported it missing — everything depends on it:
   ```powershell
   winget install Gyan.FFmpeg
   ```
   Close the terminal and open a new one afterwards so `PATH` refreshes.

2. **Add your Mistral API key** to the `.env` file that setup created
   (free tier at <https://console.mistral.ai/api-keys/>):
   ```
   MISTRAL_API_KEY=your_key_here
   ```

3. **Confirm the key works** — one tiny real API call, takes a second:
   ```powershell
   .\.venv\Scripts\python.exe -m app.doctor --live
   ```
   A bad key is reported immediately, so you don't discover it after
   transcribing a whole meeting.

4. **Start it:**
   ```powershell
   .\run.ps1
   ```
   Your browser opens at <http://127.0.0.1:8000>.

Check your environment any time — drop `--live` to skip the API calls and only
check installed packages, ffmpeg and whether keys are present:

```powershell
.\.venv\Scripts\python.exe -m app.doctor --live
```

---

## Using the web app

1. Paste a YouTube URL, **or** switch to the *Upload a file* tab and drop in an
   `mp4` / `mkv` / `mp3` / `wav` (up to 500 MB by default).
2. Pick the spoken language. *English* transcribes locally; *Hinglish* sends the
   audio to Sarvam AI, which translates while it transcribes.
3. Press **Analyse recording**. The six pipeline stages report progress live.
4. When it finishes you get the summary, action items, decisions, open
   questions, the full transcript, and a chat box. **Download report** saves
   everything as markdown.

The status pill in the top-right tells you whether ffmpeg and your API keys are
configured — click it for details.

## Using the CLI

```powershell
.\.venv\Scripts\python.exe -m app.cli "https://www.youtube.com/watch?v=..." --output report.md
```

| Flag | Meaning |
|---|---|
| `--language english\|hinglish` | Transcription engine (default `english`) |
| `--output report.md` | Also write the full markdown report to a file |
| `--no-chat` | Print the analysis and exit instead of opening the Q&A prompt |

---

## How long does it take?

Whisper runs on your CPU, so transcription dominates. Rough guide with the
default `small` model:

| Recording length | Expect |
|---|---|
| 5 minutes | 1–2 minutes |
| 30 minutes | 6–12 minutes |
| 1 hour | 12–25 minutes |

Too slow? Set `WHISPER_MODEL=base` (or `tiny`) in `.env`. Need better accuracy on
accented speech or poor audio? Try `medium`.

The very first run also downloads the Whisper weights (~460 MB for `small`) and
the embedding model (~90 MB). Those are cached afterwards.

---

## Configuration

Everything lives in `.env` — see [`.env.example`](.env.example) for the full
annotated list.

| Variable | Default | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | — | **Required.** Summaries, extraction, chat |
| `SARVAM_API_KEY` | — | Optional; only for Hinglish |
| `WHISPER_MODEL` | `small` | `tiny`/`base`/`small`/`medium`/`large` |
| `MISTRAL_MODEL` | `mistral-small-latest` | Any Mistral chat model |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformer for retrieval |
| `CHUNK_MINUTES` | `10` | Audio slice length for transcription |
| `MAX_UPLOAD_MB` | `500` | Upload size ceiling |

---

## Project layout

```
AI Video Project/
├─ app/
│  ├─ config.py       Loads .env, defines paths, exposes the health snapshot
│  ├─ server.py       FastAPI app: JSON API + serves the website
│  ├─ jobs.py         In-memory job store, one background worker
│  ├─ pipeline.py     The six-stage analysis pipeline (shared by web + CLI)
│  ├─ cli.py          Terminal front end
│  ├─ doctor.py       Environment self-check
│  ├─ core/
│  │  ├─ llm.py         Mistral factory + map-reduce over long transcripts
│  │  ├─ transcriber.py Whisper (local) and Sarvam (API) speech-to-text
│  │  ├─ summarizer.py  Title + summary
│  │  ├─ extractor.py   Action items, decisions, open questions
│  │  ├─ vector_store.py Chroma, one collection per analysis
│  │  └─ rag_engine.py   Retrieval chain for chat
│  └─ utils/
│     └─ audio_processor.py  yt-dlp download, ffmpeg normalise, chunking
├─ web/               index.html · styles.css · app.js · favicon.svg
├─ data/              Uploads, temp audio, vector DB (all gitignored)
├─ requirements.txt
├─ setup.ps1 / run.ps1
└─ .env.example
```

### API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | ffmpeg / key / model status |
| `POST` | `/api/jobs` | Start an analysis (form fields `source`, `language`, `file`) |
| `GET` | `/api/jobs/{id}` | Status, per-step progress, result, chat history |
| `POST` | `/api/jobs/{id}/chat` | `{"question": "..."}` → grounded answer |
| `DELETE` | `/api/jobs/{id}/chat` | Clear chat history |
| `GET` | `/api/jobs/{id}/export` | Markdown report download |
| `DELETE` | `/api/jobs/{id}` | Delete the analysis and its vector collection |

Interactive docs at <http://127.0.0.1:8000/docs> while the server runs.

---

## Deploying it

This is a long-running, CPU-bound service that holds state in memory, so it
needs a container host — **not** a serverless platform. Vercel and similar cannot
run it: their request bodies cap at 4.5 MB (uploads are up to 500 MB here),
invocations are stateless (the job store, the loaded retrieval chain and the
vector index all live in one process), and background work stops when the
response is sent.

A [`Dockerfile`](Dockerfile) is included and works on any container host. See
[`deploy/huggingface/README.md`](deploy/huggingface/README.md) for the Hugging
Face Spaces variant, which is the cheapest way to get a public URL.

```bash
docker build -t ai-video-assistant .
docker run -p 7860:7860 -e MISTRAL_API_KEY=your_key ai-video-assistant
```

The image installs CPU-only torch and bakes the Whisper `base` weights in, so
cold starts do not re-download hundreds of megabytes. Build with
`--build-arg WHISPER_MODEL=small` for better accuracy at 2–3x the runtime.

Environment variables that matter in a container:

| Variable | Why |
|---|---|
| `HOST` / `PORT` | Bind address. Spaces requires `0.0.0.0:7860` |
| `DATA_DIR` | Move scratch space to the only writable path |
| `MAX_UPLOAD_MB` | Lower it — uploads pass through the platform's proxy |

## Privacy

Audio never leaves your machine for English transcription — Whisper runs
locally. The resulting **text** is sent to the Mistral API for summarisation and
to answer chat questions. Hinglish is the exception: that audio is uploaded to
Sarvam AI, which translates as it transcribes.

Uploads and intermediate WAV files are deleted as soon as an analysis finishes.
Transcripts and vector indexes live under `data/` until you delete the analysis
or restart the server.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ffmpeg was not found` | `winget install Gyan.FFmpeg`, then restart the server. The app also looks in the registry PATH and the usual winget/chocolatey install directories, so a terminal opened *before* the install still works |
| Port 8000 in use / server exits at once | An older copy is still running. `run.ps1` names the PID and the command to stop it, or use `.\run.ps1 -Port 8080` |
| `MISTRAL_API_KEY is not set` | Add the key to `.env`, restart the server |
| `Invalid API Key` / 401 from Mistral | Key is wrong or has no credit. Re-check it at <https://console.mistral.ai/api-keys/>, then `python -m app.doctor --live` |
| Whitespace or quotes in `.env` | Write `MISTRAL_API_KEY=abc123` — no quotes, no spaces around `=` |
| Setup fails on `torch` or `chromadb` | You're on Python 3.13+; install 3.11 and re-run `setup.ps1` |
| `HTTP Error 403: Forbidden` on a YouTube link | The app already retries across six player clients automatically. If all six fail, YouTube has changed something: `.\.venv\Scripts\python.exe -m pip install -U yt-dlp` |
| Private / members-only / age-restricted video | Cannot be downloaded at all. Save the audio yourself and use the **Upload a file** tab |
| `Unknown job — it may have expired` | Jobs are in-memory; a server restart clears them |
| Very slow transcription | Lower `WHISPER_MODEL` to `base` or `tiny` in `.env` |
| Port 8000 already in use | `.\run.ps1 -Port 8080` |

---

## Notes on this version

This rewrite replaces the earlier Streamlit prototype. Beyond the new front end,
the following bugs were fixed:

- `.env` was loaded *after* the transcriber module read `SARVAM_API_KEY`, so
  Hinglish never saw the key. All secrets are now read lazily through
  `app/config.py`.
- Chroma reused one persistent collection, so every previously analysed video
  stayed in the index and leaked into later answers. Each analysis now gets its
  own collection, dropped when the analysis is deleted.
- `load_rag_chain()` called `get_retriever()` with no arguments and always
  raised `TypeError`.
- The YouTube download path was guessed with `.replace(".webm", ".wav")`, which
  broke whenever yt-dlp returned any other container. The real path now comes
  back from yt-dlp itself.
- Temporary WAV chunks were never deleted.
- Model output was interpolated into raw HTML, so markdown never rendered and
  the page was open to injection. The front end escapes text before rendering.
- Long transcripts were fed to the extractors in one request; they're now
  map-reduced like the summary.

Found while testing the finished build:

- Printing a `✓` crashed the CLI on Windows, whose console defaults to the
  cp1252 code page. More importantly the same crash applied to any model output
  containing characters outside that code page — Devanagari, emoji — so the
  entry points now switch stdout to UTF-8 and library code stays ASCII.
- The markdown renderer flattened indented sub-bullets, which closed the `<ol>`
  and restarted numbering at 1 for every action item. It now builds properly
  nested lists.
- ffmpeg showed as missing whenever the server was started from a terminal
  opened before ffmpeg was installed — that terminal keeps its old PATH for life
  and every child process inherits it. The app now falls back to the PATH stored
  in the registry plus the usual install directories, and prepends whatever it
  finds to `PATH` so pydub and Whisper can actually execute it. This has to
  happen in `app/__init__.py`, because pydub probes for ffmpeg once at import
  time and caches the result.
- YouTube links failed with `HTTP Error 403: Forbidden`. yt-dlp picked the
  `android_vr` player client, whose media URLs need a PO token, so extraction
  succeeded and the download then 403'd. The downloader now tries six clients in
  turn — verified that `default` and `tv_embedded` both 403 on a real video while
  `android` succeeds. Which client works changes every few weeks, hence the
  chain rather than a hardcoded choice.
- yt-dlp's coloured error text reached the browser as literal
  `[0;31mERROR:[0m`. Errors are now stripped of terminal escape codes before
  being stored on a job, and yt-dlp's own console output is routed to a silent
  logger so a *recovered* attempt no longer prints alarming 403 lines.
- Deleting a job that was still queued removed it from the list but did not stop
  it — the worker held its own reference and ran it anyway.
- `run.ps1` opened the browser before the server had bound its port, showing a
  connection-refused page that looked like a crash. It now waits for
  `/api/health` to answer, and reports the offending PID if the port is taken.
- The action-item prompt reported "No action items found." for a transcript that
  plainly contained one ("Priya will audit the spend before the board call").
  It now treats any stated commitment as an action item, while still reporting
  none when nobody committed to anything.
"# AI-Video-assistant" 
