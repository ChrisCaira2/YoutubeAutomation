"""Job lifecycle: stages, who works each stage, and which moves are legal.

A job's stage is the last milestone it completed. Blocked/failed/done live in
`jobs.status`, so a blocked job keeps its stage and can resume from it.
"""
from dataclasses import dataclass

STAGES = [
    "idea",
    "researched",
    "scripted",
    "qa_script",
    "storyboarded",
    "rendered",
    "qa_video",
    "packaged",
    "awaiting_approval",
    "scheduled",
    "published",
    "analyzing",
    "learned",
]

STAGE_LABELS = {
    "idea": "Idea",
    "researched": "Researched",
    "scripted": "Scripted",
    "qa_script": "QA-1 passed",
    "storyboarded": "Storyboarded",
    "rendered": "Rendered",
    "qa_video": "QA-2 passed",
    "packaged": "Packaged",
    "awaiting_approval": "Awaiting approval",
    "scheduled": "Approved",
    "published": "Exported",
    "analyzing": "Analyzing",
    "learned": "Learned",
}

STATUSES = ("active", "blocked", "failed", "done")


@dataclass(frozen=True)
class Route:
    agent: str
    task: str
    produces: str  # artifact kind written on success
    on_success: str  # stage after success
    on_fail: str | None = None  # stage to return to when a QA check fails


# What happens to a job sitting at each stage. `packaged` and
# `awaiting_approval` are handled by the Showrunner and by you.
ROUTES: dict[str, Route] = {
    "idea": Route("research", "Researching and writing the brief", "brief", "researched"),
    "researched": Route("script", "Writing the script", "script", "scripted"),
    "scripted": Route("qa", "QA-1: reviewing the script", "qa_report", "qa_script", on_fail="researched"),
    "qa_script": Route("studio", "Building the storyboard", "storyboard", "storyboarded"),
    "storyboarded": Route("studio", "Rendering the video", "render", "rendered"),
    "rendered": Route("qa", "QA-2: reviewing the render", "qa_report", "qa_video", on_fail="storyboarded"),
    "qa_video": Route("packaging", "Creating title and thumbnail packages", "package", "packaged"),
    "scheduled": Route("publisher", "Exporting final files for upload", "export", "published"),
    "published": Route("publisher", "Collecting performance numbers", "analytics_snapshot", "analyzing"),
    "analyzing": Route("research", "Writing lessons into the Playbook", "lessons", "learned"),
}

# "Request changes" from the approval queue sends the job back to the agent
# that owns that part of the video.
CHANGE_TARGETS = {
    "script": "researched",  # Script agent rewrites
    "visuals": "qa_script",  # Studio agent re-storyboards and re-renders
    "package": "qa_video",  # Packaging agent redoes titles and thumbnails
}


class IllegalTransition(ValueError):
    pass


def next_stage(stage: str) -> str:
    i = STAGES.index(stage)
    if i == len(STAGES) - 1:
        raise IllegalTransition(f"{stage} is the final stage")
    return STAGES[i + 1]


def allowed_targets(stage: str) -> set[str]:
    targets = set()
    if stage != STAGES[-1]:
        targets.add(next_stage(stage))
    route = ROUTES.get(stage)
    if route and route.on_fail:
        targets.add(route.on_fail)
    if stage == "awaiting_approval":
        targets.update(CHANGE_TARGETS.values())
    if stage == "scripted":
        targets.add("idea")  # at script review, you can send it back for deeper research before anything else is made
    if stage == "scheduled":
        targets.add("qa_script")  # an approved video can still get new slides; it comes back for your approval
    if stage == "qa_video":
        targets.add("scripted")  # a previewed video can go back to your script review with new narration
        targets.add("idea")  # or back to research, when it needs more depth
        targets.add("qa_script")  # or back to Studio, for new slides from the same script
        targets.add("storyboarded")  # or just a new recording and render, which is free
    return targets


def check_transition(src: str, dst: str) -> None:
    if src not in STAGES or dst not in STAGES:
        raise IllegalTransition(f"unknown stage: {src} -> {dst}")
    if dst not in allowed_targets(src):
        raise IllegalTransition(f"cannot move a job from {src} to {dst}")
