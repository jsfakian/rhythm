"""
User management views — superuser-only.
"""

import json

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from .models import UserProfile


class SuperuserRequiredMixin(LoginRequiredMixin):
    """Redirect non-superusers to the index page."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_superuser:
            return redirect('/')
        return super().dispatch(request, *args, **kwargs)


class UserManagementView(SuperuserRequiredMixin, TemplateView):
    template_name = 'uploads/user_management.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        users = (
            User.objects
            .select_related('profile')
            .order_by('username')
        )
        user_list = []
        for u in users:
            profile = getattr(u, 'profile', None)
            user_list.append({
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'is_active': u.is_active,
                'is_staff': u.is_staff,
                'is_superuser': u.is_superuser,
                'date_joined': u.date_joined.strftime('%Y-%m-%d'),
                'institution': profile.institution if profile else '',
                'department': profile.department if profile else '',
                'professional_role': profile.get_professional_role_display() if profile and profile.professional_role else '',
            })
        ctx['users'] = user_list
        return ctx


class UserCreateAPIView(SuperuserRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        username = data.get('username', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '').strip()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        is_staff = bool(data.get('is_staff', False))

        if not username:
            return JsonResponse({'error': 'Username is required'}, status=400)
        if not password:
            return JsonResponse({'error': 'Password is required'}, status=400)
        if len(password) < 8:
            return JsonResponse({'error': 'Password must be at least 8 characters'}, status=400)
        if User.objects.filter(username=username).exists():
            return JsonResponse({'error': f'Username "{username}" already exists'}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_staff=is_staff,
        )
        return JsonResponse({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
            'date_joined': user.date_joined.strftime('%Y-%m-%d'),
            'institution': '',
            'department': '',
            'professional_role': '',
        }, status=201)


class UserUpdateAPIView(SuperuserRequiredMixin, View):
    def post(self, request, user_id, *args, **kwargs):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        action = data.get('action')

        if action == 'toggle_active':
            if user == request.user:
                return JsonResponse({'error': 'Cannot deactivate your own account'}, status=400)
            user.is_active = not user.is_active
            user.save()
            return JsonResponse({'is_active': user.is_active})

        if action == 'toggle_staff':
            if user == request.user:
                return JsonResponse({'error': 'Cannot modify your own staff status'}, status=400)
            if user.is_superuser:
                return JsonResponse({'error': 'Cannot modify staff status of another superuser'}, status=400)
            user.is_staff = not user.is_staff
            user.save()
            return JsonResponse({'is_staff': user.is_staff})

        if action == 'set_password':
            new_password = data.get('password', '').strip()
            if not new_password:
                return JsonResponse({'error': 'Password is required'}, status=400)
            if len(new_password) < 8:
                return JsonResponse({'error': 'Password must be at least 8 characters'}, status=400)
            user.set_password(new_password)
            user.save()
            return JsonResponse({'ok': True})

        return JsonResponse({'error': 'Unknown action'}, status=400)


class UserDeleteAPIView(SuperuserRequiredMixin, View):
    def post(self, request, user_id, *args, **kwargs):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found'}, status=404)

        if user == request.user:
            return JsonResponse({'error': 'Cannot delete your own account'}, status=400)
        if user.is_superuser:
            return JsonResponse({'error': 'Cannot delete another superuser account'}, status=400)

        username = user.username
        user.delete()
        return JsonResponse({'ok': True, 'deleted': username})
