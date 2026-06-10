from pathlib import Path

import pytest

from coding_agent.swebench.sandbox_run import parse_instance_id_file


def test_parse_instance_id_file_ignores_blank_lines_and_comments(tmp_path: Path):
    path = tmp_path / "instances.txt"
    path.write_text(
        "\n".join(
            [
                "# smoke batch",
                "",
                "django__django-11099",
                "   ",
                "django__django-11100  ",
            ]
        ),
        encoding="utf-8",
    )

    assert parse_instance_id_file(path) == ("django__django-11099", "django__django-11100")


def test_parse_instance_id_file_rejects_empty_files(tmp_path: Path):
    path = tmp_path / "instances.txt"
    path.write_text("# only comments\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="instance-id-file"):
        parse_instance_id_file(path)
