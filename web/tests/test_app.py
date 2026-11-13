"""The app builds and binds safely by default (no model, no servers)."""

from farm_web.app import EXAMPLES, build_app, parse_args


def test_app_builds(tmp_path):
    app = build_app(tmp_path / "audit.jsonl")
    assert app.title == "Precision Farm"


def test_localhost_only_by_default():
    assert parse_args([]).lan is False
    assert parse_args(["--lan"]).lan is True


def test_examples_are_the_eval_questions():
    assert sum(len(qs) for _, qs in EXAMPLES) == 10  # eval 10 is a refusal, left out
