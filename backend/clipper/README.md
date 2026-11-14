# GTA clipper

Long GTA 6 streams and VODs go in, and vertical Shorts and TikToks come out. It's the third wing of the hub, next to The Athletics Archive and Game Day Brain, and it keeps its own database (`data/clips.db`), media (`media/clips`) and log (`data/clips.log`).

Each stage runs on its own and passes its work along through SQLite and files, so any stage can be re-run or swapped. Every tunable is in [`config.toml`](config.toml).

| # | Stage | Status |
|---|---|---|
| 1 | Ingest: VODs (yt-dlp), live streams (streamlink, in 5-minute pieces), chat (chat-downloader) | built |
| 2 | Transcription: faster-whisper, word times, one piece at a time | built |
| 3 | Highlight detection: loudness, raised voice, scene cuts (ffmpeg, faster than PySceneDetect), speech speed, hype phrases, chat speed and emotes | built |
| 4 | Judging and packaging: Claude picks the clips, word-boundary cuts, title, caption, hashtags, within the monthly cap | built |
| 5 | Editing: 9:16 facecam over gameplay (or gameplay over a blur), word-pop captions, a credit to the streamer, −14 LUFS | built |
| 6 | Review in Clip Central: approve or reject, trim, fix the facecam box, set each creator's permission and watch | built |
| 7 | Upload: YouTube Data API and TikTok Content Posting API, private first | milestone 5 |

## Setup

`./run.sh` installs everything in `backend/requirements.txt` into `.venv`. ffmpeg has to be on the PATH (`brew install ffmpeg`). The Whisper model (`base.en`) is shared with the studios in `models/whisper`.

No credentials are needed for milestones 1 and 2, apart from the `ANTHROPIC_API_KEY` that's already in `.env`. Upload credentials (a Google Cloud OAuth client and a TikTok developer app) will go in `.env` at milestone 5, never in `config.toml`.

## Running it

From the project folder:

```bash
./run.sh clip ingest https://www.twitch.tv/videos/123456789     # a VOD: downloads at 720p, then its chat replay
./run.sh clip ingest https://www.twitch.tv/somestreamer         # live now: records until the stream ends (Ctrl+C stops)
./run.sh clip ingest ~/Movies/recording.mp4 --creator "Name"    # a file on this Mac (never moved or trashed)
./run.sh clip transcribe                                        # every piece not yet transcribed
./run.sh clip transcribe --follow                               # keep going as live pieces arrive
./run.sh clip creator add https://www.twitch.tv/somestreamer --watch --permission permitted
./run.sh clip watch                                             # record watched creators when they go live with GTA
./run.sh clip status
./run.sh clip detect --source 1                                 # moments from the free signals
./run.sh clip judge --source 1                                  # Claude picks and titles them (about 2¢ per 6 moments)
./run.sh clip candidates --source 1 --all                       # the ranked list, also in media/clips/sources/00001/candidates.json
./run.sh clip edit --source 1                                   # picks become vertical clips in media/clips/out
./run.sh clip edit --moment 23                                  # or one pick
./run.sh clip sweep                                             # fully clipped sources from a week ago go to the Trash
./run.sh clip spend
```

## Editing

- **Facecam:** Claude finds the streamer's camera once per source from 3 frames (about 1¢). Code then snaps each side onto the camera's real border: the line where the still room inside meets the moving game outside. The box is saved on the source. A source without a facecam gets the gameplay over a blurred copy of itself.
- **Captions:** this ffmpeg has no text filters, so captions are drawn with Pillow and laid on top. Up to 3 words at a time, with the word being said in yellow and popping in 18% larger. They sit at 80% of the height: below GTA's mid-screen banners, above its own subtitles. Swear words are starred in the captions only (`[captions] censor`).
- **Two traps found building it:** ffmpeg's image-list reader keeps time in 1/25 s steps, and a track whose images change size breaks the overlay. Both made captions vanish silently, so every caption change lands on that grid and every image is the same size.
- **Loudness:** two-pass loudnorm to −14 LUFS. When a shout far above the talking stops it short, the gain is raised behind a peak limiter.

## The hub

`./run.sh live` starts the clipper's wing at http://127.0.0.1:8002, listed in the hub's switch beside the two studios. It shows the pipeline, the watched creators with a Record box, the top moments, spend and disk, and the posting schedule. Its **automation** switch starts off. When it's on, the wing checks the watch list every 2 minutes, records GTA streams, and transcribes, detects and judges as pieces arrive. It turns itself off if the monthly cap would be passed.

Running `ingest` again with the same video (even under a different link) returns the source that's already there, and finished pieces are never transcribed twice. Creators start with permission `unknown`, and their clips carry a warning until you mark them `permitted`.

## Platform notes

- **Chat:** live chat from Twitch and YouTube, and YouTube chat replays, come through chat-downloader. Twitch VODs have no chat: Twitch's public API offers no replay, and the private one the library relied on stopped working. Kick's chat isn't supported either. Sources without chat rely on audio and transcript signals.
- **Part of a VOD:** `--start 2:31:57 --length 30m` (or a link with `?t=`) downloads only that window, and its chat and clip times still point back into the full VOD.
- **Going live:** `watch` checks each watched creator every 2 minutes with yt-dlp, so no Twitch developer app is needed. A stream is only recorded when its title mentions a word in `game_keywords`.
- **Disk:** a recorded hour at 720p is about 1.5 GB. Downloaded and recorded sources move to the Trash 7 days after their last clip, once every pick is edited (`source_trash_days`). Words, moments and clips stay.

## Tests

`./run.sh test` runs everything. `tests/test_clipper.py` uses `tests/fixtures/sample-stream.mp4`, a 22-second stream with a facecam box and one shouted moment, drawn by `python -m clipper.fixture`. A stand-in for streamlink plays the sample as a live feed, so the live-recording test needs no network.

## Review

Click a clip's poster in **Top moments** to review it:
- **Approve** or **Reject** it. Either can be undone until it's posted. Approved clips are what milestone 5 uploads.
- **Trim** its start or end by a second at a time. A cut that lands inside a word moves to that word's edge, and the clip is made again (about 10 s). It goes back to waiting for your review.
- **Fix the facecam box** by dragging over the camera on a frame from the stream. Saving remakes that stream's clips. **No facecam** switches them to gameplay over a blur.

In **Live**, each creator has a permission setting (Permitted, No permission, Refused) and a Watch switch. Clips from creators who aren't marked Permitted carry a warning, and uploading them is your call.
