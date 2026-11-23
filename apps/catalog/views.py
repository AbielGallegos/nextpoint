from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.access import can_on, managed_area_ids, require_perm, scope_for, student_required
from apps.accounts.models import Area
from apps.audit.services import record

from apps.core.views_utils import paginate

from .forms import CategoryForm, ResourceForm, UnitForm
from .models import InventoryMovement, Resource, ResourceCategory, ResourceUnit


# --------------------------------------------------------------------------- portal estudiante
@student_required
def catalog_list(request):
    user = request.user
    qs = Resource.objects.filter(campus_id=user.campus_id, status=Resource.Status.PUBLISHED).select_related("category", "area", "location").prefetch_related("units")
    q = request.GET.get("q", "").strip()[:80]
    cat = request.GET.get("categoria", "")
    only_available = request.GET.get("disponibles") == "1"
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(code__icontains=q) | Q(category__name__icontains=q))
    if cat:
        qs = qs.filter(category__slug=cat)
    items = []
    for r in qs.order_by("name"):
        r.av = r.availability()
        if only_available and not r.av["available"]:
            continue
        items.append(r)
    categories = ResourceCategory.objects.filter(campus_id=user.campus_id, active=True).annotate(
        n=Count("resources", filter=Q(resources__status=Resource.Status.PUBLISHED))
    )
    return render(request, "catalog/list.html", {"items": items, "categories": categories, "q": q, "cat": cat, "only_available": only_available})


@student_required
def catalog_detail(request, pk):
    resource = get_object_or_404(
        Resource.objects.select_related("category", "area", "location", "campus"),
        pk=pk, campus_id=request.user.campus_id, status=Resource.Status.PUBLISHED,
    )
    from apps.loans.models import LoanRequest

    open_mine = LoanRequest.objects.filter(applicant=request.user, resource=resource, status__in=LoanRequest.OPEN_STATES).first()
    return render(request, "catalog/detail.html", {"r": resource, "av": resource.availability(), "open_mine": open_mine})


# --------------------------------------------------------------------------- panel
def _scoped_resources(user):
    return Resource.objects.filter(scope_for(user, "catalog.manage").q())


def _get_managed(user, pk):
    resource = get_object_or_404(Resource.objects.select_related("area", "campus", "category"), pk=pk)
    if not can_on(user, "catalog.manage", area_id=resource.area_id, campus_id=resource.campus_id):
        raise PermissionDenied
    return resource


@require_perm("catalog.manage")
def manage_list(request):
    qs = _scoped_resources(request.user).select_related("category", "area").prefetch_related("units")
    status = request.GET.get("estado", "")
    q = request.GET.get("q", "").strip()
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    page = paginate(request, qs.order_by("name"))
    for r in page:
        r.av = r.availability()
    units = ResourceUnit.objects.filter(resource__in=_scoped_resources(request.user))
    summary = {s: units.filter(state=s).count() for s in ResourceUnit.State.values}
    return render(request, "catalog/manage_list.html", {"page": page, "status": status, "q": q, "statuses": Resource.Status.choices,
                                                        "summary": summary, "total_units": units.count()})


@require_perm("catalog.manage")
def manage_form(request, pk=None):
    resource = _get_managed(request.user, pk) if pk else None
    areas = Area.objects.filter(pk__in=managed_area_ids(request.user, "catalog.manage"))
    campus = resource.campus if resource else (areas.first().campus if areas.exists() else request.user.campus)
    form = ResourceForm(request.POST or None, instance=resource, areas=areas, campus=campus)
    if request.method == "POST" and form.is_valid():
        if not can_on(request.user, "catalog.manage", area_id=form.cleaned_data["area"].pk):
            raise PermissionDenied
        before = {"status": resource.status, "name": resource.name} if resource else {}
        with transaction.atomic():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.created_by = request.user
            obj.save()
            record(request.user, "resource.updated" if resource else "resource.created", obj, before=before.get("status", ""),
                   after=obj.status, detail={"changed": form.changed_data})
        messages.success(request, "Recurso guardado." + (" Registra sus ejemplares para poder publicarlo." if obj.status == "borrador" else ""))
        return redirect("catalog:manage_detail", pk=obj.pk)
    return render(request, "catalog/manage_form.html", {"form": form, "resource": resource})


@require_perm("catalog.manage")
def manage_detail(request, pk):
    resource = _get_managed(request.user, pk)
    unit_form = UnitForm(campus=resource.campus)
    movements = InventoryMovement.objects.filter(unit__resource=resource).select_related("unit", "actor", "loan_request")[:30]
    from apps.loans.models import LoanRequest

    loans = LoanRequest.objects.filter(resource=resource).select_related("applicant", "unit")[:10]
    return render(request, "catalog/manage_detail.html", {"r": resource, "av": resource.availability(), "units": resource.units.select_related("location"),
                                                          "unit_form": unit_form, "movements": movements, "loans": loans,
                                                          "unit_states": ResourceUnit.State.choices})


@require_POST
@require_perm("catalog.manage")
def add_unit(request, pk):
    resource = _get_managed(request.user, pk)
    form = UnitForm(request.POST, campus=resource.campus)
    if form.is_valid():
        if ResourceUnit.objects.filter(serial=form.cleaned_data["serial"]).exists():
            messages.error(request, "Ya existe un ejemplar con ese código.")
        else:
            with transaction.atomic():
                unit = form.save(commit=False)
                unit.resource = resource
                unit.save()
                InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.REGISTER, state_after=unit.state, actor=request.user, note="Alta de ejemplar")
                record(request.user, "unit.created", unit, after=unit.state, campus=resource.campus, area=resource.area, label=f"{resource.code} · {unit.serial}")
            messages.success(request, f"Ejemplar {unit.serial} registrado.")
    else:
        messages.error(request, "Revisa el código del ejemplar: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("catalog:manage_detail", pk=pk)


@require_POST
@require_perm("catalog.manage")
def unit_state(request, pk, unit_id):
    resource = _get_managed(request.user, pk)
    unit = get_object_or_404(ResourceUnit, pk=unit_id, resource=resource)
    new_state = request.POST.get("state", "")
    note = request.POST.get("note", "").strip()
    allowed = {ResourceUnit.State.AVAILABLE, ResourceUnit.State.REVIEW, ResourceUnit.State.MAINTENANCE, ResourceUnit.State.RETIRED}
    if new_state not in allowed:
        messages.error(request, "Estado no válido.")
        return redirect("catalog:manage_detail", pk=pk)
    if unit.state == ResourceUnit.State.ON_LOAN:
        messages.error(request, "El ejemplar está prestado: registra primero la devolución.")
        return redirect("catalog:manage_detail", pk=pk)
    if new_state != ResourceUnit.State.AVAILABLE and len(note) < 5:
        messages.error(request, "Indica la causa del cambio (mínimo 5 caracteres).")
        return redirect("catalog:manage_detail", pk=pk)
    with transaction.atomic():
        unit = ResourceUnit.objects.select_for_update(of=("self",)).get(pk=unit.pk)
        before = unit.state
        unit.state = new_state
        unit.notes = note[:200]
        unit.save(update_fields=["state", "notes", "updated_at"])
        InventoryMovement.objects.create(unit=unit, kind=InventoryMovement.Kind.STATE, state_before=before, state_after=new_state, actor=request.user, note=note[:200])
        record(request.user, "unit.state_changed", unit, before=before, after=new_state, campus=resource.campus, area=resource.area,
               label=f"{resource.code} · {unit.serial}", detail={"note": note[:120]})
    messages.success(request, f"Ejemplar {unit.serial}: {unit.get_state_display()}.")
    if new_state != ResourceUnit.State.AVAILABLE:
        from apps.loans.models import LoanRequest

        held = list(LoanRequest.objects.filter(unit=unit, status="aprobado").values_list("folio", flat=True))
        if held:
            messages.warning(request, f"Atención: {', '.join(held)} tiene(n) este ejemplar apartado. No podrá entregarse hasta que "
                                      "el ejemplar vuelva a estar disponible; cancela el préstamo con motivo si no se reparará a tiempo.")
    return redirect("catalog:manage_detail", pk=pk)


@require_perm("catalog.manage")
def categories(request):
    areas = Area.objects.filter(pk__in=managed_area_ids(request.user, "catalog.manage"))
    campus = areas.first().campus if areas.exists() else request.user.campus
    form = CategoryForm(request.POST or None, campus=campus)
    if request.method == "POST" and form.is_valid():
        cat = form.save()
        record(request.user, "category.created", cat, after="activa", campus=campus)
        messages.success(request, "Categoría creada; ya aparece en los filtros del catálogo.")
        return redirect("catalog:categories")
    cats = ResourceCategory.objects.filter(campus=campus).annotate(n=Count("resources"))
    return render(request, "catalog/categories.html", {"form": form, "cats": cats})
