from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.audit.services import log_security, record
from apps.communications.services import notify
from apps.core.views_utils import paginate

from .access import has_perm, require_perm, scope_for
from .forms import AcceptInvitationForm, InvitationForm, LoginForm, ProfileForm, RoleAssignForm
from .models import Area, Campus, Invitation, LoginAttempt, Role, StaffProfile, StudentProfile, User, UserRole

MAX_ATTEMPTS = 5
WINDOW = timedelta(minutes=15)
TECHNICAL_ROLES = {Role.SUPPORT, Role.ADMIN}


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:home_redirect")
    form = LoginForm(request.POST or None, initial={"next": request.GET.get("next", "")})
    error = None
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        key = LoginAttempt.key_for(email, _client_ip(request))
        recent = LoginAttempt.objects.filter(key_hash=key, created_at__gte=timezone.now() - WINDOW).count()
        if recent >= MAX_ATTEMPTS:
            error = "Demasiados intentos. Espera 15 minutos e intenta de nuevo."
            log_security(request, "auth.rate_limited", detail={"code": "RATE_LIMITED"})
        else:
            from django.contrib.auth import authenticate

            user = authenticate(request, email=email, password=form.cleaned_data["password"])
            if user is None:
                LoginAttempt.objects.create(key_hash=key)
                # Mensaje genérico: no revela si la cuenta existe o está suspendida.
                error = "Correo o contraseña incorrectos, o la cuenta no está habilitada. Si necesitas ayuda, usa «¿Olvidaste tu contraseña?»."
                log_security(request, "auth.login_failed", detail={"code": "AUTH_FAILED"})
            else:
                LoginAttempt.objects.filter(key_hash=key).delete()
                login(request, user)
                log_security(request, "auth.login", actor=user)
                nxt = form.cleaned_data.get("next") or ""
                if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(nxt)
                return redirect("core:home_redirect")
    demo_accounts = []
    from django.conf import settings

    if settings.NEXTPOINT_SHOW_DEMO_ACCOUNTS:
        demo_accounts = [
            ("alumno.demo1@nextpoint.test", "Estudiante"), ("alumna.demo2@nextpoint.test", "Estudiante"),
            ("gestor.laboratorio@nextpoint.test", "Gestor de materiales"), ("gestor.servicios@nextpoint.test", "Gestor de solicitudes"),
            ("docente.demo@nextpoint.test", "Instructor"), ("coord.demo@nextpoint.test", "Coordinación"),
            ("admin.demo@nextpoint.test", "Administración técnica"),
        ]
        existing = set(User.objects.filter(email__in=[a for a, _ in demo_accounts]).values_list("email", flat=True))
        demo_accounts = [a for a in demo_accounts if a[0] in existing]
    return render(request, "accounts/login.html", {"form": form, "error": error, "demo_accounts": demo_accounts}, status=429 if error and "Demasiados" in error else 200)


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        log_security(request, "auth.logout")
    logout(request)  # invalida la sesión en el servidor (flush)
    messages.success(request, "Cerraste sesión correctamente.")
    return redirect("core:landing")


def accept_invitation(request, token):
    inv = Invitation.find(token)
    if inv is None or not inv.usable:
        return render(request, "accounts/invitation_invalid.html", {"inv": inv}, status=410 if inv else 404)
    form = AcceptInvitationForm(request.POST or None, user=User(email=inv.email, display_name=inv.display_name))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            inv = Invitation.objects.select_for_update(of=("self",)).get(pk=inv.pk)
            if not inv.usable or User.objects.filter(email=inv.email).exists():
                return render(request, "accounts/invitation_invalid.html", {"inv": inv}, status=410)
            user = User.objects.create_user(inv.email, form.cleaned_data["password1"], display_name=inv.display_name,
                                            campus=inv.campus or (inv.area.campus if inv.area else None))
            UserRole.objects.create(user=user, role=inv.role, campus=inv.campus if not inv.area else None, area=inv.area, granted_by=inv.created_by)
            if inv.role.code == Role.STUDENT:
                StudentProfile.objects.create(user=user)
            else:
                StaffProfile.objects.create(user=user, area=inv.area)
            inv.accepted_at = timezone.now()
            inv.accepted_user = user
            inv.save(update_fields=["accepted_at", "accepted_user"])
            record(user, "account.invitation_accepted", user, after=inv.role.code, campus=user.campus, area=inv.area)
        login(request, user, backend="apps.accounts.backends.EmailBackend")
        messages.success(request, "Tu cuenta quedó activa. ¡Bienvenida/o a NextPoint!")
        return redirect("core:home_redirect")
    return render(request, "accounts/invitation_accept.html", {"form": form, "inv": inv})


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        before = {"display_name": User.objects.get(pk=request.user.pk).display_name}
        form.save()
        record(request.user, "account.profile_updated", request.user, detail={"changed": form.changed_data, "before_name": before["display_name"][:3] + "…"})
        messages.success(request, "Guardamos los cambios de tu perfil.")
        return redirect("accounts:profile")
    roles = UserRole.objects.filter(user=request.user).select_related("role", "area", "campus")
    template = "accounts/profile.html"
    return render(request, template, {"form": form, "roles": roles, "base": _base_for(request)})


def _base_for(request):
    return "layouts/portal.html" if has_perm(request.user, "portal.student") else "layouts/panel.html"


@login_required
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # conserva esta sesión; las demás quedan invalidadas
        record(user, "account.password_changed", user)
        notify(user, "account", "Tu contraseña cambió", body="Si no fuiste tú, contacta a soporte.", url=reverse("accounts:profile"),
               dedupe_key=f"account:{user.pk}:pw:{timezone.now().timestamp()}")
        messages.success(request, "Contraseña actualizada.")
        return redirect("accounts:profile")
    for f in form.fields.values():
        f.widget.attrs["class"] = "input"
    return render(request, "accounts/password_change.html", {"form": form, "base": _base_for(request)})


# --------------------------------------------------------------------------- administración de cuentas
def _user_scope_q(request_user, perm):
    scope = scope_for(request_user, perm)
    if not scope.allowed:
        return Q(pk__in=[])
    if scope.is_global:
        return Q()
    q = Q(pk__in=[])
    if scope.campus_ids:
        q |= Q(campus_id__in=scope.campus_ids)
    if scope.area_ids:
        q |= Q(user_roles__area_id__in=scope.area_ids)
    return q


def _can_manage_user(actor, target):
    if target.pk == actor.pk:
        return False
    target_roles = set(target.user_roles.values_list("role__code", flat=True))
    if target_roles & TECHNICAL_ROLES and not has_perm(actor, "users.manage_technical"):
        return False
    scope = scope_for(actor, "users.manage")
    return scope.covers(campus_id=target.campus_id) or (scope.is_global)


def _assignable_roles(actor):
    qs = Role.objects.all()
    if not has_perm(actor, "users.manage_technical"):
        qs = qs.exclude(code__in=TECHNICAL_ROLES).exclude(code=Role.COORDINATOR)
    return qs


def _manageable_areas(actor):
    scope = scope_for(actor, "users.manage")
    return Area.objects.filter(scope.q(area_field="id", campus_field="campus_id")).select_related("campus")


@require_perm("users.view")
def users_list(request):
    qs = User.objects.filter(_user_scope_q(request.user, "users.view")).distinct().select_related("campus").annotate(nroles=Count("user_roles"))
    role = request.GET.get("rol", "")
    status = request.GET.get("estado", "")
    q = request.GET.get("q", "").strip()
    if role:
        qs = qs.filter(user_roles__role__code=role)
    if status in User.Status.values:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(display_name__icontains=q) | Q(email__icontains=q))
    page = paginate(request, qs.order_by("display_name"))
    roles_by_user = {}
    for ur in UserRole.objects.filter(user__in=[u.pk for u in page]).select_related("role", "area", "campus"):
        roles_by_user.setdefault(ur.user_id, []).append(ur)
    invitations = Invitation.objects.none()
    if has_perm(request.user, "users.manage"):
        scope = scope_for(request.user, "users.manage")
        invitations = Invitation.objects.filter(Q() if scope.is_global else (Q(campus_id__in=scope.campus_ids) | Q(area__campus_id__in=scope.campus_ids))).select_related("role", "area", "created_by")[:20]
    return render(request, "accounts/users_list.html", {
        "page": page, "roles_by_user": roles_by_user, "roles": Role.objects.all(), "statuses": User.Status.choices,
        "filters": {"rol": role, "estado": status, "q": q}, "invitations": invitations,
        "can_manage": has_perm(request.user, "users.manage"),
    })


@require_perm("users.view")
def user_detail(request, pk):
    target = get_object_or_404(User.objects.filter(_user_scope_q(request.user, "users.view")).distinct(), pk=pk)
    can_manage = has_perm(request.user, "users.manage") and _can_manage_user(request.user, target)
    form = RoleAssignForm(roles=_assignable_roles(request.user), areas=_manageable_areas(request.user)) if can_manage else None
    from apps.audit.models import AuditLog

    history = AuditLog.objects.filter(target_type="user", target_id=str(target.pk))[:15] if has_perm(request.user, "audit.view") else []
    return render(request, "accounts/user_detail.html", {
        "target": target, "assignments": target.user_roles.select_related("role", "area", "campus"), "can_manage": can_manage,
        "form": form, "history": history,
    })


@require_perm("users.manage")
def invite(request):
    roles = _assignable_roles(request.user)
    scope = scope_for(request.user, "users.manage")
    campuses = Campus.objects.filter(Q() if scope.is_global else Q(pk__in=scope.campus_ids))
    form = InvitationForm(request.POST or None, roles=roles, campuses=campuses, areas=_manageable_areas(request.user))
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        inv, token = Invitation.issue(created_by=request.user, email=d["email"], display_name=d["display_name"], role=d["role"],
                                      campus=d.get("campus"), area=d.get("area"))
        record(request.user, "account.invitation_created", inv, after=d["role"].code, label=f"Invitación {d['role'].name}",
               campus=d.get("campus"), area=d.get("area"))
        link = request.build_absolute_uri(reverse("accounts:accept_invitation", args=[token]))
        # Prototipo sin SMTP: el enlace se muestra una sola vez a quien invita para entregarlo por un canal seguro.
        return render(request, "accounts/invitation_created.html", {"inv": inv, "link": link})
    return render(request, "accounts/invite.html", {"form": form})


@require_POST
@require_perm("users.manage")
def revoke_invitation(request, pk):
    inv = get_object_or_404(Invitation, pk=pk)
    scope = scope_for(request.user, "users.manage")
    campus_id = inv.campus_id or (inv.area.campus_id if inv.area_id else None)
    if not scope.covers(campus_id=campus_id) and not scope.is_global:
        raise PermissionDenied
    if inv.usable:
        inv.revoked = True
        inv.save(update_fields=["revoked"])
        record(request.user, "account.invitation_revoked", inv, before="pendiente", after="revocada", label="Invitación")
        messages.success(request, "Invitación revocada.")
    return redirect("accounts:users")


def _last_admin(target):
    if not target.user_roles.filter(role__code=Role.ADMIN).exists():
        return False
    return User.objects.filter(status=User.Status.ACTIVE, user_roles__role__code=Role.ADMIN).exclude(pk=target.pk).count() == 0


@require_POST
@require_perm("users.manage")
def set_status(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not _can_manage_user(request.user, target):
        raise PermissionDenied
    new = request.POST.get("status")
    reason = request.POST.get("reason", "").strip()
    if new not in (User.Status.ACTIVE, User.Status.SUSPENDED):
        messages.error(request, "Estado no válido.")
        return redirect("accounts:user_detail", pk=pk)
    if new == User.Status.SUSPENDED and len(reason) < 5:
        messages.error(request, "Indica el motivo de la suspensión.")
        return redirect("accounts:user_detail", pk=pk)
    if new == User.Status.SUSPENDED and _last_admin(target):
        messages.error(request, "No se puede suspender la última cuenta de administración de la plataforma.")
        return redirect("accounts:user_detail", pk=pk)
    before = target.status
    target.status = new
    target.save()
    if new == User.Status.SUSPENDED:
        _kill_sessions(target)
    record(request.user, "account.status_changed", target, before=before, after=new, detail={"reason": reason[:200]}, campus=target.campus)
    messages.success(request, f"Cuenta {'suspendida: sus sesiones se cerraron' if new == 'suspendido' else 'reactivada'}.")
    return redirect("accounts:user_detail", pk=pk)


def _kill_sessions(user):
    from django.contrib.sessions.models import Session

    for s in Session.objects.filter(expire_date__gte=timezone.now()):
        if str(s.get_decoded().get("_auth_user_id")) == str(user.pk):
            s.delete()


def _role_snapshot(user):
    return ", ".join(sorted(f"{ur.role.code}@{ur.area.code if ur.area else (ur.campus.code if ur.campus else 'global')}"
                            for ur in user.user_roles.select_related("role", "area", "campus"))) or "sin roles"


@require_POST
@require_perm("users.manage")
def assign_role(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not _can_manage_user(request.user, target):
        raise PermissionDenied
    form = RoleAssignForm(request.POST, roles=_assignable_roles(request.user), areas=_manageable_areas(request.user))
    if not form.is_valid():
        for errs in form.errors.values():
            messages.error(request, errs[0])
        return redirect("accounts:user_detail", pk=pk)
    role, area = form.cleaned_data["role"], form.cleaned_data.get("area")
    before = _role_snapshot(target)
    campus = None if area else target.campus
    if role.code == Role.ADMIN:
        campus = None
    _, created = UserRole.objects.get_or_create(user=target, role=role, area=area, campus=campus, defaults={"granted_by": request.user})
    if created:
        if role.code == Role.STUDENT:
            StudentProfile.objects.get_or_create(user=target)
        record(request.user, "account.role_assigned", target, before=before[:40], after=_role_snapshot(target)[:40],
               detail={"before": before, "after": _role_snapshot(target)}, campus=target.campus, area=area)
        notify(target, "account", "Cambiaron tus permisos", body=f"Nuevo rol: {role.name}.", url=reverse("accounts:profile"),
               dedupe_key=f"account:{target.pk}:role:{timezone.now().timestamp()}")
        messages.success(request, f"Rol «{role.name}» asignado.")
    else:
        messages.info(request, "La persona ya tenía ese rol con ese alcance.")
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@require_perm("users.manage")
def revoke_role(request, pk, assignment_id):
    target = get_object_or_404(User, pk=pk)
    assignment = get_object_or_404(UserRole, pk=assignment_id, user=target)
    if not _can_manage_user(request.user, target):
        raise PermissionDenied
    if assignment.role.code in TECHNICAL_ROLES and not has_perm(request.user, "users.manage_technical"):
        raise PermissionDenied
    if assignment.role.code == Role.ADMIN and _last_admin(target):
        messages.error(request, "No se puede retirar el rol a la última cuenta de administración.")
        return redirect("accounts:user_detail", pk=pk)
    before = _role_snapshot(target)
    assignment.delete()
    record(request.user, "account.role_revoked", target, before=before[:40], after=_role_snapshot(target)[:40],
           detail={"before": before, "after": _role_snapshot(target)}, campus=target.campus)
    messages.success(request, "Rol retirado. El cambio aplica desde la siguiente petición de esa cuenta.")
    return redirect("accounts:user_detail", pk=pk)
