"""
File management views — superuser-only.

Provides a unified dashboard for browsing all uploaded examinations,
associated protocols, and study set files, with per-institution filtering
and direct download of study set archives.
"""

import os

from django.contrib.auth.models import User
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views import View

from .models import CTExamination, CTProtocol
from .user_management_views import SuperuserRequiredMixin


def _build_institution_map() -> tuple[dict[str, str], list[str]]:
    """Return (username→institution dict, sorted list of distinct institutions)."""
    profiles = User.objects.select_related('profile').filter(profile__isnull=False)
    inst_map: dict[str, str] = {}
    all_insts: set[str] = set()
    for u in profiles:
        inst = (u.profile.institution or '').strip()
        inst_map[u.username] = inst
        if inst:
            all_insts.add(inst)
    return inst_map, sorted(all_insts)


class FileManagerView(SuperuserRequiredMixin, View):
    template_name = 'uploads/file_manager.html'

    def get(self, request):
        institution_filter = request.GET.get('institution', '').strip()
        inst_map, all_institutions = _build_institution_map()

        # Resolve usernames that belong to the selected institution.
        filtered_usernames: list[str] | None = None
        if institution_filter:
            filtered_usernames = [u for u, inst in inst_map.items() if inst == institution_filter]

        # ── Examinations ───────────────────────────────────────────────────────
        exam_qs = (
            CTExamination.objects
            .select_related('protocol', 'scanner__manufacturer', 'scanner__scanner_model')
            .order_by('-created_at')
        )
        if filtered_usernames is not None:
            exam_qs = exam_qs.filter(created_by__in=filtered_usernames)

        examinations = [
            {
                'obj': e,
                'institution': inst_map.get(e.created_by, '') or '—',
            }
            for e in exam_qs
        ]

        # ── Protocols ──────────────────────────────────────────────────────────
        protocol_qs = (
            CTProtocol.objects
            .select_related('scanner__manufacturer', 'scanner__scanner_model')
            .order_by('-created_at')
        )
        if filtered_usernames is not None:
            protocol_qs = protocol_qs.filter(created_by__in=filtered_usernames)

        protocols = [
            {
                'obj': p,
                'institution': inst_map.get(p.created_by, '') or '—',
            }
            for p in protocol_qs
        ]

        with_study_set = sum(1 for e in examinations if e['obj'].study_set_file)

        return render(request, self.template_name, {
            'examinations': examinations,
            'protocols': protocols,
            'institutions': all_institutions,
            'selected_institution': institution_filter,
            'total_exams': len(examinations),
            'total_protocols': len(protocols),
            'with_study_set': with_study_set,
        })


class StudySetDownloadView(SuperuserRequiredMixin, View):
    def get(self, request, exam_id):
        try:
            exam = CTExamination.objects.get(pk=exam_id)
        except CTExamination.DoesNotExist:
            raise Http404

        if not exam.study_set_file:
            raise Http404('No study set file attached to this examination.')

        try:
            file_path = exam.study_set_file.path
        except ValueError:
            raise Http404('File path could not be resolved.')

        if not os.path.exists(file_path):
            raise Http404('File not found on disk.')

        filename = os.path.basename(file_path)
        return FileResponse(
            open(file_path, 'rb'),  # noqa: WPS515 — FileResponse owns the handle
            as_attachment=True,
            filename=filename,
        )
