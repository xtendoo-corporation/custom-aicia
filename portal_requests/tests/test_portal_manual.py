# -*- coding: utf-8 -*-
"""Manual de usuario por rol: artículos de Knowledge mostrados en el portal
(/my/manual), con sus imágenes y su PDF servidos solo al rol que corresponde."""
import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPortalManual(HttpCase):

    def setUp(self):
        super().setUp()
        self.password = 'portal_manual_test'
        portal = self.env.ref('base.group_portal')

        def user(login, groups):
            return self.env['res.users'].create({
                'name': login, 'login': login, 'password': self.password,
                'email': f'{login}@example.com',
                'group_ids': [(6, 0, [g.id for g in groups])],
            })

        self.requester = user('manual_requester_test', [portal])
        self.project_boss = user('manual_project_boss_test', [portal, self.env.ref('portal_requests.group_project_boss')])
        self.boss = user('manual_boss_test', [portal, self.env.ref('portal_requests.group_equip_boss')])
        self.administrative = user('manual_administrative_test', [self.env.ref('portal_requests.group_administrative')])
        self.internal = user('manual_internal_test', [self.env.ref('base.group_user')])

    def _get(self, user, url, **kw):
        self.authenticate(user.login, self.password)
        return self.url_open(url, **kw)

    def test_each_role_sees_its_manual(self):
        cases = [
            (self.requester, 'manual_article_solicitante'),
            (self.project_boss, 'manual_article_jefe_de_proyecto'),
            (self.boss, 'manual_article_jefe_de_equipo'),
            (self.administrative, 'manual_article_administrativo'),
        ]
        for user, xmlid in cases:
            article = self.env.ref(f'portal_requests.{xmlid}')
            response = self._get(user, '/my/manual')
            self.assertEqual(response.status_code, 200)
            self.assertIn(article.name, response.text, f'{user.login} debe ver {article.name}')
            others = [x for _u, x in cases if x != xmlid]
            for other in others:
                self.assertNotIn(self.env.ref(f'portal_requests.{other}').name, response.text)

    def test_manual_body_points_to_protected_routes(self):
        response = self._get(self.boss, '/my/manual')
        self.assertIn('/my/manual/image/manual_img_jefe_de_equipo_', response.text)
        self.assertIn('/my/manual/pdf', response.text)
        self.assertNotIn('/web/image/portal_requests.', response.text)
        # El enlace al PDF del artículo no se duplica con el botón del portal
        self.assertNotIn('Descargar este manual en PDF', response.text)

    def test_card_only_for_portal_users(self):
        self.assertIn('href="/my/manual"', self._get(self.requester, '/my').text.replace("'", '"'))
        home_internal = self._get(self.internal, '/my')
        self.assertNotIn('/my/manual', home_internal.text)

    def test_image_of_own_manual_is_served(self):
        body = self._get(self.boss, '/my/manual').text
        ref = re.search(r'/my/manual/image/(manual_img_[a-z0-9_]+)', body).group(1)
        response = self.url_open(f'/my/manual/image/{ref}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get('Content-Type', '').startswith('image/'))

    def test_image_of_other_role_is_not_served(self):
        # Imagen exclusiva del manual del Jefe de Equipo pedida por un solicitante
        self.assertTrue(self.env.ref('portal_requests.manual_img_jefe_de_equipo_04_documento_rechazar_motivo',
                                     raise_if_not_found=False))
        response = self._get(self.requester, '/my/manual/image/manual_img_jefe_de_equipo_04_documento_rechazar_motivo')
        self.assertEqual(response.status_code, 404)

    def test_numeric_attachment_of_other_article_is_not_served(self):
        other = self.env.ref('portal_requests.manual_pdf_director_gerente')
        response = self._get(self.requester, f'/my/manual/image/{other.id}')
        self.assertEqual(response.status_code, 404)

    def test_pdf_download_of_own_role(self):
        response = self._get(self.administrative, '/my/manual/pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Content-Type'), 'application/pdf')
        self.assertIn('Administrativo', response.headers.get('Content-Disposition', ''))
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_internal_users_can_read_articles_in_knowledge(self):
        root = self.env.ref('portal_requests.manual_article_root')
        article = self.env.ref('portal_requests.manual_article_director_gerente')
        self.assertTrue(article.with_user(self.internal).user_has_access)
        # Visible en el Espacio de trabajo de Knowledge para cualquier interno
        self.assertTrue(root.with_user(self.internal).is_article_visible)
        self.assertTrue(article.with_user(self.internal).is_article_visible)
        self.assertFalse(article.with_user(self.internal).user_has_write_access)
        self.assertEqual(root.internal_permission, 'read')
        self.assertEqual(article.parent_id, root)
