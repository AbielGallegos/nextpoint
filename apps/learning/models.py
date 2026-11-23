"""Cursos y tutoriales: estructura, publicación revisada, inscripción y progreso por lección."""
from django.conf import settings
from django.db import models


class Course(models.Model):
    class Status(models.TextChoices):
        DRAFT = "borrador", "Borrador"
        REVIEW = "en_revision", "En revisión"
        PUBLISHED = "publicado", "Publicado"
        ARCHIVED = "archivado", "Archivado"

    class Level(models.TextChoices):
        INTRO = "introductorio", "Introductorio"
        INTERMEDIATE = "intermedio", "Intermedio"
        ADVANCED = "avanzado", "Avanzado"

    class Mode(models.TextChoices):
        ONLINE = "en_linea", "En línea (autoestudio)"
        ONSITE = "presencial", "Presencial"
        MIXED = "mixta", "Mixta"

    campus = models.ForeignKey("accounts.Campus", on_delete=models.PROTECT, related_name="courses")
    area = models.ForeignKey("accounts.Area", on_delete=models.PROTECT, related_name="courses")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_courses")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    title = models.CharField("título", max_length=140)
    summary = models.CharField("resumen", max_length=240)
    description = models.TextField("descripción", max_length=3000)
    level = models.CharField("nivel", max_length=20, choices=Level.choices, default=Level.INTRO)
    mode = models.CharField("modalidad", max_length=20, choices=Mode.choices, default=Mode.ONLINE)
    duration_minutes = models.PositiveIntegerField("duración estimada (min)", default=30)
    tags = models.JSONField(default=list, blank=True)
    fee_type = models.CharField(max_length=20, default="gratuito", editable=False)  # sin pagos en el prototipo
    capacity = models.PositiveIntegerField("cupo (opcional)", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    review_note = models.CharField(max_length=300, blank=True)
    content_license_ok = models.BooleanField("contenido original o con permiso", default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "curso"
        ordering = ["title"]
        indexes = [models.Index(fields=["campus", "status"])]

    def __str__(self):
        return self.title

    def published_lessons(self):
        return Lesson.objects.filter(module__course=self, published=True).order_by("module__position", "position")


class CourseModule(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    position = models.PositiveSmallIntegerField()
    title = models.CharField("título", max_length=140)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["course", "position"], name="uniq_module_position")]


class Lesson(models.Model):
    class Kind(models.TextChoices):
        TEXT = "texto", "Lectura"
        PRACTICE = "practica", "Práctica guiada"

    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name="lessons")
    position = models.PositiveSmallIntegerField()
    title = models.CharField("título", max_length=140)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.TEXT)
    content = models.TextField("contenido", max_length=12000, help_text="Texto plano. Línea en blanco = párrafo; '- ' = viñeta; '## ' = subtítulo.")
    duration_minutes = models.PositiveSmallIntegerField(default=10)
    published = models.BooleanField(default=True)

    class Meta:
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["module", "position"], name="uniq_lesson_position")]

    def __str__(self):
        return self.title


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "activa", "Activa"
        COMPLETED = "completada", "Completada"
        CANCELLED = "cancelada", "Cancelada"

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="enrollments")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="enrollments")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "student"], name="uniq_enrollment")]

    def progress(self):
        total = self.course.published_lessons().count()
        if not total:
            return 0
        done = self.progress_entries.filter(lesson__published=True).count()
        return round(done * 100 / total)


class LessonProgress(models.Model):
    enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name="progress_entries")
    lesson = models.ForeignKey(Lesson, on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["enrollment", "lesson"], name="uniq_lesson_progress")]
