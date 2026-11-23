from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from apps.accounts.access import has_perm, require_perm, scope_for, student_required
from apps.accounts.models import Campus
from apps.audit.services import record
from apps.catalog.models import normalize_tags
from apps.core.models import get_policy
from apps.core.views_utils import int_or_none

from .engine import DEFAULT_WEIGHTS, recommend
from .models import CATEGORIES, CATEGORY_ICONS, CATEGORY_LABELS, MatchQuery, MatchRule, Need

WEIGHT_LABELS = [("category", "Categoría"), ("tags", "Etiquetas"), ("campus", "Campus"), ("availability", "Disponibilidad"), ("freshness", "Vigencia")]


def _module_enabled(user):
    return get_policy("module_smartmatch_enabled", user.campus)


@student_required
def home(request):
    user = request.user
    if not _module_enabled(user):
        return render(request, "errors/module_disabled.html", {"module": "SmartMatch"}, status=503)
    needs = Need.objects.filter(campus=user.campus, enabled=True)
    params = request.GET
    submitted = "category" in params or "need" in params
    need = needs.filter(code=params.get("need", "")).first()
    category = params.get("category", "") if params.get("category", "") in CATEGORY_LABELS else (need.category if need else "")
    tags_text = params.get("tags", ", ".join(need.tags) if need else "")
    tags = normalize_tags(tags_text)
    campus_only = params.get("todos_campus") != "1"
    only_available = params.get("disponibles") == "1"
    modality = params.get("modalidad", "")
    level = params.get("nivel", "")
    results, rule = [], None
    if submitted:
        if not category and not tags:
            messages.error(request, "Elige una necesidad o una categoría para buscar coincidencias.")
        else:
            limit = get_policy("smartmatch_max_results", user.campus)
            results, rule = recommend(user, category=category, tags=tags, campus_only=campus_only, only_available=only_available,
                                      modality=modality, level=level, limit=limit)
            MatchQuery.objects.create(user=user, campus=user.campus, need_code=need.code if need else "", category=category,
                                      results_count=len(results), rule_version=rule.version if rule else None)
    weights = rule.weights if rule else DEFAULT_WEIGHTS
    return render(request, "smartmatch/home.html", {
        "needs": needs, "categories": [(c, l, CATEGORY_ICONS[c]) for c, l in CATEGORIES], "submitted": submitted, "results": results,
        "rule": rule, "f": {"need": need.code if need else "", "category": category, "tags": tags_text, "todos_campus": not campus_only,
                            "disponibles": only_available, "modalidad": modality, "nivel": level},
        "weights": weights, "weight_labels": WEIGHT_LABELS, "need": need, "related": [c for c in CATEGORIES if c[0] != category][:3],
    })


@student_required
def compare(request):
    user = request.user
    keys = request.GET.getlist("item")[:3]
    category = request.GET.get("category", "")
    tags = normalize_tags(request.GET.get("tags", ""))
    results, rule = recommend(user, category=category, tags=tags, campus_only=request.GET.get("todos_campus") != "1", limit=50, min_score=0)
    chosen = [r for r in results if r.key in keys]
    weights = rule.weights if rule else DEFAULT_WEIGHTS
    return render(request, "smartmatch/compare.html", {"chosen": chosen, "weights": weights, "weight_labels": WEIGHT_LABELS,
                                                       "back": request.GET.get("back", "")})


# --------------------------------------------------------------------------- panel
def _campus_for(user):
    scope = scope_for(user, "smartmatch.test")
    if scope.is_global:
        return Campus.objects.filter(pk=user.campus_id).first() or Campus.objects.first()
    from apps.accounts.models import Area

    if scope.campus_ids:
        return Campus.objects.get(pk=sorted(scope.campus_ids)[0])
    area = Area.objects.filter(pk__in=scope.area_ids).select_related("campus").first()
    return area.campus if area else user.campus


@require_perm("smartmatch.test")
def rules(request):
    campus = _campus_for(request.user)
    versions = MatchRule.objects.filter(campus=campus).select_related("created_by")
    active = versions.filter(status=MatchRule.Status.ACTIVE).first()
    draft = versions.filter(status=MatchRule.Status.DRAFT).first()
    sim_results, sim_rule = None, None
    sim = {"category": request.GET.get("category", "materiales"), "tags": request.GET.get("tags", "redes, laboratorio"), "rule": request.GET.get("rule", "")}
    if "simular" in request.GET:
        rule_id = int_or_none(sim["rule"])
        sim_rule = (versions.filter(pk=rule_id).first() if rule_id else None) or draft or active
        errors = sim_rule.validation_errors() if sim_rule else []
        if errors:
            messages.error(request, "La versión simulada no es válida: " + " ".join(errors))
        else:
            # El simulador usa la versión elegida sin activarla: no altera la configuración vigente.
            sim_user = request.user
            if sim_user.campus_id != campus.pk:
                sim_user = type(request.user).objects.get(pk=request.user.pk)
                sim_user.campus = campus
            sim_results, _ = recommend(sim_user, category=sim["category"], tags=normalize_tags(sim["tags"]),
                                       weights=sim_rule.weights if sim_rule else DEFAULT_WEIGHTS, min_score=sim_rule.min_score if sim_rule else 40)
    usage = MatchQuery.objects.filter(campus=campus).values("category").annotate(n=Count("id")).order_by("-n")
    return render(request, "smartmatch/rules.html", {
        "campus": campus, "versions": versions[:10], "active": active, "draft": draft, "needs": Need.objects.filter(campus=campus),
        "can_publish": has_perm(request.user, "smartmatch.publish"), "sim": sim, "sim_results": sim_results, "sim_rule": sim_rule,
        "categories": CATEGORIES, "weight_labels": WEIGHT_LABELS, "usage": usage,
        "total_queries": MatchQuery.objects.filter(campus=campus).count(),
    })


def _int(v, default=0):
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return default


@require_POST
@require_perm("smartmatch.publish")
def save_draft(request):
    campus = _campus_for(request.user)
    with transaction.atomic():
        draft = MatchRule.objects.filter(campus=campus, status=MatchRule.Status.DRAFT).first()
        if draft is None:
            last = MatchRule.objects.filter(campus=campus).aggregate(v=Max("version"))["v"] or 0
            draft = MatchRule(campus=campus, version=last + 1, created_by=request.user)
        draft.w_category = _int(request.POST.get("w_category"))
        draft.w_tags = _int(request.POST.get("w_tags"))
        draft.w_campus = _int(request.POST.get("w_campus"))
        draft.w_availability = _int(request.POST.get("w_availability"))
        draft.w_freshness = _int(request.POST.get("w_freshness"))
        draft.min_score = _int(request.POST.get("min_score"), 40)
        draft.note = request.POST.get("note", "")[:200]
        draft.save()
        record(request.user, "smartmatch.draft_saved", draft, after="borrador", label=f"Reglas v{draft.version}", campus=campus,
               detail={"weights": draft.weights, "min_score": draft.min_score})
    errors = draft.validation_errors()
    if errors:
        messages.warning(request, "Borrador guardado, pero no se puede activar todavía: " + " ".join(errors))
    else:
        messages.success(request, f"Borrador v{draft.version} guardado. Pruébalo en el simulador antes de activarlo.")
    return redirect("smartmatch:rules")


@require_POST
@require_perm("smartmatch.publish")
def activate(request, pk):
    campus = _campus_for(request.user)
    with transaction.atomic():
        rule = get_object_or_404(MatchRule.objects.select_for_update(of=("self",)), pk=pk, campus=campus)
        errors = rule.validation_errors()
        if errors:
            messages.error(request, "No se activó: " + " ".join(errors))
            return redirect("smartmatch:rules")
        previous = MatchRule.objects.filter(campus=campus, status=MatchRule.Status.ACTIVE).exclude(pk=rule.pk)
        prev_versions = list(previous.values_list("version", flat=True))
        previous.update(status=MatchRule.Status.RETIRED)
        rule.status = MatchRule.Status.ACTIVE
        rule.activated_at = timezone.now()
        rule.save(update_fields=["status", "activated_at"])
        record(request.user, "smartmatch.rule_activated", rule, before=f"v{prev_versions[0]}" if prev_versions else "", after=f"v{rule.version}",
               label=f"Reglas v{rule.version}", campus=campus, detail={"weights": rule.weights})
    messages.success(request, f"Reglas v{rule.version} activas para {campus}.")
    return redirect("smartmatch:rules")


@require_POST
@require_perm("smartmatch.publish")
def need_save(request):
    campus = _campus_for(request.user)
    label = request.POST.get("label", "").strip()[:100]
    category = request.POST.get("category", "")
    tags = normalize_tags(request.POST.get("tags", ""))
    if len(label) < 3 or category not in CATEGORY_LABELS or not tags:
        messages.error(request, "La necesidad requiere nombre, categoría y al menos una etiqueta.")
        return redirect("smartmatch:rules")
    code = slugify(label)[:60]
    need, created = Need.objects.update_or_create(campus=campus, code=code, defaults={"label": label, "category": category, "tags": tags, "enabled": True})
    record(request.user, "smartmatch.need_saved", need, after="activa", label=label, campus=campus)
    messages.success(request, f"Necesidad «{label}» {'creada' if created else 'actualizada'}.")
    return redirect("smartmatch:rules")


@require_POST
@require_perm("smartmatch.publish")
def need_toggle(request, pk):
    campus = _campus_for(request.user)
    need = get_object_or_404(Need, pk=pk, campus=campus)
    need.enabled = not need.enabled
    need.save(update_fields=["enabled"])
    record(request.user, "smartmatch.need_toggled", need, after="activa" if need.enabled else "desactivada", label=need.label, campus=campus)
    messages.success(request, f"«{need.label}» {'activada' if need.enabled else 'desactivada'}.")
    return redirect("smartmatch:rules")
