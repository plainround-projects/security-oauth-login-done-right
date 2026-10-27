# Jinja2 3.1 templates and HTML

## What it is

**HTML** is the markup language of web pages: text with tags such as `<h1>Title</h1>` and `<form>`. A browser reads it and draws the page. A **template** is an HTML file with holes in it. **Jinja2** is the Python library that fills the holes with values at request time. The pinned version is `jinja2==3.1.6`; Flask uses it for `render_template`. Jinja2 depends on `markupsafe` (`3.0.4`), a small library that marks text as "already safe HTML".

## Why this repository uses it

Cross-site scripting (**XSS**) happens when a page prints text that someone else controls and the browser mistakes it for code. The fix is **output encoding**: before printing, turn `<` into `&lt;`, `>` into `&gt;`, `&` into `&amp;`, `"` into `&#34;` and `'` into `&#39;`, so the browser shows the characters instead of treating them as markup. Jinja2 does this automatically for Flask's `.html` templates. This repository's pages print only a few values that come from the identity provider (the user name, the granted scopes) and from the code itself, but those are exactly the values that must never be trusted: a user name chosen at the provider is still input.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/oidc_login/interfaces/http/templates/base.html` | The page frame: head, header link, content block (13 lines). |
| `templates/home.html` | Signed-out: sign-in link(s). Signed-in: identity, granted scopes, sign-out form with the CSRF token. |
| `templates/error.html` | The generic failure page used by the callback. |
| `src/oidc_login/interfaces/http/static/style.css` | The one stylesheet; the Content-Security-Policy allows only this. |
| `tests/unit/test_http_app.py` | Renders the pages through the real Flask app. |

## How it works underneath

1. Flask calls `render_template("home.html", extra_scope=REPORTS_SCOPE, reports_allowed=...)`.
2. Jinja2 finds the file (cached after the first load), compiles it into a Python function, and calls it with the variables you gave plus the **context processor** values.
3. `{{ expression }}` prints a value. With autoescaping on, `&`, `<`, `>`, `'` and `"` in the printed text become `&amp;`, `&lt;`, `&gt;`, `&#39;`, `&#34;`.
4. `{% statement %}` is logic: `if`, `for`, `block`, `extends`.
5. The result is a plain string of HTML sent as the response body.

Autoescape is on by default for templates whose names end in `.html`, `.htm`, `.xml` or `.xhtml` when you use Flask's `render_template`.

### Ideas you need first

- **HTML.** The markup language of web pages: text with tags such as `<h1>Title</h1>` (a heading) and `<form>`. The browser draws the page from it.
- **A template.** An HTML file with holes that the server fills in for each request.
- **Escaping.** Replacing characters that have a special meaning in HTML (`<`, `>`, `&`, quotes) with harmless codes (`&lt;`, `&gt;`, `&amp;`) so user text cannot become markup.
- **A block and inheritance.** A base template defines named blocks (`{% block content %}`); child templates `extend` it and fill the blocks.

## Walkthrough of this repository's use

### `base.html`

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Notes sign-in{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header><a class="brand" href="/">Notes</a></header>
  <main>{% block content %}{% endblock %}</main>
</body>
</html>
```
`<!doctype html>` selects standards mode. `lang="en"` helps screen readers. `charset="utf-8"` is how the browser decodes bytes. `viewport` fits a phone screen. `{% block title %}Notes sign-in{% endblock %}` is a hole with a default; child pages override it. The stylesheet is the app's own `/static/style.css`, which the CSP (`style-src 'self'`) allows. There is no `<script>` and no inline style anywhere: the CSP forbids them.

### `error.html`

```html
{% extends "base.html" %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
<h1>{{ title }}</h1>
<p>{{ message }}</p>
<p><a href="/">Back to the start</a></p>
{% endblock %}
```
`{% extends "base.html" %}` means "use that page as the frame and fill its blocks". `title` and `message` are fixed strings chosen in `app.py` (`_failed(400, "This sign-in attempt is not valid. Start again.", ...)`); they never contain the provider's error text or any request value. That is deliberate: the page tells the user *that* the sign-in failed, never *why*.

### `home.html`

```html
{% if session %}
<h1>Signed in</h1>
<p>You are signed in as <strong>{{ session.identity.username }}</strong>.</p>
<p>Granted scopes: <code>{{ session.scopes | sort | join(" ") }}</code></p>
<p>The browser holds one opaque cookie. The tokens stay on the server.</p>
<form method="post" action="/logout">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <button type="submit">Sign out</button>
</form>
{% else %}
```
`session` and `csrf_token` come from the context processor in `app.py` (`template_context`), so every template can use them. `{{ session.identity.username }}` is **autoescaped**: a name like `<b>x</b>` prints as text. `session.scopes | sort | join(" ")` is a **filter chain**: take the set of scopes, sort it, join with spaces. The sign-out form is a POST with the CSRF token as a hidden field, so another site cannot sign you out by showing you a link or an image. Note that the template can read `session.scopes` and the identity but there is no way to print a token: the tokens are `repr=False` fields and no template mentions them.

```html
<h1>Sign in</h1>
<p>Sign-in is handled by the identity provider; this app never sees your password.</p>
<p><a class="button" href="/login">Sign in</a></p>
{% if reports_allowed %}
<p><a href="/login?scope={{ extra_scope | urlencode }}">Sign in and ask for reports access</a></p>
{% endif %}
```
Signed-out visitors get a plain link to `/login`, which starts the redirect to the provider. The second link is shown only when `reports:read` is on the allow-list; `| urlencode` percent-encodes the value for use inside a URL (`reports:read` becomes `reports%3Aread`), a different escaping from HTML escaping because the context (a URL) is different.

## Try it yourself

1. See escaping directly:
   ```bash
   .venv/bin/python - <<'EOF'
   from jinja2 import Environment
   print(Environment(autoescape=True).from_string("{{ x }}").render(x="<script>alert(1)</script>"))
   print(Environment(autoescape=False).from_string("{{ x }}").render(x="<b>"))
   EOF
   ```
   Expect `&lt;script&gt;alert(1)&lt;/script&gt;` and then `<b>`.
2. See the URL filter:
   ```bash
   .venv/bin/python -c "
   from jinja2 import Environment
   print(Environment().from_string('{{ s | urlencode }}').render(s='reports:read'))"
   ```
   Expect `reports%3Aread`.
3. Render the real pages through the app's unit tests:
   ```bash
   .venv/bin/pytest tests/unit/test_http_app.py -q
   ```
   Expect `27 passed`.
4. With the app running (`make run`), look at the signed-out page:
   ```bash
   curl -s http://localhost:3000/ | head -20
   ```
   Expect the `<h1>Sign in</h1>` page with the links above and no `<script>` tag.

## Mistakes people make

- `{{ value|safe }}` or `Markup(user_text)` on user text. The repository never uses either.
- Putting user input inside a `<script>` block or an `on...=` attribute, where HTML escaping is not enough. The templates contain no script and no inline handlers.
- Building HTML with string concatenation in Python. All HTML is in templates.
- Putting a provider error message or a request value into the failure page. It shows fixed strings only.
- Turning autoescape off globally "to fix a display problem".

## Check yourself

1. What does autoescaping do to `<` in a printed value?
   *It prints `&lt;`, so the browser shows the character and does not start a tag.*
2. Why does `error.html` show only fixed messages?
   *The page must tell the user that sign-in failed, never why; the reason is only in the log.*
3. Where do `csrf_token` and `session` come from?
   *The `template_context` context processor in `app.py`.*
4. What is `{% block %}` for?
   *A named hole in a base template that child templates fill.*
5. Why does the sign-out button live in a POST form with a hidden token?
   *A GET link could be triggered by another site; the token proves the request came from a page this app served.*

## Further reading

- Jinja 3.1 template designer: https://jinja.palletsprojects.com/en/3.1.x/templates/
- Autoescaping in Flask: https://flask.palletsprojects.com/en/stable/templating/#controlling-autoescaping
- HTML reference (MDN): https://developer.mozilla.org/en-US/docs/Web/HTML
- OWASP XSS prevention cheat sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
