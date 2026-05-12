from pathlib import Path

pytest_plugins = ("pytester",)


def _make_marker_suite(pytester):
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text())
    pytester.makeini(
        """
        [pytest]
        markers =
            live: requires an explicitly configured live Ollama endpoint
            perf: long-running local performance checks
        """
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.live
        def test_quick_live():
            assert True

        @pytest.mark.live
        @pytest.mark.perf
        def test_heavy_perf():
            assert True
        """
    )


def test_live_and_perf_markers_skip_by_default(pytester):
    _make_marker_suite(pytester)

    result = pytester.runpytest("-q")

    result.assert_outcomes(skipped=2)


def test_run_live_with_api_runs_only_quick_live_tests(pytester, monkeypatch):
    _make_marker_suite(pytester)
    monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")

    result = pytester.runpytest("-q", "--run-live")

    result.assert_outcomes(passed=1, skipped=1)


def test_run_live_without_api_still_skips_live_tests(pytester, monkeypatch):
    _make_marker_suite(pytester)
    monkeypatch.delenv("API_URL", raising=False)

    result = pytester.runpytest("-q", "--run-live")

    result.assert_outcomes(skipped=2)


def test_run_live_and_perf_with_api_runs_all_marked_tests(pytester, monkeypatch):
    _make_marker_suite(pytester)
    monkeypatch.setenv("API_URL", "http://localhost:11434/api/chat")

    result = pytester.runpytest("-q", "--run-live", "--run-perf")

    result.assert_outcomes(passed=2)
