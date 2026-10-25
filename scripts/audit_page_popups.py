"""Read-only HTML audit of sidebar pages and their modal targets (manage.py shell)."""
import json
from collections import Counter
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve

client = Client(HTTP_HOST="localhost")
client.force_login(get_user_model().objects.filter(is_superuser=True).first())
session = client.session
session["selected_company"] = "all"
session.save()
initial = client.get("/petty-cash/")
root = BeautifulSoup(initial.content, "html.parser")
paths = {"/petty-cash/", "/documents/library/"}
for link in root.select('#sidebar [hx-get]'):
    path = urlsplit(link.get("hx-get", "")).path
    if path.startswith("/"):
        paths.add(path)
results = []
popup_urls = set()
lazy_urls = set()
for path in sorted(paths):
    try:
        response = client.get(path)
        soup = BeautifulSoup(response.content, "html.parser")
        counts = Counter(tag.get("id") for tag in soup.select('[id]'))
        for loader in soup.select('[hx-get][hx-trigger]'):
            if 'load' in loader.get('hx-trigger', '') and loader['hx-get'].startswith('/'):
                lazy_urls.add(loader['hx-get'])
        duplicates = {key: value for key, value in counts.items()
                      if value > 1 and ("modal" in key.lower() or "confirmation" in key.lower())}
        missing = []
        routes = []
        for button in soup.select('[data-toggle="oh-modal-toggle"]'):
            target = button.get('data-target', '')
            if target.startswith('#') and not soup.select(target):
                missing.append(target)
            url = button.get('hx-get')
            if url and url.startswith('/'):
                try:
                    match = resolve(urlsplit(url).path)
                    name = match.url_name or ''
                    if name.endswith(('-create', '-creation', '-update', '-form')) and not any(
                        part in name for part in ('delete', 'remove', 'approve', 'generate', 'send-mail')
                    ):
                        popup_urls.add(url)
                except Exception:
                    routes.append(url)
        result = {'page': path, 'status': response.status_code,
                          'modal_duplicates': duplicates,
                          'missing_targets': sorted(set(missing)),
                          'broken_routes': sorted(set(routes))}
        results.append(result)
        if duplicates or missing or routes or response.status_code != 200:
            print(json.dumps(result), flush=True)
    except Exception as exc:
        print(json.dumps({'page': path, 'error': type(exc).__name__, 'detail': str(exc)[:180]}), flush=True)
print('POPUP AUDIT COMPLETE: ' + str(len(results)) + ' pages checked', flush=True)
seen_lazy = set()
for depth in range(3):
    batch = lazy_urls - seen_lazy
    for url in sorted(batch):
        seen_lazy.add(url)
        try:
            response = client.get(url, HTTP_HX_REQUEST='true')
            soup = BeautifulSoup(response.content, 'html.parser')
            if response.status_code >= 400:
                print(json.dumps({'fragment': url, 'status': response.status_code}), flush=True)
            for button in soup.select('[data-toggle="oh-modal-toggle"][hx-get]'):
                dest = button['hx-get']
                if not dest.startswith('/'):
                    continue
                name = resolve(urlsplit(dest).path).url_name or ''
                if name.endswith(('-create', '-creation', '-update', '-form')) and not any(
                    part in name for part in ('delete', 'remove', 'approve', 'generate', 'send-mail')
                ):
                    popup_urls.add(dest)
            for loader in soup.select('[hx-get][hx-trigger]'):
                if 'load' in loader.get('hx-trigger', '') and loader['hx-get'].startswith('/'):
                    lazy_urls.add(loader['hx-get'])
        except Exception as exc:
            print(json.dumps({'fragment': url, 'error': type(exc).__name__, 'detail': str(exc)[:160]}), flush=True)
print('LAZY FRAGMENTS CHECKED: ' + str(len(seen_lazy)), flush=True)
for url in sorted(popup_urls):
    try:
        response = client.get(url, HTTP_HX_REQUEST='true')
        soup = BeautifulSoup(response.content, 'html.parser')
        print(json.dumps({'popup': url, 'status': response.status_code,
                          'full_page': bool(soup.select('#ohMainContent')),
                          'forms': len(soup.select('form'))}), flush=True)
    except Exception as exc:
        print(json.dumps({'popup': url, 'error': type(exc).__name__, 'detail': str(exc)[:160]}), flush=True)
print('FORM AUDIT COMPLETE: ' + str(len(popup_urls)) + ' popup routes checked', flush=True)
