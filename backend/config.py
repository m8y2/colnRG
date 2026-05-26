import os

PROJECT_SLUG = "coln-river-guardians"
EPICOLLECT_API = "https://five.epicollect.net/api"
EPICOLLECT_EXPORT = f"{EPICOLLECT_API}/export/entries/{PROJECT_SLUG}"
EPICOLLECT_PROJECT = f"{EPICOLLECT_API}/export/project/{PROJECT_SLUG}"
FORM_REF = "10e9925df5cc4aa286de880dd770c4b4_6827803722b7f"
BRANCH_REFS = {}
PER_PAGE = 500
RATE_LIMIT_DELAY = 12
DB_PATH = os.path.join(os.path.dirname(__file__), "dashboard.db")
