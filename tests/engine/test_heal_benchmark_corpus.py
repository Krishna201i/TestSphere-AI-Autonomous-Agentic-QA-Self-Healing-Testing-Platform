"""The generated healing-benchmark corpus is well formed (no browser needed)."""

import re

from engine.heal_benchmark import OPERATORS, PAGES, build_cases, find, step_for


def test_every_case_breaks_the_primary_locator_and_marks_the_truth():
    cases = build_cases()
    assert len(cases) >= 250
    assert {c.operator.name for c in cases} == {o.name for o in OPERATORS}
    for case in cases:
        primary = step_for(PAGES[case.page], case.target).target.primary_locator
        testid = re.search(r'data-testid="([^"]+)"', primary).group(1)
        assert f'data-testid="{testid}"' not in case.html, case.name
        assert "data-t=" not in case.html and "data-alt=" not in case.html
        marks = case.probe.count('data-truth="1"')
        assert marks == (1 if case.operator.heal_expected else 0), case.name
        assert case.probe.replace(' data-truth="1"', "") == case.html, case.name


def test_quick_corpus_is_one_target_per_page():
    quick = build_cases(quick=True)
    assert len({(c.page, c.target) for c in quick}) == len(PAGES)
    assert 40 <= len(quick) <= 60


def test_steps_match_the_element_kind():
    assert step_for(PAGES["login"], "email").action.value == "fill"
    assert step_for(PAGES["shop"], "category").action.value == "select"
    assert step_for(PAGES["login"], "remember").action.value == "click"
    _, el = find(PAGES["shop"], "add")
    assert el.attrs["id"] == "add-2"
