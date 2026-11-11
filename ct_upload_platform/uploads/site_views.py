"""
Public RHYTHM project pages (no login required).

These replace the WordPress pages at ctdose.med.uoc.gr/rhythm/, which are
being retired:

    /             LandingView      project info, upload platform, repository progress
    /tasks/       ProjectTasksView UoC work packages (WP1, WP5, Tasks 5.1-5.4)
    /repository/  RepositoryView   progress of the future RHYTHM repository

The upload platform itself (formerly at /) now lives at /platform/.

Repository progress is kept in REPOSITORY_MILESTONES below. Edit that list
as work lands. When the public repository is live, set
RHYTHM_REPOSITORY_URL in .env: every "RHYTHM repo" link then points there
instead of at /repository/.
"""

from typing import Any

from django.conf import settings
from django.urls import reverse
from django.views.generic import TemplateView

DONE = 'done'
IN_PROGRESS = 'in-progress'
PLANNED = 'planned'

STATUS_LABELS = {
    DONE: 'Done',
    IN_PROGRESS: 'In progress',
    PLANNED: 'Planned',
}

# One entry per milestone of the RHYTHM repository (WP5, Task 5.3/5.4).
# Keep it short and factual: this list is published as-is.
REPOSITORY_MILESTONES: list[dict[str, str]] = [
    {
        'task': '5.2',
        'title': 'Secure upload platform',
        'detail': 'Partner accounts with two-factor authentication, institution-scoped access '
                  'and an audit trail for every action.',
        'status': DONE,
    },
    {
        'task': '5.2',
        'title': 'Scanner, protocol and examination entry',
        'detail': 'Structured entry of CT scanner profiles, clinical-indication protocols and '
                  'per-examination dose data.',
        'status': DONE,
    },
    {
        'task': '5.2',
        'title': 'Anonymisation checks and image storage',
        'detail': 'Every DICOM file is checked against a GDPR-strict rule set before it reaches '
                  'the image archive. The server assigns the Repository Study ID.',
        'status': DONE,
    },
    {
        'task': '5.2',
        'title': 'Automated batch upload',
        'detail': 'A manifest tool (Python and Windows) and a manifest validator for submitting '
                  'many study sets in one batch.',
        'status': DONE,
    },
    {
        'task': '5.3',
        'title': 'Search and retrieval',
        'detail': 'Browse and filter repository data by age group, scanner model, examination '
                  'type, site and time period.',
        'status': IN_PROGRESS,
    },
    {
        'task': '5.3',
        'title': 'Interactive reporting and benchmarking',
        'detail': 'Compare local DRLs, protocol settings and image quality with institutions '
                  'that use the same scanner model.',
        'status': PLANNED,
    },
    {
        'task': '5.4',
        'title': 'Pilot validation and roll-out',
        'detail': 'Pilot testing with selected radiology departments, then a public release.',
        'status': PLANNED,
    },
]


def repository_link() -> dict[str, Any]:
    """Where "RHYTHM repo" links point: the live repository, or the progress page."""
    url = getattr(settings, 'RHYTHM_REPOSITORY_URL', '') or ''
    return {
        'repository_url': url or reverse('repository-progress'),
        'repository_is_live': bool(url),
    }


def milestone_context() -> dict[str, Any]:
    milestones = [
        {**m, 'status_label': STATUS_LABELS[m['status']]} for m in REPOSITORY_MILESTONES
    ]
    counts = {s: sum(1 for m in milestones if m['status'] == s) for s in STATUS_LABELS}
    total = len(milestones) or 1
    return {
        'milestones': milestones,
        'milestones_done': counts[DONE],
        'milestones_in_progress': counts[IN_PROGRESS],
        'milestones_planned': counts[PLANNED],
        'milestone_total': len(milestones),
        # Done counts fully, in-progress counts half: a rough but honest bar.
        'milestone_percent': round(100 * (counts[DONE] + 0.5 * counts[IN_PROGRESS]) / total),
    }


class PublicPageView(TemplateView):
    """Base for the public site pages: adds the repository link to every page."""

    nav_current = ''

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(repository_link())
        context['nav_current'] = self.nav_current
        return context


class LandingView(PublicPageView):
    template_name = 'site/landing.html'
    nav_current = 'home'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(milestone_context())
        return context


class ProjectTasksView(PublicPageView):
    template_name = 'site/tasks.html'
    nav_current = 'tasks'


class RepositoryView(PublicPageView):
    template_name = 'site/repository.html'
    nav_current = 'repository'

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context.update(milestone_context())
        return context
