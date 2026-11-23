"""Reglas de cursos: publicación revisada, inscripción gratuita y progreso secuencial verificable."""
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.access import can_on, has_perm
from apps.audit.services import record
from apps.communications.services import notify, notify_many
from apps.core.errors import DomainError

from .models import Course, Enrollment, Lesson, LessonProgress


def visible_courses(user):
    return Course.objects.filter(status=Course.Status.PUBLISHED, campus_id=user.campus_id)


def can_edit(user, course):
    return course.author_id == user.pk and has_perm(user, "courses.author") and course.status in (Course.Status.DRAFT,)


def can_publish(user, course):
    return can_on(user, "courses.publish", area_id=course.area_id, campus_id=course.campus_id)


def submit_for_review(user, course_id):
    with transaction.atomic():
        course = Course.objects.select_for_update(of=("self",)).get(pk=course_id)
        if course.author_id != user.pk or course.status != Course.Status.DRAFT:
            raise DomainError("INVALID_TRANSITION")
        if not course.published_lessons().exists():
            raise DomainError("VALIDATION_FAILED", "Agrega al menos una lección publicada antes de enviar a revisión.")
        if not course.content_license_ok:
            raise DomainError("VALIDATION_FAILED", "Confirma que el contenido es original o cuenta con permiso.")
        course.status = Course.Status.REVIEW
        course.save(update_fields=["status", "updated_at"])
        record(user, "course.en_revision", course, before="borrador", after="en_revision")
        from apps.accounts.models import User

        reviewers = User.objects.filter(status="activo", user_roles__role__code="gestor", user_roles__area=course.area).distinct()
        notify_many(reviewers, "course", f"Curso por revisar: {course.title}", url=reverse("learning:manage_detail", args=[course.pk]),
                    dedupe_prefix=f"course:{course.pk}:review:{course.updated_at.timestamp()}")
    return course


def decide(user, course_id, approve: bool, note=""):
    with transaction.atomic():
        course = Course.objects.select_for_update(of=("self",)).get(pk=course_id)
        if not can_publish(user, course):
            raise DomainError("PERMISSION_DENIED")
        if course.author_id == user.pk:
            raise DomainError("PERMISSION_DENIED", "Quien crea el curso no puede aprobar su propia publicación.")
        if course.status != Course.Status.REVIEW:
            raise DomainError("INVALID_TRANSITION")
        before = course.status
        if approve:
            course.status = Course.Status.PUBLISHED
            course.published_at = timezone.now()
            course.approver = user
        else:
            if len((note or "").strip()) < 5:
                raise DomainError("VALIDATION_FAILED", fields={"note": "Indica qué debe corregirse."})
            course.status = Course.Status.DRAFT
        course.review_note = (note or "")[:300]
        course.save()
        record(user, f"course.{course.status}", course, before=before, after=course.status)
        notify(course.author, "course", f"Curso {'publicado' if approve else 'devuelto a borrador'}: {course.title}",
               body=note[:200] if note else "", url=reverse("learning:manage_detail", args=[course.pk]),
               dedupe_key=f"course:{course.pk}:decision:{course.updated_at.timestamp()}")
    return course


def archive(user, course_id):
    with transaction.atomic():
        course = Course.objects.select_for_update(of=("self",)).get(pk=course_id)
        if not can_publish(user, course):
            raise DomainError("PERMISSION_DENIED")
        if course.status != Course.Status.PUBLISHED:
            raise DomainError("INVALID_TRANSITION")
        course.status = Course.Status.ARCHIVED
        course.save(update_fields=["status", "updated_at"])
        record(user, "course.archivado", course, before="publicado", after="archivado")
    return course


def enroll(user, course_id):
    with transaction.atomic():
        course = visible_courses(user).select_for_update(of=("self",)).filter(pk=course_id).first()
        if course is None:
            raise DomainError("PERMISSION_DENIED")
        existing = Enrollment.objects.filter(course=course, student=user).first()
        if existing:
            if existing.status == Enrollment.Status.CANCELLED:
                existing.status = Enrollment.Status.ACTIVE
                existing.save(update_fields=["status"])
            return existing, False
        if course.capacity is not None and course.enrollments.exclude(status="cancelada").count() >= course.capacity:
            raise DomainError("RESOURCE_UNAVAILABLE", "El curso alcanzó su cupo.")
        try:
            with transaction.atomic():
                enrollment = Enrollment.objects.create(course=course, student=user)
        except IntegrityError:
            return Enrollment.objects.get(course=course, student=user), False
        record(user, "course.inscripcion", course, after="activa")
    return enrollment, True


def complete_lesson(user, lesson_id):
    """Solo el propio estudiante, inscrito, en lecciones publicadas y en orden."""
    with transaction.atomic():
        lesson = Lesson.objects.select_related("module__course").filter(pk=lesson_id, published=True).first()
        if lesson is None or lesson.module.course.status != Course.Status.PUBLISHED or lesson.module.course.campus_id != user.campus_id:
            raise DomainError("PERMISSION_DENIED")
        course = lesson.module.course
        enrollment = Enrollment.objects.select_for_update(of=("self",)).filter(course=course, student=user, status__in=["activa", "completada"]).first()
        if enrollment is None:
            raise DomainError("PERMISSION_DENIED", "Inscríbete al curso para registrar tu avance.")
        ordered = list(course.published_lessons().values_list("id", flat=True))
        done = set(enrollment.progress_entries.values_list("lesson_id", flat=True))
        previous = ordered[: ordered.index(lesson.pk)]
        if any(pid not in done for pid in previous):
            raise DomainError("INVALID_TRANSITION", "Completa primero las lecciones anteriores.")
        LessonProgress.objects.get_or_create(enrollment=enrollment, lesson=lesson)
        pct = enrollment.progress()
        if pct >= 100 and enrollment.status != Enrollment.Status.COMPLETED:
            enrollment.status = Enrollment.Status.COMPLETED
            enrollment.completed_at = timezone.now()
            enrollment.save(update_fields=["status", "completed_at"])
            notify(user, "course", f"Completaste «{course.title}»", body="Progreso: 100 %. Curso de ejemplo del prototipo (sin valor oficial).",
                   url=reverse("learning:detail", args=[course.pk]), dedupe_key=f"course:{course.pk}:done:{user.pk}")
    return enrollment, pct
