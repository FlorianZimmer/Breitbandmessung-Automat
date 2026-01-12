import breitbandmessung_automate_stateful as bbm


def test_enforce_calendar_gap_default_enabled():
    args = bbm.build_arg_parser().parse_args([])
    assert args.enforce_calendar_gap is True


def test_enforce_calendar_gap_can_be_disabled():
    args = bbm.build_arg_parser().parse_args(["--no-enforce-calendar-gap"])
    assert args.enforce_calendar_gap is False


def test_wait_calendar_gap_default_disabled():
    args = bbm.build_arg_parser().parse_args([])
    assert args.wait_calendar_gap is False


def test_run_forever_default_disabled():
    args = bbm.build_arg_parser().parse_args([])
    assert args.run_forever is False


def test_try_read_ui_progress_default_enabled():
    args = bbm.build_arg_parser().parse_args([])
    assert args.try_read_ui_progress is True


def test_try_read_ui_progress_can_be_disabled():
    args = bbm.build_arg_parser().parse_args(["--no-try-read-ui-progress"])
    assert args.try_read_ui_progress is False


def test_ui_progress_sync_enabled_disabled_when_seeding():
    args = bbm.build_arg_parser().parse_args(["--seed-day-done", "0"])
    assert bbm.ui_progress_sync_enabled(args) is False
