"""
Tests for the public RHYTHM pages (/, /tasks/, /repository/) and for the
upload platform's move from / to /platform/.
"""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from uploads import site_views


class PublicPagesTests(TestCase):
    def test_public_pages_need_no_login(self):
        for name in ('index', 'project-tasks', 'repository-progress'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)

    def test_landing_is_served_at_root(self):
        self.assertEqual(reverse('index'), '/')
        response = self.client.get('/')
        self.assertTemplateUsed(response, 'site/landing.html')

    def test_landing_links_anonymous_visitors_to_login_and_signup(self):
        response = self.client.get('/')
        self.assertContains(response, '/login/?next=/platform/')
        self.assertContains(response, reverse('signup-page'))

    def test_landing_links_signed_in_users_to_the_platform(self):
        user = User.objects.create_user('partner', password='pw-12345678')
        self.client.force_login(user)
        response = self.client.get('/')
        self.assertContains(response, 'href="/platform/"')
        self.assertNotContains(response, '/login/?next=')

    def test_landing_shows_every_milestone(self):
        response = self.client.get('/')
        for milestone in site_views.REPOSITORY_MILESTONES:
            self.assertContains(response, milestone['title'])

    @override_settings(RHYTHM_REPOSITORY_URL='')
    def test_repo_link_points_at_progress_page_until_live(self):
        response = self.client.get('/')
        self.assertContains(response, 'href="/repository/"')
        self.assertContains(response, 'Soon')

    @override_settings(RHYTHM_REPOSITORY_URL='https://repo.example.org/')
    def test_repo_link_points_at_live_repository_when_configured(self):
        response = self.client.get('/')
        self.assertContains(response, 'href="https://repo.example.org/"')
        self.assertContains(response, 'Live')
        self.assertNotContains(response, 'href="/repository/"')


class MilestoneContextTests(TestCase):
    def test_every_milestone_has_a_known_status(self):
        for milestone in site_views.REPOSITORY_MILESTONES:
            self.assertIn(milestone['status'], site_views.STATUS_LABELS)

    def test_percent_counts_in_progress_as_half(self):
        milestones = [
            {'task': '1', 'title': 'a', 'detail': '', 'status': site_views.DONE},
            {'task': '1', 'title': 'b', 'detail': '', 'status': site_views.IN_PROGRESS},
            {'task': '1', 'title': 'c', 'detail': '', 'status': site_views.PLANNED},
            {'task': '1', 'title': 'd', 'detail': '', 'status': site_views.PLANNED},
        ]
        original = site_views.REPOSITORY_MILESTONES
        site_views.REPOSITORY_MILESTONES = milestones
        try:
            context = site_views.milestone_context()
        finally:
            site_views.REPOSITORY_MILESTONES = original
        self.assertEqual(context['milestone_percent'], 38)  # (1 + 0.5) / 4
        self.assertEqual(context['milestones_done'], 1)
        self.assertEqual(context['milestones_in_progress'], 1)
        self.assertEqual(context['milestones_planned'], 2)


class PlatformHomeTests(TestCase):
    def test_platform_home_requires_login(self):
        response = self.client.get('/platform/')
        self.assertRedirects(response, '/login/?next=/platform/', fetch_redirect_response=False)

    def test_platform_home_renders_for_signed_in_user(self):
        user = User.objects.create_user('partner', password='pw-12345678')
        self.client.force_login(user)
        response = self.client.get('/platform/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'uploads/home.html')

    def test_login_page_sends_signed_in_users_to_platform(self):
        user = User.objects.create_user('partner', password='pw-12345678')
        self.client.force_login(user)
        response = self.client.get(reverse('login-page'))
        self.assertRedirects(response, '/platform/', fetch_redirect_response=False)

    def test_signup_page_sends_signed_in_users_to_platform(self):
        user = User.objects.create_user('partner', password='pw-12345678')
        self.client.force_login(user)
        response = self.client.get(reverse('signup-page'))
        self.assertRedirects(response, '/platform/', fetch_redirect_response=False)

    def test_non_superuser_is_sent_to_platform_from_admin_pages(self):
        user = User.objects.create_user('partner', password='pw-12345678')
        self.client.force_login(user)
        response = self.client.get(reverse('user-management'))
        self.assertRedirects(response, '/platform/', fetch_redirect_response=False)
