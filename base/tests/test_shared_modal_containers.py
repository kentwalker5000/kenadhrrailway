from django.conf import settings
from django.template import Context, Engine
from django.test import RequestFactory, SimpleTestCase


class SharedModalContainersTests(SimpleTestCase):
    def render_components(self, **headers):
        request = RequestFactory().get('/petty-cash/', **headers)
        engine = Engine(dirs=[str(settings.BASE_DIR / 'horilla_views' / 'templates')], libraries={
            'i18n': 'django.templatetags.i18n',
            'modal_components': 'horilla_theme.templatetags.modal_components',
        })
        return engine.from_string('{% include "generic/components.html" %}{% include "generic/components.html" %}').render(Context({'request': request}))

    def test_repeated_includes_render_only_one_container(self):
        html = self.render_components()
        for target in ('allocationModal', 'genericModal', 'deleteConfirmation', 'relatedObjectModal'):
            self.assertEqual(html.count(f'id="{target}"'), 1)

    def test_fragments_reuse_the_existing_shell(self):
        html = self.render_components(HTTP_HX_REQUEST='true')
        self.assertNotIn('id="genericModal"', html)

    def test_sidebar_full_responses_still_render_shared_containers(self):
        html = self.render_components(HTTP_HX_REQUEST='true', HTTP_HX_SIDEBAR_NAV='true')
        self.assertEqual(html.count('id="genericModal"'), 1)
