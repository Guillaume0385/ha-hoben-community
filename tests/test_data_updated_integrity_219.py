"""#219-A: offline anti-tampering proof runs in the ordinary Python CI."""

import subprocess


def test_new_parser_is_pinned_and_mutation_is_refused():
    result = subprocess.run(
        ["node", "tests/js/data-updated-integrity-219.test.cjs"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
