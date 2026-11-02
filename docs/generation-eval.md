# Generation eval: login and sign-up

Do the tests TestSphere writes for a login or sign-up page catch real bugs, without failing a
healthy site? Produced by `python -m scripts.generation_eval` against the local site in
`tests/fixtures/auth_app.py`; the rule-based planner every run uses, no LLM.

* **Feature checks**: assertions other than "the body is visible" or the page title.
* **Healthy fails**: tests failing on the working site, on the first run and on the next one
  (the account the first run created now exists). Every one blames the site wrongly.
* **Bugs caught**: bugs of that flow where a test that passed on the healthy site fails.
* **CAPTCHA**: tests failing when a CAPTCHA guards the form, which is not a bug; they should
  report that automation is blocked instead.

## Summary

| Scenario | Tests | With a feature check | Healthy fails (run 1 / run 2) | Bugs caught | CAPTCHA fails |
| --- | --- | --- | --- | --- | --- |
| `login-no-goal` | 3 | 0 | 0 / 0 | 0 of 7 (0%) | 0 |
| `login-with-credentials` | 3 | 1 | 0 / 0 | 1 of 7 (14%) | 1 |
| `login-goal-no-credentials` | 3 | 1 | 1 / 1 | 0 of 7 (0%) | 1 |
| `store-login-with-credentials` | 3 | 1 | 0 / 0 | 0 of 7 (0%) | 0 |
| `signup-no-goal` | 3 | 0 | 0 / 0 | 0 of 5 (0%) | 0 |
| `signup-goal` | 3 | 1 | 0 / 1 | 1 of 5 (20%) | 1 |
| **All** | 18 | 4 | 3 | 2 of 38 (5%) | |

## Bugs, by scenario

✔ caught · ✘ missed

| Bug | `login-no-goal` | `login-with-credentials` | `login-goal-no-credentials` | `store-login-with-credentials` |
| --- | --- | --- | --- | --- |
| `login-rejects-valid` — The correct email and password are refused. | ✘ | ✔ | ✘ | ✘ |
| `login-accepts-wrong-password` — Any password signs in. | ✘ | ✘ | ✘ | ✘ |
| `login-no-error-message` — A wrong password shows no error; the form just reloads. | ✘ | ✘ | ✘ | ✘ |
| `login-empty-submit` — Empty fields are not required and sign in. | ✘ | ✘ | ✘ | ✘ |
| `password-visible` — The password field shows what is typed (type=text). | ✘ | ✘ | ✘ | ✘ |
| `session-lost-on-reload` — The account page signs you out when reloaded. | ✘ | ✘ | ✘ | ✘ |
| `logout-broken` — Log out keeps you signed in. | ✘ | ✘ | ✘ | ✘ |

| Bug | `signup-no-goal` | `signup-goal` |
| --- | --- | --- |
| `signup-broken` — Creating an account ends in a server error. | ✘ | ✘ |
| `signup-mismatch-accepted` — Different password and confirmation are accepted. | ✘ | ✘ |
| `signup-invalid-email-accepted` — An email without @ is accepted. | ✘ | ✘ |
| `signup-duplicate-crash` — An email already registered ends in a server error. | ✘ | ✘ |
| `signup-no-confirmation` — Success shows the empty form again, no account made. | ✘ | ✔ |

## Tests, by scenario

### `login-no-goal`

A user gives only the URL. Goal: none.

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass | pass |
| Interaction: Sign in · Acme | 0 | pass | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass | pass |

### `login-with-credentials`

The goal has working credentials. Goal: "log in with demo@testsphere.test / Correct-Horse-7".

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass | pass |
| Scenario: log in with demo@testsphere.test / Correct-Horse-7 | 1 | pass | pass | **fail**: assert_hidden failed: '#password' is still visible |
| Content: heading 'Sign in to your account' | 0 | pass | pass | pass |

### `login-goal-no-credentials`

The goal asks for the login, without credentials. Goal: "test the login".

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass | pass |
| Scenario: test the login | 1 | **fail**: assert_hidden failed: '#password' is still visible | **fail**: assert_hidden failed: '#password' is still visible | **fail**: assert_hidden failed: '#password' is still visible |
| Content: heading 'Sign in to your account' | 0 | pass | pass | pass |

### `store-login-with-credentials`

Working credentials; the page also has a header search form. Goal: "log in with demo@testsphere.test / Correct-Horse-7".

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass | pass |
| Scenario: log in with demo@testsphere.test / Correct-Horse-7 | 1 | pass | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass | pass |

### `signup-no-goal`

A user gives only the URL. Goal: none.

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass | pass |
| Interaction: Create account · Acme | 0 | pass | pass | pass |
| Content: heading 'Create your account' | 0 | pass | pass | pass |

### `signup-goal`

The goal asks for a sign-up. Goal: "sign up as a new user".

| Test | Feature checks | Healthy run 1 | Healthy run 2 | CAPTCHA |
| --- | --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass | pass |
| Scenario: sign up as a new user | 1 | pass | **fail**: assert_hidden failed: '#password' is still visible | **fail**: assert_hidden failed: '#password' is still visible |
| Content: heading 'Create your account' | 0 | pass | pass | pass |
