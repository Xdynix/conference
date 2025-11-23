from pathlib import Path
from textwrap import dedent

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from app.conference.models import Keyword, KeywordSet


def write_yaml(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


@pytest.mark.django_db
def test_creates_new_keyword_set(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: Research Topics
        keywords:
          - Machine Learning
          - Artificial Intelligence
          - Data Science
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Research Topics")
    keywords = set(keyword_set.keywords.values_list("text", flat=True))
    assert keywords == {"Machine Learning", "Artificial Intelligence", "Data Science"}


@pytest.mark.django_db
def test_updates_existing_keyword_set(tmp_path: Path) -> None:
    keyword_set = KeywordSet.objects.create(name="Topics")
    kw1 = Keyword.objects.create(text="Python")
    kw2 = Keyword.objects.create(text="Django")
    keyword_set.keywords.set([kw1, kw2])

    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: Topics
        keywords:
          - Python
          - JavaScript
          - TypeScript
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set.refresh_from_db()
    keywords = set(keyword_set.keywords.values_list("text", flat=True))
    assert keywords == {"Python", "JavaScript", "TypeScript"}


@pytest.mark.django_db
def test_handles_empty_keyword_list(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "empty.yaml",
        """
        name: Empty Set
        keywords: []
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Empty Set")
    assert not keyword_set.keywords.exists()


@pytest.mark.django_db
def test_handles_missing_keywords_field(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "minimal.yaml",
        """
        name: Minimal Set
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Minimal Set")
    assert not keyword_set.keywords.exists()


@pytest.mark.django_db
def test_strips_whitespace_from_keywords(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: Topics
        keywords:
          - "  Python  "
          - " Django"
          - "Flask "
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Topics")
    keywords = set(keyword_set.keywords.values_list("text", flat=True))
    assert keywords == {"Python", "Django", "Flask"}


@pytest.mark.django_db
def test_ignores_empty_keywords(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: Topics
        keywords:
          - Python
          - "  "
          - ""
          - Django
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Topics")
    keywords = set(keyword_set.keywords.values_list("text", flat=True))
    assert keywords == {"Python", "Django"}


@pytest.mark.django_db
def test_sanitizes_names_and_keywords(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: "  Research\u00a0Topics  "
        keywords:
          - " AI\u200b "
          - "  data   science "
          - "  "
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    keyword_set = KeywordSet.objects.get(name="Research Topics")
    keywords = set(keyword_set.keywords.values_list("text", flat=True))
    assert keywords == {"AI", "data science"}


@pytest.mark.django_db
def test_loads_multiple_keyword_sets(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "topics.yaml",
        """
        name: Topics
        keywords:
          - Python
          - Django
        """,
    )
    write_yaml(
        tmp_path / "types.yaml",
        """
        name: Types
        keywords:
          - Academic
          - Industry
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    assert KeywordSet.objects.count() == 2
    assert KeywordSet.objects.filter(name="Topics").exists()
    assert KeywordSet.objects.filter(name="Types").exists()


@pytest.mark.django_db
def test_reuses_existing_keyword_objects(tmp_path: Path) -> None:
    Keyword.objects.create(text="Python")

    write_yaml(
        tmp_path / "set1.yaml",
        """
        name: Set 1
        keywords:
          - Python
          - Django
        """,
    )
    write_yaml(
        tmp_path / "set2.yaml",
        """
        name: Set 2
        keywords:
          - Python
          - Flask
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    assert Keyword.objects.filter(text="Python").count() == 1


@pytest.mark.django_db
def test_duplicate_keyword_set_names_non_strict(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_yaml(
        tmp_path / "a.yaml",
        """
        name: Duplicate
        keywords:
          - First
        """,
    )
    write_yaml(
        tmp_path / "b.yaml",
        """
        name: Duplicate
        keywords:
          - Second
        """,
    )

    call_command("load_keywords", str(tmp_path), strict=False)

    captured = capsys.readouterr()
    assert "Duplicate keyword set name 'Duplicate'" in captured.err


@pytest.mark.django_db
def test_duplicate_keyword_set_names_strict(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "a.yaml",
        """
        name: Duplicate
        keywords:
          - First
        """,
    )
    write_yaml(
        tmp_path / "b.yaml",
        """
        name: Duplicate
        keywords:
          - Second
        """,
    )

    with pytest.raises(CommandError, match="Duplicate keyword set name 'Duplicate'"):
        call_command("load_keywords", str(tmp_path), strict=True)


@pytest.mark.django_db
def test_missing_name_field(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "invalid.yaml",
        """
        keywords:
          - Python
          - Django
        """,
    )

    with pytest.raises(CommandError):
        call_command("load_keywords", str(tmp_path), strict=True)


@pytest.mark.django_db
def test_empty_name_field(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "invalid.yaml",
        """
        name: ""
        keywords:
          - Python
        """,
    )

    with pytest.raises(CommandError):
        call_command("load_keywords", str(tmp_path), strict=True)


@pytest.mark.django_db
def test_invalid_keywords_type(tmp_path: Path) -> None:
    write_yaml(
        tmp_path / "invalid.yaml",
        """
        name: Test
        keywords: "not a list"
        """,
    )

    with pytest.raises(CommandError):
        call_command("load_keywords", str(tmp_path), strict=True)
