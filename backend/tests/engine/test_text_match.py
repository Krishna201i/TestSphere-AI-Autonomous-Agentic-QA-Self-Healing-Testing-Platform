"""assert_text compares text as a reader sees it, and reports a failure briefly."""

from engine.runner import _quote, _text_contains


def test_a_line_break_in_the_page_matches_a_space_in_the_check():
    # inner_text splits a heading at <br>: "The Modern Operating System\nfor National Healthcare"
    page = " ".join("Skip to main content\nThe Modern Operating System\nfor National Healthcare".split())
    assert _text_contains(page, "The Modern Operating System for National")


def test_a_check_that_lost_the_space_of_a_line_break_still_matches():
    page = " ".join("NATIONAL HEALTHCARE COMMAND CENTER\nSmarter Insights.\nHealthier India.".split())
    assert _text_contains(page, "Smarter Insights.Healthier India.")


def test_matching_ignores_case_but_not_missing_words():
    assert _text_contains("Welcome Back", "welcome back")
    assert not _text_contains("Welcome Back", "Welcome Home")
    assert _text_contains("anything", "")  # an empty expectation always held, as before
    assert not _text_contains("Sign in · Patient portal", "CareLink")


def test_a_long_page_is_quoted_by_its_start_and_length():
    short = _quote("Sign in · Patient portal")
    assert short == "'Sign in · Patient portal'"
    long = _quote("word " * 1000)
    assert long.startswith("'word word") and "…' (5,000 characters)" in long and len(long) < 360
    assert "\\n" not in _quote("a\nb")  # never Python's escaped form


def test_hyphenation_does_not_decide_a_match():
    # A goal says "reach the sign-in page"; CareLink's page says "Sign in"
    page = " ".join("CareLink Patient portal\nWelcome Back\nSign in to your account".split())
    assert _text_contains(page, "sign-in")
    assert _text_contains("Log in with e-mail", "email")
    assert not _text_contains(page, "sign-up")  # a different word still fails
