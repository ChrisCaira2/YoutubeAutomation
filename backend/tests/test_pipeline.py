import pytest

from studio.pipeline import CHANGE_TARGETS, ROUTES, STAGES, IllegalTransition, allowed_targets, check_transition, next_stage


def test_every_route_advances_one_stage():
    for stage, route in ROUTES.items():
        assert route.on_success == next_stage(stage)


def test_qa_failures_return_to_the_producing_stage():
    assert ROUTES["scripted"].on_fail == "researched"
    assert ROUTES["rendered"].on_fail == "storyboarded"
    for route in ROUTES.values():
        if route.on_fail:
            assert STAGES.index(route.on_fail) < STAGES.index(route.on_success)


def test_only_you_move_jobs_past_approval():
    assert "awaiting_approval" not in ROUTES
    assert allowed_targets("awaiting_approval") == {"scheduled", *CHANGE_TARGETS.values()}


def test_change_requests_go_back_to_an_agent_stage():
    for stage in CHANGE_TARGETS.values():
        assert stage in ROUTES
        assert STAGES.index(stage) < STAGES.index("awaiting_approval")


@pytest.mark.parametrize("src,dst", [("idea", "scripted"), ("researched", "idea"), ("packaged", "scheduled"), ("learned", "idea"), ("idea", "nope")])
def test_illegal_moves_are_refused(src, dst):
    with pytest.raises(IllegalTransition):
        check_transition(src, dst)


def test_legal_moves_pass():
    check_transition("idea", "researched")
    check_transition("scripted", "researched")
    check_transition("awaiting_approval", "qa_video")


def test_preview_can_go_back_to_script_review():
    check_transition("qa_video", "scripted")
