from subprocess import CompletedProcess

import pytest

from csvql.exceptions import CSVQLError
from csvql.tui_native_picker import choose_csv_paths_with_native_picker


def test_native_picker_rejects_non_macos_platform() -> None:
    with pytest.raises(CSVQLError, match="only available on macOS"):
        choose_csv_paths_with_native_picker(platform="linux")


def test_native_picker_runs_osascript_without_shell() -> None:
    seen: dict[str, object] = {}

    def fake_run(args, *, check, capture_output, text):
        seen["args"] = args
        seen["check"] = check
        seen["capture_output"] = capture_output
        seen["text"] = text
        return CompletedProcess(
            args=args, returncode=0, stdout="/tmp/a.csv\n/tmp/b.csv\n", stderr=""
        )

    paths = choose_csv_paths_with_native_picker(platform="darwin", run_command=fake_run)

    assert paths == ("/tmp/a.csv", "/tmp/b.csv")
    assert isinstance(seen["args"], list)
    assert seen["args"][0] == "osascript"
    assert "-e" in seen["args"]
    assert seen["check"] is False
    assert seen["capture_output"] is True
    assert seen["text"] is True


def test_native_picker_treats_user_cancel_as_empty_selection() -> None:
    def fake_run(args, *, check, capture_output, text):
        return CompletedProcess(args=args, returncode=1, stdout="", stderr="User canceled.")

    assert choose_csv_paths_with_native_picker(platform="darwin", run_command=fake_run) == ()


def test_native_picker_maps_missing_osascript_to_csvql_error() -> None:
    def fake_run(args, *, check, capture_output, text):
        raise FileNotFoundError("osascript")

    with pytest.raises(CSVQLError) as exc_info:
        choose_csv_paths_with_native_picker(platform="darwin", run_command=fake_run)

    assert exc_info.value.message == "Native CSV picker is unavailable."
    assert exc_info.value.suggestion == "Use Add source and paste a CSV path instead."


def test_native_picker_maps_non_cancel_failure_to_csvql_error() -> None:
    def fake_run(args, *, check, capture_output, text):
        return CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="execution error: missing entitlement",
        )

    with pytest.raises(CSVQLError) as exc_info:
        choose_csv_paths_with_native_picker(platform="darwin", run_command=fake_run)

    assert exc_info.value.message == "Native CSV picker failed."
    assert exc_info.value.suggestion == "Use Add source and paste a CSV path instead."
