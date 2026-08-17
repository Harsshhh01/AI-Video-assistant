---
title: AI Video Assistant
emoji: 🎬
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Transcribe, summarise and chat with meeting recordings
---

# AI Video Assistant

Turn a meeting recording or YouTube link into a transcript, a structured
summary, action items with owners, and a chat window answering questions from
only what was actually said.

- **Transcription** — OpenAI Whisper, running in this container
- **Summary & extraction** — Mistral via LangChain, map-reduced for long meetings
- **Grounded chat** — transcript passages embedded into Chroma and retrieved per
  question, so answers cite the recording rather than the model's imagination

## Configuration

This Space needs one secret, set under **Settings → Variables and secrets**:

| Name | Required | Purpose |
|---|---|---|
| `MISTRAL_API_KEY` | yes | Summaries, extraction and chat |
| `SARVAM_API_KEY` | no | Only for the Hinglish option |
| `WHISPER_MODEL` | no | `tiny`/`base`/`small`; the image bakes in `base` |

## Notes on the free CPU tier

- Transcription runs on 2 shared vCPUs, so expect roughly **1.5–3x the
  recording's length**. A 10-minute video takes a while; be patient.
- Analyses are held **in memory**. Restarting or waking the Space clears
  previous results.
- Uploads are capped at 200 MB. For anything larger, paste a link instead.
- Only `base` is preloaded. Selecting a bigger model downloads it on first use.

Audio sent to this Space is processed on Hugging Face's servers, not your own
machine. For fully local processing, run the project yourself — see the source
repository.
