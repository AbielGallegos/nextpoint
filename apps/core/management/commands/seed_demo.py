"""Carga el conjunto de datos SINTÉTICO de demostración. Idempotente: ejecutarlo dos veces no duplica nada.

Escenario propuesto (sin convenio): Instituto Tecnológico de Morelia, Campus 2. Ningún dato corresponde
a personas, inventarios o contenidos reales de la institución.
"""
import os
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Area, Campus, Institution, Role, StaffProfile, StudentProfile, User, UserRole
from apps.catalog.models import InventoryMovement, Location, Resource, ResourceCategory, ResourceUnit
from apps.cases.models import ServiceCategory, ServiceRequest
from apps.communications.models import Alert
from apps.learning.models import Course, CourseModule, Lesson
from apps.smartmatch.models import MatchRule, Need

LESSON_1 = """## ¿Qué es una red?
Una red de computadoras es un conjunto de dispositivos conectados que comparten información y recursos. En el laboratorio verás tres piezas básicas: equipos finales (computadoras), dispositivos de interconexión (switches y routers) y el medio que los une (cable o señal inalámbrica).

## Tipos de red según su alcance
- LAN: red local, por ejemplo la de un laboratorio o un edificio.
- WAN: red de área amplia que une sitios distantes, como varias sedes.
- WLAN: red local inalámbrica basada en Wi-Fi.

## Direcciones IP en una frase
Cada equipo necesita una dirección IP para que los demás sepan a quién enviar los datos. La máscara de subred indica qué parte de la dirección identifica a la red y qué parte al equipo.

## Para practicar
Anota la dirección IP y la máscara de tu equipo de práctica y responde: ¿qué otros equipos estarían en la misma red?"""

LESSON_2 = """## Del cable al switch
En una LAN cableada cada computadora se conecta a un puerto del switch con un cable de par trenzado. El switch aprende qué equipo está en cada puerto y envía las tramas solo a quien corresponde.

## Armado guiado con el kit de redes
- Revisa que el kit incluya switch, cables y probador de continuidad.
- Conecta dos equipos al switch y verifica los indicadores luminosos de cada puerto.
- Asigna direcciones IP de la misma red a ambos equipos.
- Usa el comando ping de un equipo hacia el otro para comprobar la conexión.

## Si algo falla
Primero revisa la capa física: cable bien insertado, luz del puerto encendida y continuidad del cable. Después confirma que ambas direcciones IP pertenezcan a la misma red.

## Cierre
Al terminar, desconecta el equipo, enrolla los cables sin doblarlos y reporta en NextPoint cualquier daño que encuentres antes de devolver el kit."""


class Command(BaseCommand):
    help = "Carga datos sintéticos de demostración (idempotente). Requiere NEXTPOINT_DEMO_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("--reset-passwords", action="store_true", help="Vuelve a fijar la contraseña demo en las cuentas existentes.")
        parser.add_argument("--without-history", action="store_true", help="No crea casos/préstamos históricos (escenario vacío).")

    def handle(self, *args, **opts):
        password = os.environ.get("NEXTPOINT_DEMO_PASSWORD", "")
        if len(password) < 10:
            raise CommandError("Define NEXTPOINT_DEMO_PASSWORD (≥ 10 caracteres) en .env. Usa `python manage.py init_env`.")
        sync_master_data()
        with transaction.atomic():
            self.base_structure()
            self.users(password, opts["reset_passwords"])
            self.catalog()
            self.services()
            self.smartmatch()
            self.courses()
            self.alerts()
        if not opts["without_history"]:
            self.history()
        if opts.get("verbosity", 1):
            self.stdout.write(self.style.SUCCESS("Datos de demostración listos (sintéticos). Cuentas: ver docs/DEMO.md."))

    # ------------------------------------------------------------------ estructura
    def base_structure(self):
        self.inst, _ = Institution.objects.update_or_create(code="ITM-DEMO", defaults={
            "name": "Instituto Tecnológico de Morelia (escenario propuesto)", "data_controller_contact": "Por definir mediante convenio"})
        self.c2, _ = Campus.objects.update_or_create(institution=self.inst, code="C2", defaults={"name": "Campus 2"})
        self.c1, _ = Campus.objects.update_or_create(institution=self.inst, code="C1", defaults={"name": "Campus 1 (demo)"})
        self.lab, _ = Area.objects.update_or_create(campus=self.c2, code="LAB", defaults={"name": "Laboratorios y materiales", "contact_email": "laboratorio@nextpoint.test"})
        self.serv, _ = Area.objects.update_or_create(campus=self.c2, code="SERV", defaults={"name": "Atención y servicios estudiantiles", "contact_email": "servicios@nextpoint.test"})
        self.lab_c1, _ = Area.objects.update_or_create(campus=self.c1, code="LAB", defaults={"name": "Laboratorio (Campus 1)"})

    def users(self, password, reset):
        spec = [
            ("alumno.demo1@nextpoint.test", "Alumno Demo Uno", Role.STUDENT, self.c2, None, {"program": "Ingeniería en Sistemas (ejemplo)", "semester": 5}),
            ("alumna.demo2@nextpoint.test", "Alumna Demo Dos", Role.STUDENT, self.c2, None, {"program": "Ingeniería Electrónica (ejemplo)", "semester": 3}),
            ("gestor.laboratorio@nextpoint.test", "Gestor de Laboratorio (demo)", Role.MANAGER, self.c2, self.lab, {"position": "Responsable de materiales"}),
            ("gestor.servicios@nextpoint.test", "Gestora de Servicios (demo)", Role.MANAGER, self.c2, self.serv, {"position": "Atención estudiantil"}),
            ("docente.demo@nextpoint.test", "Docente Demo", Role.INSTRUCTOR, self.c2, None, {"position": "Instructor de redes"}),
            ("coord.demo@nextpoint.test", "Coordinación Demo", Role.COORDINATOR, self.c2, None, {"position": "Coordinación académica"}),
            ("admin.demo@nextpoint.test", "Administración Técnica (demo)", Role.ADMIN, self.c2, None, {"position": "Plataforma"}),
        ]
        self.u = {}
        for email, name, role_code, campus, area, extra in spec:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(email, password, display_name=name, campus=campus)
            elif reset:
                user.set_password(password)
                user.status = User.Status.ACTIVE
                user.save()
            role = Role.objects.get(code=role_code)
            if role_code == Role.ADMIN:
                UserRole.objects.get_or_create(user=user, role=role, campus=None, area=None)
            elif area:
                UserRole.objects.get_or_create(user=user, role=role, campus=None, area=area)
            else:
                UserRole.objects.get_or_create(user=user, role=role, campus=campus, area=None)
            if role_code == Role.STUDENT:
                StudentProfile.objects.update_or_create(user=user, defaults=extra)
            else:
                StaffProfile.objects.update_or_create(user=user, defaults={"area": area, "position": extra.get("position", "")})
            self.u[email.split("@")[0]] = user

    # ------------------------------------------------------------------ catálogo
    def catalog(self):
        cats = {}
        for slug, name, icon in [("redes", "Redes", "server"), ("electronica", "Electrónica", "zap"), ("computo", "Cómputo", "layers"),
                                 ("audiovisual", "Audiovisual", "play-circle")]:
            cats[slug], _ = ResourceCategory.objects.update_or_create(campus=self.c2, slug=slug, defaults={"name": name, "icon": icon})
        cat_c1, _ = ResourceCategory.objects.update_or_create(campus=self.c1, slug="redes", defaults={"name": "Redes", "icon": "server"})
        loc_lab, _ = Location.objects.update_or_create(campus=self.c2, name="Sala de prácticas de redes (ficticia)", defaults={
            "public_hint": "Edificio de laboratorios, planta baja (ubicación de ejemplo)", "access_rules": "Entrega con identificación escolar"})
        loc_elec, _ = Location.objects.update_or_create(campus=self.c2, name="Almacén de electrónica (ficticio)", defaults={
            "public_hint": "Ventanilla del almacén, edificio de laboratorios (ejemplo)"})
        loc_c1, _ = Location.objects.update_or_create(campus=self.c1, name="Laboratorio Campus 1 (ficticio)")
        gl = self.u["gestor.laboratorio"]
        spec = [
            (self.c2, self.lab, cats["redes"], "KIT-RED-01", "Kit de redes de laboratorio",
             "Kit para prácticas de redes locales: switch de 8 puertos, cables de par trenzado, conectores y probador de continuidad.",
             "Haber cursado o estar cursando una materia de redes (ejemplo).", "Préstamo de hasta 3 días; devolver completo y probado.", 3,
             ["redes", "laboratorio", "cableado", "switch", "practicas"], loc_lab, ["KR-0001"]),
            (self.c2, self.lab, cats["electronica"], "MULT-01", "Multímetro de prácticas",
             "Multímetro digital para mediciones de voltaje, corriente y continuidad en prácticas de electrónica.",
             "", "Préstamo de hasta 5 días.", 5, ["electronica", "mediciones", "laboratorio", "practicas"], loc_elec, ["MT-0001", "MT-0002"]),
            (self.c2, self.lab, cats["electronica"], "ARD-01", "Kit de microcontrolador para prototipos",
             "Placa de desarrollo con sensores básicos, protoboard y cables para prototipos de electrónica y programación.",
             "", "Préstamo de hasta 7 días.", 7, ["electronica", "programacion", "iot", "prototipos"], loc_elec, ["AR-0001", "AR-0002"]),
            (self.c2, self.lab, cats["computo"], "LAP-01", "Laptop para préstamo",
             "Equipo portátil con herramientas de programación para trabajo en clase o proyectos.",
             "", "Préstamo de hasta 3 días; no salir del campus (política de ejemplo).", 3, ["computo", "programacion", "laptop"], loc_lab, ["LP-0001", "LP-0002", "LP-0003"]),
            (self.c2, self.lab, cats["audiovisual"], "PROY-01", "Proyector portátil",
             "Proyector para exposiciones de proyectos.", "", "Préstamo de 1 día.", 1, ["audiovisual", "exposicion"], loc_lab, ["PR-0001"]),
            (self.c1, self.lab_c1, cat_c1, "KIT-RED-C1", "Kit de redes (Campus 1)",
             "Kit de redes del Campus 1, usado para demostrar el aislamiento por campus.", "", "", 3, ["redes", "laboratorio"], loc_c1, ["KR-C1-0001"]),
        ]
        self.res = {}
        for campus, area, cat, code, name, desc, req, policy, days, tags, loc, serials in spec:
            r, created = Resource.objects.get_or_create(campus=campus, code=code, defaults={
                "area": area, "category": cat, "name": name, "description": desc, "requirements": req, "loan_policy": policy,
                "max_loan_days": days, "tags": tags, "location": loc, "status": Resource.Status.PUBLISHED, "created_by": gl})
            for s in serials:
                unit, ucreated = ResourceUnit.objects.get_or_create(serial=s, defaults={"resource": r, "location": loc})
                if ucreated:
                    InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.REGISTER, state_after=unit.state, actor=gl, note="Alta (datos demo)")
            self.res[code] = r
        # Borrador sin ejemplares: no visible para estudiantes
        Resource.objects.get_or_create(campus=self.c2, code="OSC-01", defaults={
            "area": self.lab, "category": cats["electronica"], "name": "Osciloscopio de dos canales", "description": "Pendiente de registrar ejemplares.",
            "tags": ["electronica", "mediciones"], "status": Resource.Status.DRAFT, "created_by": gl})

    def services(self):
        spec = [
            (self.serv, "Consulta de disponibilidad de laboratorio", "consulta", "Pregunta por horarios y disponibilidad de salas de práctica.", ["laboratorio", "disponibilidad", "redes", "horarios"], "presencial"),
            (self.serv, "Incidencia en instalaciones o equipo", "incidencia", "Reporta fallas en salones, laboratorios o equipo de uso común.", ["incidencia", "instalaciones", "equipo"], "presencial"),
            (self.serv, "Información de trámites escolares", "tramite", "Orientación informativa sobre trámites; no sustituye los sistemas oficiales.", ["tramites", "servicios escolares", "orientacion"], "mixta"),
            (self.serv, "Asesoría de programación", "asesoria", "Sesiones de orientación con personal docente para dudas de programación.", ["programacion", "asesoria", "proyectos"], "mixta"),
            (self.serv, "Asesoría de redes", "asesoria", "Orientación para prácticas de redes y configuración básica.", ["redes", "asesoria", "laboratorio"], "presencial"),
            (self.lab, "Reporte de material dañado o incompleto", "reporte_recurso", "Avisa si un material prestado presenta daño o le faltan piezas.", ["material", "dano", "laboratorio"], "presencial"),
        ]
        self.cat = {}
        for area, name, kind, desc, tags, modality in spec:
            sc, _ = ServiceCategory.objects.update_or_create(campus=area.campus, name=name, defaults={
                "area": area, "kind": kind, "description": desc, "tags": tags, "modality": modality, "active": True})
            self.cat[name] = sc

    def smartmatch(self):
        for campus in (self.c2, self.c1):
            if not MatchRule.objects.filter(campus=campus).exists():
                MatchRule.objects.create(campus=campus, version=1, status=MatchRule.Status.ACTIVE, activated_at=timezone.now(),
                                         note="Pesos de referencia del documento maestro", created_by=self.u["coord.demo"])
        needs = [
            ("material-de-redes", "Material de redes", "materiales", ["redes", "laboratorio", "cableado"], 1),
            ("equipo-de-electronica", "Equipo de electrónica", "materiales", ["electronica", "mediciones"], 2),
            ("equipo-de-computo", "Equipo de cómputo", "materiales", ["computo", "laptop", "programacion"], 3),
            ("asesoria-de-programacion", "Asesoría de programación", "asesorias", ["programacion", "asesoria"], 4),
            ("aprender-redes", "Aprender redes desde cero", "cursos", ["redes", "introductorio"], 5),
            ("tramites-escolares", "Orientación sobre trámites", "tramites", ["tramites", "orientacion"], 6),
            ("convocatorias", "Talleres y convocatorias", "oportunidades", ["convocatoria", "taller", "becas"], 7),
        ]
        for code, label, cat, tags, order in needs:
            Need.objects.update_or_create(campus=self.c2, code=code, defaults={"label": label, "category": cat, "tags": tags, "order": order})

    def courses(self):
        doc, gl = self.u["docente.demo"], self.u["gestor.laboratorio"]
        c, created = Course.objects.get_or_create(campus=self.c2, title="Introducción a redes: conceptos básicos y conexiones", defaults={
            "area": self.lab, "author": doc, "approver": gl, "summary": "Curso de ejemplo con dos lecciones: qué es una red y cómo armar una LAN con el kit del laboratorio.",
            "description": "Este es un curso de ejemplo del prototipo; no representa una capacitación institucional acreditada ni emite constancias oficiales.",
            "level": Course.Level.INTRO, "mode": Course.Mode.ONLINE, "duration_minutes": 40, "tags": ["redes", "introductorio", "laboratorio"],
            "status": Course.Status.PUBLISHED, "published_at": timezone.now(), "content_license_ok": True})
        if created:
            m = CourseModule.objects.create(course=c, position=1, title="Fundamentos")
            Lesson.objects.create(module=m, position=1, title="¿Qué es una red y cómo se identifica cada equipo?", content=LESSON_1, duration_minutes=15)
            Lesson.objects.create(module=m, position=2, title="Arma tu primera LAN con el kit de redes", kind=Lesson.Kind.PRACTICE, content=LESSON_2, duration_minutes=25)
        d, created = Course.objects.get_or_create(campus=self.c2, title="Buenas prácticas de documentación de proyectos", defaults={
            "area": self.lab, "author": doc, "summary": "Borrador: cómo documentar un proyecto escolar de software.",
            "description": "Curso en preparación (borrador). No visible para estudiantes.", "level": Course.Level.INTRO, "mode": Course.Mode.ONLINE,
            "duration_minutes": 30, "tags": ["documentacion", "proyectos"], "status": Course.Status.DRAFT, "content_license_ok": True})
        if created:
            m = CourseModule.objects.create(course=d, position=1, title="Primeros pasos")
            Lesson.objects.create(module=m, position=1, title="Un README que se entiende", content="## Propósito\nExplica qué hace tu proyecto, cómo instalarlo y cómo probarlo.\n\n- Qué problema resuelve\n- Cómo se ejecuta\n- Cómo se prueba", duration_minutes=10)

    def alerts(self):
        now = timezone.now()
        gl, coord = self.u["gestor.laboratorio"], self.u["coord.demo"]
        spec = [
            ("Entrega de materiales del laboratorio esta semana", "Horario especial de entrega y recepción de materiales de práctica.",
             "Durante esta semana la ventanilla de materiales atenderá en horario extendido (horario de ejemplo). Consulta disponibilidad en NextPoint antes de acudir.",
             "materiales", "normal", self.c2, self.lab, gl, "borrador", now, now + timedelta(days=7), ["materiales", "laboratorio"]),
            ("Convocatoria de taller introductorio (ejemplo)", "Taller gratuito de redes para estudiantes del campus. Cupo limitado (ejemplo).",
             "Convocatoria ficticia para la demostración. El registro de interés no implica cobro ni inscripción oficial.",
             "convocatorias", "alta", self.c2, None, coord, "publicado", now - timedelta(days=1), now + timedelta(days=30), ["convocatoria", "taller", "redes"]),
            ("Mantenimiento programado de equipo de cómputo", "Algunos equipos de préstamo estarán en revisión preventiva.",
             "Durante el mantenimiento algunas laptops no estarán disponibles; el catálogo muestra la disponibilidad real.",
             "mantenimiento", "normal", self.c2, self.lab, gl, "publicado", now - timedelta(days=2), now + timedelta(days=10), ["computo", "mantenimiento"]),
            ("Aviso vencido de semana anterior", "Este aviso ya expiró y no debe mostrarse a estudiantes.",
             "Contenido histórico de ejemplo.", "general", "normal", self.c2, self.lab, gl, "publicado", now - timedelta(days=15), now - timedelta(days=8), []),
            ("Aviso exclusivo del Campus 1", "Solo visible para cuentas del Campus 1.", "Demostración de segmentación por campus.",
             "general", "normal", self.c1, None, coord, "publicado", now - timedelta(days=1), now + timedelta(days=20), []),
        ]
        for title, summary, body, cat, prio, campus, area, author, status, pub, exp, tags in spec:
            Alert.objects.get_or_create(title=title, defaults={
                "summary": summary, "body": body, "category": cat, "priority": prio, "institution": self.inst, "campus": campus, "area": area,
                "author": author, "approver": author if status == "publicado" else None, "status": status, "publish_at": pub, "expires_at": exp,
                "published_at": pub if status == "publicado" else None, "tags": tags, "audience": "estudiantes"})

    # ------------------------------------------------------------------ historial
    def history(self):
        """Actividad previa creada a través de los servicios reales (mismas reglas, eventos y auditoría)."""
        from apps.cases import services as case_services
        from apps.loans import services as loan_services
        from apps.loans.models import LoanRequest

        a1, a2 = self.u["alumno.demo1"], self.u["alumna.demo2"]
        gl, gs = self.u["gestor.laboratorio"], self.u["gestor.servicios"]
        today = timezone.localdate()
        ns = uuid.UUID("6f1c2f1e-0000-4000-8000-000000000000")

        def key(name):
            return uuid.uuid5(ns, name)

        # Préstamo concluido de alumno 1 (multímetro): historial completo
        if not LoanRequest.objects.filter(applicant=a1, idempotency_key=key("a1-mult")).exists():
            req, _ = loan_services.create_request(a1, self.res["MULT-01"].pk, today, today + timedelta(days=2), "Práctica de mediciones (demo)", key("a1-mult"))
            loan_services.approve(gl, req.pk, "Recoger en ventanilla")
            loan_services.deliver(gl, req.pk, "bueno")
            loan_services.register_return(gl, req.pk, "bueno", "disponible", "Devuelto completo")
        # Préstamo activo y vencido de alumna 2 (laptop) — para el tablero de vencidos
        if not LoanRequest.objects.filter(applicant=a2, idempotency_key=key("a2-lap")).exists():
            req, _ = loan_services.create_request(a2, self.res["LAP-01"].pk, today, today + timedelta(days=1), "Proyecto de programación (demo)", key("a2-lap"))
            loan_services.approve(gl, req.pk, "")
            loan_services.deliver(gl, req.pk, "bueno")
            LoanRequest.objects.filter(pk=req.pk).update(start_date=today - timedelta(days=4), due_date=today - timedelta(days=1))
            req.loan.__class__.objects.filter(pk=req.loan.pk).update(due_date=today - timedelta(days=1))
        # Solicitud pendiente de alumna 2 (multímetro)
        if not LoanRequest.objects.filter(applicant=a2, idempotency_key=key("a2-mult")).exists():
            loan_services.create_request(a2, self.res["MULT-01"].pk, today + timedelta(days=1), today + timedelta(days=3), "Práctica de electrónica (demo)", key("a2-mult"))

        # Casos de alumna 2: uno en atención (con nota interna) y uno cerrado
        if not ServiceRequest.objects.filter(creator=a2, idempotency_key=key("a2-case1")).exists():
            req, _ = case_services.create_request(a2, self.cat["Consulta de disponibilidad de laboratorio"].pk, "Horario de la sala de prácticas",
                                                  "¿La sala de prácticas de redes está disponible el jueves por la tarde para trabajar en equipo? (caso demo)",
                                                  "normal", key("a2-case1"))
            case_services.staff_action(gs, req.pk, "acknowledge")
            case_services.staff_message(gs, req.pk, "Nota interna: confirmar con laboratorio la agenda del jueves.", internal=True)
            case_services.staff_action(gs, req.pk, "start", body="Estamos verificando la agenda de la sala.")
        if not ServiceRequest.objects.filter(creator=a2, idempotency_key=key("a2-case2")).exists():
            req, _ = case_services.create_request(a2, self.cat["Incidencia en instalaciones o equipo"].pk, "Contacto dañado en mesa 3",
                                                  "El contacto eléctrico de la mesa 3 de la sala de cómputo no funciona (caso demo).", "alta", key("a2-case2"))
            case_services.staff_action(gs, req.pk, "acknowledge")
            case_services.staff_action(gs, req.pk, "resolve", body="Se reportó a mantenimiento y se reparó el contacto (resolución demo).")
            case_services.student_action(a2, req.pk, "confirm")
        # Caso cerrado de alumno 1 (historial propio)
        if not ServiceRequest.objects.filter(creator=a1, idempotency_key=key("a1-case1")).exists():
            req, _ = case_services.create_request(a1, self.cat["Información de trámites escolares"].pk, "Dónde consultar el calendario de reinscripción",
                                                  "Quisiera saber dónde se publica el calendario de reinscripción (caso demo).", "baja", key("a1-case1"))
            case_services.staff_action(gs, req.pk, "acknowledge")
            case_services.staff_action(gs, req.pk, "resolve", body="El calendario se publica en los canales oficiales de la institución; NextPoint no lo sustituye.")
            case_services.staff_action(gs, req.pk, "close")
        # Un caso nuevo sin atender (para la cola del gestor)
        if not ServiceRequest.objects.filter(creator=a1, idempotency_key=key("a1-case2")).exists():
            case_services.create_request(a1, self.cat["Asesoría de programación"].pk, "Duda sobre estructuras de datos",
                                         "Busco orientación para implementar una lista enlazada en mi proyecto (caso demo).", "normal", key("a1-case2"))


def sync_master_data():
    """Re-sincroniza roles/permisos con el catálogo maestro (idempotente)."""
    from apps.accounts.access import PERMISSIONS, ROLE_PERMISSIONS, ROLES
    from apps.accounts.models import Permission, RolePermission

    for code, name, desc, privileged, order in ROLES:
        Role.objects.update_or_create(code=code, defaults={"name": name, "description": desc, "is_privileged": privileged, "order": order})
    for code, (module, desc) in PERMISSIONS.items():
        Permission.objects.update_or_create(code=code, defaults={"module": module, "description": desc})
    for role_code, perms in ROLE_PERMISSIONS.items():
        role = Role.objects.get(code=role_code)
        RolePermission.objects.filter(role=role).exclude(permission__code__in=perms).delete()
        for p in perms:
            RolePermission.objects.get_or_create(role=role, permission=Permission.objects.get(code=p))
