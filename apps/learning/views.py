from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.access import has_perm, managed_area_ids, require_perm, scope_for, student_required
from apps.accounts.models import Area
from apps.audit.services import record
from apps.core.errors import DomainError
from apps.core.models import get_policy

from . import services
from .forms import CourseForm, LessonForm
from .models import Course, CourseModule, Enrollment, Lesson


def _guard_module(request):
    if not get_policy("module_courses_enabled", request.user.campus):
        return render(request, "errors/module_disabled.html", {"module": "Cursos"}, status=503)
    return None


# --------------------------------------------------------------------------- estudiante
@student_required
def catalog(request):
    if (resp := _guard_module(request)) is not None:
        return resp
    courses = services.visible_courses(request.user).annotate(nlessons=Count("modules__lessons", filter=Q(modules__lessons__published=True)))
    level = request.GET.get("nivel", "")
    if level:
        courses = courses.filter(level=level)
    mine = {e.course_id: e for e in Enrollment.objects.filter(student=request.user).exclude(status="cancelada")}
    items = []
    for c in courses:
        e = mine.get(c.pk)
        c.enrollment = e
        c.pct = e.progress() if e else None
        items.append(c)
    return render(request, "learning/catalog.html", {"courses": items, "level": level, "levels": Course.Level.choices})


@student_required
def detail(request, pk):
    if (resp := _guard_module(request)) is not None:
        return resp
    course = get_object_or_404(services.visible_courses(request.user).select_related("author", "area"), pk=pk)
    enrollment = Enrollment.objects.filter(course=course, student=request.user).exclude(status="cancelada").first()
    done = set(enrollment.progress_entries.values_list("lesson_id", flat=True)) if enrollment else set()
    lessons = list(course.published_lessons().select_related("module"))
    next_lesson = next((l for l in lessons if l.pk not in done), None)
    modules = []
    for m in course.modules.all():
        ls = [l for l in lessons if l.module_id == m.pk]
        if ls:
            modules.append({"m": m, "lessons": ls})
    return render(request, "learning/detail.html", {"c": course, "enrollment": enrollment, "done": done, "modules": modules,
                                                    "pct": enrollment.progress() if enrollment else 0, "next_lesson": next_lesson,
                                                    "total": len(lessons)})


@require_POST
@student_required
def enroll(request, pk):
    try:
        enrollment, created = services.enroll(request.user, pk)
        messages.success(request, "Inscripción registrada. ¡Comienza cuando quieras!" if created else "Ya estabas inscrita/o en este curso.")
    except DomainError as e:
        if e.code == "PERMISSION_DENIED":
            raise Http404
        messages.error(request, e.message)
    return redirect("learning:detail", pk=pk)


@student_required
def lesson(request, pk):
    lesson = get_object_or_404(Lesson.objects.select_related("module__course"), pk=pk, published=True)
    course = lesson.module.course
    if course.status != Course.Status.PUBLISHED or course.campus_id != request.user.campus_id:
        raise Http404
    enrollment = Enrollment.objects.filter(course=course, student=request.user).exclude(status="cancelada").first()
    if enrollment is None:
        messages.info(request, "Inscríbete gratis para abrir las lecciones.")
        return redirect("learning:detail", pk=course.pk)
    lessons = list(course.published_lessons().select_related("module"))
    done = set(enrollment.progress_entries.values_list("lesson_id", flat=True))
    idx = [l.pk for l in lessons].index(lesson.pk)
    locked = any(l.pk not in done for l in lessons[:idx])
    return render(request, "learning/lesson.html", {
        "lesson": lesson, "c": course, "lessons": lessons, "done": done, "idx": idx, "locked": locked,
        "prev": lessons[idx - 1] if idx > 0 else None, "next": lessons[idx + 1] if idx + 1 < len(lessons) else None,
        "pct": enrollment.progress(), "is_done": lesson.pk in done,
    })


@require_POST
@student_required
def complete(request, pk):
    try:
        enrollment, pct = services.complete_lesson(request.user, pk)
        messages.success(request, f"Lección completada. Tu avance: {pct} %.")
    except DomainError as e:
        if e.code == "PERMISSION_DENIED":
            raise Http404
        messages.error(request, e.message)
        return redirect("learning:lesson", pk=pk)
    lesson = Lesson.objects.select_related("module__course").get(pk=pk)
    lessons = list(lesson.module.course.published_lessons())
    ids = [l.pk for l in lessons]
    nxt = lessons[ids.index(pk) + 1] if ids.index(pk) + 1 < len(ids) else None
    return redirect("learning:lesson", pk=nxt.pk) if nxt else redirect("learning:detail", pk=lesson.module.course_id)


# --------------------------------------------------------------------------- panel
def _manageable_courses(user):
    cond = Q(pk__in=[])
    if has_perm(user, "courses.author"):
        cond |= Q(author=user)
    cond |= scope_for(user, "courses.publish").q()
    return Course.objects.filter(cond)


def _get_course(user, pk):
    course = get_object_or_404(_manageable_courses(user).select_related("author", "area", "approver"), pk=pk)
    return course


@require_perm("courses.author", "courses.publish", any_of=True)
def manage_list(request):
    qs = _manageable_courses(request.user).select_related("author", "area").annotate(
        nlessons=Count("modules__lessons", distinct=True), nenroll=Count("enrollments", distinct=True))
    status = request.GET.get("estado", "")
    if status:
        qs = qs.filter(status=status)
    review_count = _manageable_courses(request.user).filter(status=Course.Status.REVIEW).count() if has_perm(request.user, "courses.publish") else 0
    return render(request, "learning/manage_list.html", {"courses": qs.order_by("status", "title"), "status": status, "statuses": Course.Status.choices,
                                                         "review_count": review_count, "can_author": has_perm(request.user, "courses.author")})


@require_perm("courses.author")
def course_form(request, pk=None):
    course = _get_course(request.user, pk) if pk else None
    if course and not services.can_edit(request.user, course):
        messages.error(request, "Solo quien creó el curso puede editarlo y únicamente en borrador.")
        return redirect("learning:manage_detail", pk=course.pk)
    campus_areas = Area.objects.filter(campus_id=request.user.campus_id, active=True)
    form = CourseForm(request.POST or None, instance=course, areas=campus_areas)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.author = request.user
        obj.save()
        record(request.user, "course.updated" if course else "course.created", obj, after=obj.status)
        messages.success(request, "Curso guardado como borrador.")
        return redirect("learning:manage_detail", pk=obj.pk)
    return render(request, "learning/course_form.html", {"form": form, "course": course})


@require_perm("courses.author", "courses.publish", any_of=True)
def manage_detail(request, pk):
    course = _get_course(request.user, pk)
    modules = course.modules.prefetch_related("lessons")
    enrollments = course.enrollments.select_related("student").exclude(status="cancelada") if services.can_publish(request.user, course) or course.author_id == request.user.pk else []
    rows = [{"e": e, "pct": e.progress()} for e in enrollments]
    return render(request, "learning/manage_detail.html", {
        "c": course, "modules": modules, "can_edit": services.can_edit(request.user, course),
        "can_publish": services.can_publish(request.user, course) and course.author_id != request.user.pk, "rows": rows,
        "lesson_form": LessonForm(initial={"module_title": modules.first().title if modules.exists() else "Módulo 1", "published": True}),
    })


@require_POST
@require_perm("courses.author")
def add_lesson(request, pk):
    course = _get_course(request.user, pk)
    if not services.can_edit(request.user, course):
        raise PermissionDenied
    form = LessonForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            title = form.cleaned_data["module_title"].strip()
            module = course.modules.filter(title__iexact=title).first()
            if module is None:
                pos = (course.modules.aggregate(p=Max("position"))["p"] or 0) + 1
                module = CourseModule.objects.create(course=course, position=pos, title=title)
            lesson = form.save(commit=False)
            lesson.module = module
            lesson.position = (module.lessons.aggregate(p=Max("position"))["p"] or 0) + 1
            lesson.save()
            record(request.user, "lesson.created", course, after="borrador", detail={"lesson": lesson.title[:80]})
        messages.success(request, f"Lección «{lesson.title}» agregada.")
    else:
        messages.error(request, "Revisa la lección: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("learning:manage_detail", pk=pk)


@require_POST
@require_perm("courses.author", "courses.publish", any_of=True)
def course_action(request, pk, action):
    course = _get_course(request.user, pk)
    try:
        if action == "submit":
            services.submit_for_review(request.user, course.pk)
            messages.success(request, "Curso enviado a revisión. El gestor del área decidirá su publicación.")
        elif action == "approve":
            services.decide(request.user, course.pk, True, request.POST.get("note", ""))
            messages.success(request, "Curso publicado: ya aparece en el catálogo del campus.")
        elif action == "return":
            services.decide(request.user, course.pk, False, request.POST.get("note", ""))
            messages.success(request, "Curso devuelto a borrador con observaciones.")
        elif action == "archive":
            services.archive(request.user, course.pk)
            messages.success(request, "Curso archivado: ya no aparece en el catálogo; el progreso se conserva.")
        else:
            raise Http404
    except DomainError as e:
        if e.code == "PERMISSION_DENIED" and "propia" not in e.message:
            raise PermissionDenied
        messages.error(request, e.message + (" " + "; ".join(e.fields.values()) if e.fields else ""))
    return redirect("learning:manage_detail", pk=pk)
