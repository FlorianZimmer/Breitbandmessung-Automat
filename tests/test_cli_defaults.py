import breitbandmessung_automate_stateful as bbm


def test_enforce_calendar_gap_default_enabled():
    args = bbm.build_arg_parser().parse_args([])
    assert args.enforce_calendar_gap is True


def test_enforce_calendar_gap_can_be_disabled():
    args = bbm.build_arg_parser().parse_args(["--no-enforce-calendar-gap"])
    assert args.enforce_calendar_gap is False

