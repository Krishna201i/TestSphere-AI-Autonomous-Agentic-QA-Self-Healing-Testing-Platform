# Generation eval: login and sign-up

Do the tests TestSphere writes for a login or sign-up page catch real bugs, without failing a
healthy site? Produced by `python -m scripts.generation_eval` against the local site in
`tests/fixtures/auth_app.py`; the rule-based planner every run uses, no LLM.

* **Feature checks**: assertions other than "the body is visible" or the page title.
* **Healthy fails**: tests failing on the working site, on the first run and on the next one
  (the account the first run created now exists). Every one blames the site wrongly.
* **Bugs caught**: bugs of that flow where a test that passed on the healthy site fails.
* **CAPTCHA fails**: tests planned on the page with a CAPTCHA on its form, failing there. A
  CAPTCHA is not a bug: the tests should leave out what it blocks and say so, not fail.

## Summary

| Scenario | Tests | With a feature check | Healthy fails (run 1 / run 2) | Bugs caught | CAPTCHA fails |
| --- | --- | --- | --- | --- | --- |
| `login-no-goal` | 5 | 3 | 0 / 0 | 3 of 7 (43%) | 0 |
| `login-with-credentials` | 8 | 6 | 0 / 0 | 7 of 7 (100%) | 0 |
| `login-goal-no-credentials` | 5 | 3 | 0 / 0 | 3 of 7 (43%) | 0 |
| `store-login-with-credentials` | 8 | 6 | 0 / 0 | 7 of 7 (100%) | 0 |
| `signup-no-goal` | 6 | 4 | 0 / 0 | 3 of 5 (60%) | 0 |
| `signup-goal` | 6 | 4 | 0 / 0 | 3 of 5 (60%) | 0 |
| `signup-no-goal-accounts-on` | 8 | 6 | 0 / 0 | 5 of 5 (100%) | 0 |
| `signup-goal-accounts-on` | 8 | 6 | 0 / 0 | 5 of 5 (100%) | 0 |
| **All** | 54 | 38 | 0 | 36 of 48 (75%) | |

## Bugs, by scenario

✔ caught · ✘ missed

| Bug | `login-no-goal` | `login-with-credentials` | `login-goal-no-credentials` | `store-login-with-credentials` |
| --- | --- | --- | --- | --- |
| `login-rejects-valid` — The correct email and password are refused. | ✘ | ✔ | ✘ | ✔ |
| `login-accepts-wrong-password` — Any password signs in. | ✘ | ✔ | ✘ | ✔ |
| `login-no-error-message` — A wrong password shows no error; the form just reloads. | ✔ | ✔ | ✔ | ✔ |
| `login-empty-submit` — Empty fields are not required and sign in. | ✔ | ✔ | ✔ | ✔ |
| `password-visible` — The password field shows what is typed (type=text). | ✔ | ✔ | ✔ | ✔ |
| `session-lost-on-reload` — The account page signs you out when reloaded. | ✘ | ✔ | ✘ | ✔ |
| `logout-broken` — Log out keeps you signed in. | ✘ | ✔ | ✘ | ✔ |

| Bug | `signup-no-goal` | `signup-goal` | `signup-no-goal-accounts-on` | `signup-goal-accounts-on` |
| --- | --- | --- | --- | --- |
| `signup-broken` — Creating an account ends in a server error. | ✔ | ✔ | ✔ | ✔ |
| `signup-mismatch-accepted` — Different password and confirmation are accepted. | ✔ | ✔ | ✔ | ✔ |
| `signup-invalid-email-accepted` — An email without @ is accepted (no check in the page or on the server). | ✔ | ✔ | ✔ | ✔ |
| `signup-duplicate-crash` — An email already registered ends in a server error. | ✘ | ✘ | ✔ | ✔ |
| `signup-no-confirmation` — Success shows the empty form again, no account made. | ✘ | ✘ | ✔ | ✔ |

## Tests, by scenario

### `login-no-goal`

A user gives only the URL. Goal: none.

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass |
| Login: the password is masked | 1 | pass | pass |
| Login: an empty form is not sent | 1 | pass | pass |
| Login: a wrong password is refused with a message | 2 | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Sign in · Acme: pass; Login: the password is masked: pass; Login: an empty form is not sent: pass; Content: heading 'Sign in to your account': pass.

### `login-with-credentials`

The goal has working credentials. Goal: "log in with demo@testsphere.test / Correct-Horse-7".

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass |
| Scenario: log in with demo@testsphere.test / Correct-Horse-7 | 2 | pass | pass |
| Login: the password is masked | 1 | pass | pass |
| Login: an empty form is not sent | 1 | pass | pass |
| Login: a wrong password is refused with a message | 2 | pass | pass |
| Login: the session survives a reload | 2 | pass | pass |
| Login: logging out ends the session | 3 | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Sign in · Acme: pass; Login: the password is masked: pass; Login: an empty form is not sent: pass; Content: heading 'Sign in to your account': pass.

### `login-goal-no-credentials`

The goal asks for the login, without credentials. Goal: "test the login".

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass |
| Login: the password is masked | 1 | pass | pass |
| Login: an empty form is not sent | 1 | pass | pass |
| Login: a wrong password is refused with a message | 2 | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Sign in · Acme: pass; Login: the password is masked: pass; Login: an empty form is not sent: pass; Content: heading 'Sign in to your account': pass.

### `store-login-with-credentials`

Working credentials; the page also has a header search form. Goal: "log in with demo@testsphere.test / Correct-Horse-7".

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Sign in · Acme | 0 | pass | pass |
| Scenario: log in with demo@testsphere.test / Correct-Horse-7 | 2 | pass | pass |
| Login: the password is masked | 1 | pass | pass |
| Login: an empty form is not sent | 1 | pass | pass |
| Login: a wrong password is refused with a message | 2 | pass | pass |
| Login: the session survives a reload | 2 | pass | pass |
| Login: logging out ends the session | 3 | pass | pass |
| Content: heading 'Sign in to your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Sign in · Acme: pass; Login: the password is masked: pass; Login: an empty form is not sent: pass; Content: heading 'Sign in to your account': pass.

### `signup-no-goal`

A user gives only the URL. Goal: none.

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass |
| Sign-up: the password is masked | 1 | pass | pass |
| Sign-up: an empty form is not sent | 1 | pass | pass |
| Sign-up: different passwords are refused | 2 | pass | pass |
| Sign-up: an invalid email is refused | 2 | pass | pass |
| Content: heading 'Create your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Create account · Acme: pass; Sign-up: the password is masked: pass; Sign-up: an empty form is not sent: pass; Content: heading 'Create your account': pass.

### `signup-goal`

The goal asks for a sign-up. Goal: "sign up as a new user".

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass |
| Sign-up: the password is masked | 1 | pass | pass |
| Sign-up: an empty form is not sent | 1 | pass | pass |
| Sign-up: different passwords are refused | 2 | pass | pass |
| Sign-up: an invalid email is refused | 2 | pass | pass |
| Content: heading 'Create your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Create account · Acme: pass; Sign-up: the password is masked: pass; Sign-up: an empty form is not sent: pass; Content: heading 'Create your account': pass.

### `signup-no-goal-accounts-on`

A user gives only the URL; the project allows test accounts. Goal: none.

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass |
| Interaction: Create account · Acme | 2 | pass | pass |
| Sign-up: the password is masked | 1 | pass | pass |
| Sign-up: an empty form is not sent | 1 | pass | pass |
| Sign-up: different passwords are refused | 2 | pass | pass |
| Sign-up: an invalid email is refused | 2 | pass | pass |
| Sign-up: an email already registered is refused | 5 | pass | pass |
| Content: heading 'Create your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Create account · Acme: pass; Sign-up: the password is masked: pass; Sign-up: an empty form is not sent: pass; Content: heading 'Create your account': pass.

### `signup-goal-accounts-on`

The goal asks for a sign-up; the project allows test accounts. Goal: "sign up as a new user".

| Test | Feature checks | Healthy run 1 | Healthy run 2 |
| --- | --- | --- | --- |
| Smoke: Create account · Acme | 0 | pass | pass |
| Scenario: sign up as a new user | 2 | pass | pass |
| Sign-up: the password is masked | 1 | pass | pass |
| Sign-up: an empty form is not sent | 1 | pass | pass |
| Sign-up: different passwords are refused | 2 | pass | pass |
| Sign-up: an invalid email is refused | 2 | pass | pass |
| Sign-up: an email already registered is refused | 5 | pass | pass |
| Content: heading 'Create your account' | 0 | pass | pass |

With a captcha on the form: Smoke: Create account · Acme: pass; Sign-up: the password is masked: pass; Sign-up: an empty form is not sent: pass; Content: heading 'Create your account': pass.
