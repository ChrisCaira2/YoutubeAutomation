"""Settings read from the environment and the git-ignored .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

# Each workspace is its own studio with its own channel, data, topics and playbook, served on its own port.
# The owner added the AI Slop wing on 2026-11-07 for AI-generated videos on a separate YouTube channel.
WORKSPACES = {
    "archive": {"label": "The Athletics Archive", "port": 8000},
    "slop": {"label": "Game Day Brain", "port": 8001},  # the folder and data keep the name "slop"
}
# Wings of the hub that aren't studios, listed in the same switch. The GTA clipper (backend/clipper) was added 2026-11-12.
WINGS = {"clips": {"label": "GTA 6 Clip Central", "port": 8002}}
WORKSPACE = os.getenv("STUDIO_WORKSPACE", "archive")
if WORKSPACE not in WORKSPACES:
    raise SystemExit(f"Unknown workspace {WORKSPACE!r}: use one of {', '.join(WORKSPACES)}")
MODE = os.getenv("STUDIO_MODE", "mock")  # "mock" runs fake providers at no cost; "live" calls Claude
MOCK_SPEED = float(os.getenv("STUDIO_MOCK_SPEED", "1.0"))  # higher = faster mock agents
HUB_DIST = ROOT / "hub" / "dist"

if WORKSPACE == "archive":
    CHANNEL_NAME = "The Athletics Archive"
    HOST_NAME = "Professor Sportington III"
    PITCH = "a YouTube channel about the biggest moments in sports history, hosted by an illustrated character, Professor Sportington III"
    # The owner's call, 2026-11-07: cartoon scenes instead of real photos, and the Professor opens every long-form video.
    VISUAL_STYLE = "cartoon"
    PROFESSOR_INTRO = True
    VISUAL_RULES = ("cartoon scenes of the key moments (faceless players in team colors acting out what happened), animated charts that build on screen, "
                    "moving play diagrams, timelines, scoreboards, and {host} on screen at chapter resets. He opens every long video with his own welcome, "
                    "so don't write one. When a beat describes a sequence on the field, say plainly where each step happened (first base, the left corner, "
                    "the 20-yard line), since those words become a moving diagram; when it covers events over time, give the dates. Never an AI-made "
                    "likeness of a real person, never a team or league logo, never broadcast footage.")
    RECIPE = {
        "subject": "moment",
        "research": ("- Include the key moments on the field in the order they happened: who did what, and where on the field or court (the yard line, the base, the spot "
                     "on the floor). The video acts these out as cartoon scenes, so the plays fans remember most must be in your facts.\n"
                     "- Include facts that support the \"how unlikely was it\" angle (odds, records, margins, how long a record stood)."),
        "look": "the colors and format of this video's slides, built around the team or country at the center of this moment",
        "thumbnail_rule": "the professor, one big number or scoreline, a faceless silhouette; never an athlete's face or photo, never a team or league logo",
        "shape": ("Hook in the first 30 seconds, no greeting: beat 1 proves the title with one concrete number or claim (about 10 s), then why it matters, then a "
                  "one-line roadmap. First payoff before 0:30. Re-hook near 3:00. Open 1 to 3 loops and close them; a strong payoff mid-video, not only at the end. "
                  "End with a specific bridge to another big moment, not a subscribe plea."),
        "host": f"{HOST_NAME}, the channel's illustrated host",
        "voice": "warm, witty, precise American English, like a favorite professor narrating a thriller",
        "originality": "it adds real analysis (the 'how unlikely' angle) beyond a recap of the highlight",
    }
    # Live runs keep their own database so demo data never mixes with real work.
    DB_PATH = os.getenv("STUDIO_DB", str(ROOT / "data" / ("studio-live.db" if MODE == "live" else "studio.db")))
    MEDIA_DIR = Path(os.getenv("STUDIO_MEDIA_DIR", ROOT / "media"))
    STRATEGY_DIR = ROOT / "strategy"
    TOPICS_FILE = STRATEGY_DIR / "topics.md"
    PLAYBOOK_FILE = ROOT / "playbook" / "playbook.json"
else:
    WORKSPACE_DIR = ROOT / "workspaces" / WORKSPACE
    CHANNEL_NAME = "Game Day Brain"  # the owner named it on 2026-11-09; it was "AI Slop" before
    HOST_NAME = "the narrator"
    # Modeled on youtube.com/@Dogunee97 at the owner's request, 2026-11-09: sketch-style AI pictures and numbered list scripts, about sports.
    PITCH = ("a YouTube channel about the science and psychology of sports, for fans and players: what really happens in your brain and body, "
             "told as numbered lists over hand-drawn AI sketches, narrated by an unseen storyteller")
    VISUAL_STYLE = "sketch"
    PROFESSOR_INTRO = False
    VISUAL_RULES = ("a hand-drawn sketch for each moment: an everyday scene a fan or player would recognize, with the channel's mascot fan when the viewer is the subject. "
                    "Describe who is in it, what they're doing and where. Never a real, identifiable person, never a logo, team name or trademark.")
    RECIPE = {
        "subject": "topic",
        "research": ("- This channel explains the science and psychology behind sports: what happens in the brains and bodies of fans and players, and why. Find the "
                     "real studies and named ideas behind the topic: who found what, when, in how many people, and where it was published. Prefer the studies "
                     "themselves, university pages and respected science journalism.\n"
                     "- Never overstate a finding: say what a study measured and in whom, and say when the evidence is mixed or comes from one small study.\n"
                     "- Gather 5 to 9 distinct, well-supported points that could each be a numbered item, each with an everyday moment a fan or player would recognize."),
        "look": "the slide colors; this channel uses one fixed look, so set team to \"none\", primary #1C1C1C, secondary #E0312B, highlight #F5C518, background light, texture plain and font condensed",
        "thumbnail_rule": "a short headline of up to 5 words in black capitals with one word in a red box, beside the mascot fan; never a real person, never a team or league logo",
        "shape": ("A numbered list video. Beat 1 opens straight on the viewer in the second person, with a claim that reframes something they've felt or seen "
                  "(\"Your brain doesn't experience a loss the way you think it does\"), then one line on why it's real, then the promise of the list and a tease of "
                  "one item by number (\"stay for number four\"). No greeting. Then 5 to 9 numbered items. Each item's first beat opens with its number and a plain "
                  "title spoken as a sentence (\"Four. You remember the losses longer than the wins.\"), and that beat's on_screen_text is the number and title, "
                  "like \"4. You remember the losses longer\". Inside each item: a concrete moment the viewer will recognize, told in the second person; the named "
                  "idea behind it and what the research found; a comparison that makes it click; then a one-line payoff that lands the feeling. Put the strongest "
                  "item at the teased number. End with a warm line that sends the viewer back to their own experience, then a bridge to another planned video."),
        "host": "an unseen narrator",
        "voice": "calm, warm, plain American English, like a friend who has read the research explaining it over coffee",
        "originality": ("it gives real insight from named research, honest about each study's size and limits, beyond generic sports advice; "
                        "each numbered item is distinct, and the list isn't a template filled in"),
    }
    DB_PATH = os.getenv("STUDIO_DB", str(ROOT / "data" / (f"{WORKSPACE}-live.db" if MODE == "live" else f"{WORKSPACE}.db")))
    MEDIA_DIR = Path(os.getenv("STUDIO_MEDIA_DIR", ROOT / "media" / WORKSPACE))
    STRATEGY_DIR = WORKSPACE_DIR
    TOPICS_FILE = WORKSPACE_DIR / "topics.md"
    PLAYBOOK_FILE = WORKSPACE_DIR / "playbook.json"

DEFAULT_SETTINGS = {
    "paused": False,
    "daily_budget_usd": float(os.getenv("DAILY_BUDGET_USD", "2")),
    "per_video_budget_usd": float(os.getenv("PER_VIDEO_BUDGET_USD", "2")),
    "approve_first_n": 3,  # after this many approvals, packaged videos auto-approve
    "mock_feed": MODE == "mock",  # in mock mode, keep a few jobs flowing so the hub has activity
    "manual_script_review": MODE == "live",  # you review scripts instead of the QA agent (QA-1 paused)
    "tts_voice": "am_michael",  # narrator: am_michael, am_adam, am_eric or am_onyx
}

# Stages where live jobs wait for you. At qa_video you watch the preview, then start Packaging, a paid step.
# At scheduled the video is approved and you upload it yourself: the Publisher isn't built.
LIVE_HALT_STAGES = {"qa_video", "scheduled"}
