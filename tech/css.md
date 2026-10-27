# CSS (the stylesheet)

## What it is

HTML says what is on a page (a heading, a form, a paragraph). **CSS** (Cascading Style Sheets) says how it looks: colors, spacing, fonts, layout. A CSS file is a list of **rules**. Each rule has a **selector** (which elements it applies to) and a **block** in curly braces of **declarations**, each `property: value;`. For example `button { padding: 0.4rem 0.9rem; }` means "every `<button>` gets this much space inside it". The browser downloads the file named in the page's `<link rel="stylesheet" href="/static/style.css">` and applies the rules.

## Why this repository uses it

The app has two small pages (a sign-in page and a signed-in page) and a generic failure page, and the lesson is about security, so the stylesheet is the *only* extra thing a page loads. That is deliberate: the Content-Security-Policy header (`default-src 'none'; style-src 'self'`, `tech/http-cookies-csrf-and-headers.md`) allows no script, no images and no inline style, and allows exactly one origin for styles: the app itself. A single small file from the same origin keeps that policy as strict as it can be.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/oidc_login/interfaces/http/static/style.css` | The one stylesheet, 6 rules. |
| `src/oidc_login/interfaces/http/templates/base.html` | Links to it: `<link rel="stylesheet" href="/static/style.css">`. |
| `pyproject.toml` | `[tool.setuptools.package-data]` lists `static/*.css` so the file is included when the package is built (`tech/pyproject-and-setuptools.md`). |

## How it works underneath

1. The browser loads the HTML, sees the `<link>`, and requests `/static/style.css` from the server. Flask serves anything in the app's `static/` folder under `/static/`. That response goes through the same security-header hook as every other, and `static` is one of the endpoints that skip session handling.
2. The browser parses the file into rules. For each element on the page it finds the rules whose selector matches, and combines their declarations. When two rules set the same property for the same element, the more **specific** selector wins (a class beats an element name; a longer selector beats a shorter one), and if they are equally specific, the later one wins. That is the "cascading".
3. Units: `rem` is a multiple of the page's base font size (`1rem` is about 16 pixels by default), so spacing scales with the user's font settings. `px` is a pixel. A bare number such as `1.5` for `line-height` is a multiple of the font size.
4. Colors: `#b00020` is red, green, blue in hexadecimal pairs (b0, 00, 20). An eight-digit code such as `#8884` is written with four digits: red 8, green 8, blue 8 and alpha 4 (opacity); each digit is doubled to make `#88888844`, a mid-gray at about 27% opacity, which works on both light and dark backgrounds.

## Walkthrough of this repository's use

The whole file is six rules.

```css
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
```
`:root` is the top element of the page (the `<html>` element). `color-scheme: light dark` tells the browser the page supports both a light and a dark theme, so it picks default colors (text, background, buttons) to match the user's system setting. `font-family: system-ui, sans-serif` asks for the operating system's own interface font and, if there is none, any sans-serif font. No font file is downloaded, which keeps the "load nothing else" policy intact.

```css
body { margin: 0; line-height: 1.5; }
```
Removes the browser's default space around the page and sets line spacing to 1.5 times the font size for easy reading.

```css
header { padding: 0.75rem 1.5rem; border-bottom: 1px solid #8884; }
```
The top bar (the `<header>` element holding the "Notes" link). `padding` is the space inside it: 0.75rem above and below, 1.5rem left and right. `border-bottom` draws a thin 1-pixel solid line in the translucent gray `#8884` (red 8, green 8, blue 8 and alpha 4, each digit doubled to `#88888844`: about 27% opaque, so it shows on both light and dark backgrounds).

```css
main { max-width: 40rem; margin: 0 auto; padding: 1.5rem; }
```
The content column: at most 40rem wide (about 640 pixels), centered (`margin: 0 auto` means no vertical margin and equal automatic margins on the left and right), with space inside.

```css
button, .button { padding: 0.4rem 0.9rem; font: inherit; }
```
A comma lists two selectors for one rule: every `<button>` and every element with the class `.button` (a leading dot means "has this class"). On the home page the "Sign in" control is an ordinary link styled with `class="button"`, and sign-out is a real button; both get the same padding. `font: inherit` uses the surrounding text's font instead of the browser's smaller control default.

```css
code { background: #8882; padding: 0.1rem 0.3rem; }
```
The `<code>` element (used on the home page for the list of granted scopes, `<code>openid profile email</code>`) gets a faint gray background (`#8882`: alpha 2, about 13% opaque) and a little padding, so scope names stand out from the text around them.

## Try it yourself

1. Read the file:
   ```bash
   cat src/oidc_login/interfaces/http/static/style.css
   ```
   Expect 6 lines, one rule each.
2. With the app running (`make up`, then `make run`), fetch it the way a browser does and look at the headers:
   ```bash
   curl -si http://localhost:3000/static/style.css | head -14
   ```
   Expect `200 OK`, `Content-Type: text/css`, the security headers, and the rules in the body.
3. See the stylesheet is the only thing a page loads:
   ```bash
   curl -s http://localhost:3000/ | grep -E "<link|<script|<img"
   ```
   Expect one `<link rel="stylesheet" href="/static/style.css">` line and no `<script>` or `<img>`.
4. Experiment: change `code { background: #8882; ... }` to `background: yellow;`, sign in, and see the list of granted scopes highlighted in yellow. Undo with `git checkout src/oidc_login/interfaces/http/static/style.css`. Or open the page in a browser and use the developer tools (right-click, Inspect) to edit rules live.

(Steps 2 to 4 need the running app, which needs Docker; they were not re-run when this note was written.)

## Mistakes people make

- Loading styles from a third-party address (a font or framework CDN) and then weakening the CSP to allow it. This app loads nothing from outside.
- Using inline `style="..."` attributes or a `<style>` block: the CSP forbids them (`style-src 'self'` allows only files from the same origin).
- Setting `width: 100%` and padding without `box-sizing: border-box`, so the element overflows its box (not needed in this small stylesheet).
- Assuming a later rule always wins: a more specific selector wins first.
- Packaging: forgetting to list `static/*.css` in `package-data`, so the installed package has no stylesheet.

## Check yourself

1. What are the two parts of a CSS rule?
   *A selector and a block of `property: value;` declarations.*
2. What does `button, .button` match?
   *Every `<button>` element and every element with the class `button`.*
3. What does `#8884` mean?
   *A translucent mid-gray: red 8, green 8, blue 8, alpha 4, each digit doubled.*
4. Why is the stylesheet the only external file a page loads?
   *The Content-Security-Policy allows scripts and images from nowhere and styles only from the app itself.*
5. What does `margin: 0 auto` do on `main`?
   *No vertical margin, and equal automatic left and right margins, which centers the column.*

## Further reading

- MDN, CSS: https://developer.mozilla.org/en-US/docs/Web/CSS
- MDN, flexbox: https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_flexible_box_layout/Basic_concepts_of_flexbox
- MDN, specificity: https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_cascade/Specificity
- MDN, `color-scheme`: https://developer.mozilla.org/en-US/docs/Web/CSS/color-scheme
