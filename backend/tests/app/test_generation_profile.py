"""A project's generation profile steers what the pipeline generates."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
from backend.pipeline.profile import GenerationProfile, profile_of, select, type_of

TESTS = [
    {"slug": "smoke", "category": "smoke", "steps": [{"action": "ASSERT_VISIBLE", "target": "body"}]},
    {"slug": "interaction", "category": "functional",
     "steps": [{"action": "CLICK", "target": "#go"}, {"action": "ASSERT_URL", "value": "/done"}]},
    {"slug": "login-wrong-password", "category": "functional", "steps": [{"action": "ASSERT_VISIBLE", "target": "#pw"}]},
    {"slug": "form-invalid-email", "category": "functional", "steps": [{"action": "ASSERT_VISIBLE", "target": "#e:invalid"}]},
    {"slug": "content", "category": "content", "steps": [{"action": "ASSERT_CONTAINS_TEXT", "target": "h1", "value": "Hi"}]},
    {"slug": "link-about", "category": "link", "steps": [{"action": "ASSERT_VISIBLE", "target": "body"}]},
    {"slug": "ai-1", "category": "ai", "steps": [{"action": "ASSERT_VISIBLE", "target": "#a"}]},
    {"slug": "ai-2", "category": "ai", "steps": [{"action": "ASSERT_VISIBLE", "target": "#b"}]},
]


def test_each_planned_test_has_a_type():
    assert [type_of(t) for t in TESTS[:6]] == ["smoke", "functional", "negative", "negative", "content", "pages"]


def test_the_default_profile_keeps_everything():
    assert [t["slug"] for t in select(TESTS, GenerationProfile())] == [t["slug"] for t in TESTS]
    assert profile_of({}) == GenerationProfile() and profile_of({"generation_profile": {"max_ai_tests": "x"}}) == GenerationProfile()


def test_types_strict_and_the_ai_limit_narrow_the_suite():
    profile = GenerationProfile(test_types=["functional", "negative"], strict=True, max_ai_tests=1)
    assert [t["slug"] for t in select(TESTS, profile)] == [
        "interaction", "login-wrong-password", "form-invalid-email", "ai-1"]


def test_the_profile_is_saved_and_validated_on_the_project(fresh_store):
    client = TestClient(app)
    project = client.post("/api/projects", json={"name": "Shop", "app_url": "https://shop.example/"}).json()
    profile = {"test_types": ["smoke", "negative"], "test_data": {"text": "laptop", "email": "qa@shop.example"},
               "max_ai_tests": 2, "strict": True, "acceptance": False}
    saved = client.put(f"/api/projects/{project['id']}", json={"generation_profile": profile})
    assert saved.status_code == 200, saved.text
    assert saved.json()["generation_profile"]["test_data"] == {"text": "laptop", "email": "qa@shop.example"}
    assert profile_of(saved.json()).strict is True

    bad = client.put(f"/api/projects/{project['id']}", json={"generation_profile": {"test_data": {"ssn": "1"}}})
    assert bad.status_code == 422 and "test_data keys" in bad.text
    bad = client.put(f"/api/projects/{project['id']}", json={"generation_profile": {"test_types": ["load"]}})
    assert bad.status_code == 422


def test_the_planner_hears_the_profile_but_never_the_password():
    from backend.pipeline.ai_plan import page_context

    analysis = {"url": "https://shop.example/", "page_title": "Shop", "elements_inventory": {}}
    profile = GenerationProfile(test_types=["negative"], test_data={"text": "laptop", "password": "S3cret!"})
    description = page_context(analysis, "search", None, profile).description
    assert "negative" in description and "laptop" in description and "S3cret" not in description


async def test_the_pipeline_keeps_each_tests_acceptance_verdict(fresh_store, monkeypatch):
    from backend.models import TEST_CASES
    from backend.pipeline import acceptance

    async def fake_check(tc, base_url, runner=None):
        return {"steps_key": acceptance.steps_key(acceptance.steps_of(tc)), "status": acceptance.VERIFIED}

    monkeypatch.setattr(acceptance, "check", fake_check)
    import json

    row = fresh_store.insert(TEST_CASES, name="t", description=json.dumps({"steps": [{"action": "ASSERT_VISIBLE",
                                                                                     "target": "#x"}]}))
    counts = await acceptance.check_new_tests(fresh_store, [row], [{"test_case_id": row["id"], "status": "PASSED"}],
                                              "https://shop.example/", limit=5)
    assert counts == {"verified": 1}
    stored = fresh_store.get(TEST_CASES, row["id"])
    assert stored["acceptance"]["status"] == "verified"
    # Checked once: the same steps are not checked again
    assert await acceptance.check_new_tests(fresh_store, [stored], [{"test_case_id": row["id"], "status": "PASSED"}],
                                            "https://shop.example/", limit=5) == {}
