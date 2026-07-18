"""Page shells — server renders the chrome (nav, session), static JS renders the data."""

LAYOUT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — WonderTask</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body data-page="{page}">
<header class="topbar">
  <div class="brand"><span class="logo">W</span> WonderTask</div>
  <nav>
    <a href="/" class="{nav_dashboard}">Dashboard</a>
    <a href="/board" class="{nav_board}">My Board</a>
    {admin_link}
  </nav>
  <div class="userbox">
    <span class="uname">{user_name}</span>
    <span class="urole">{user_role}</span>
    <a class="btn ghost sm" href="/account">Account</a>
    <a class="btn ghost sm" href="/logout">Log out</a>
  </div>
</header>
<main id="app">{body}</main>
<div id="modal-root"></div>
{scripts}
</body>
</html>"""

LOGIN = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in — WonderTask</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body class="login-body">
<form class="login-card" method="post" action="/login">
  <div class="brand big"><span class="logo">W</span> WonderTask</div>
  <p class="muted">WonderDoc marketing team — task management</p>
  {error}
  <label>Email <input name="email" type="email" required autofocus autocomplete="username"></label>
  <label>Password <input name="password" type="password" required autocomplete="current-password"></label>
  <button class="btn primary" type="submit">Sign in</button>
</form>
</body>
</html>"""

ACCOUNT = """
<div class="panel narrow">
  <h2>My account</h2>
  {notice}
  <form method="post" action="/account" class="stack">
    <label>Current password <input name="current" type="password" required></label>
    <label>New password (min 8 chars) <input name="new" type="password" minlength="8" required></label>
    <label>Repeat new password <input name="new2" type="password" minlength="8" required></label>
    <button class="btn primary" type="submit">Change password</button>
  </form>
</div>"""


def page(title, page_key, body, scripts, user, is_admin=False, notice=""):
    admin_link = f'<a href="/admin" class="{"active" if page_key == "admin" else ""}">Admin</a>' if is_admin else ""
    return LAYOUT.format(
        title=title, page=page_key, body=body, scripts=scripts,
        admin_link=admin_link,
        nav_dashboard="active" if page_key == "dashboard" else "",
        nav_board="active" if page_key == "board" else "",
        user_name=user.get("name") or user.get("email", ""),
        user_role=user.get("role_label", ""),
    )
