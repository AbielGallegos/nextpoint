# Pruebas y aseguramiento de calidad

## Ejecuciones registradas (22/11/2026, versión 1.0.0‑prototipo)

| Entorno | Comando | Resultado real |
| --- | --- | --- |
| Python 3.13 · Django 5.2.19 · **PostgreSQL 16** | `DATABASE_URL=… python manage.py test tests` | **89 pruebas, 89 OK** (tras la auditoría; antes 77/77) (incluye concurrencia E2E‑07 con hilos) |
| Python 3.13 · Django 5.2.19 · **SQLite** | `python manage.py test tests` | **89 pruebas: 88 OK, 1 omitida** (E2E‑07 concurrente requiere PostgreSQL) |
| Humo de rutas (7 perfiles, 70 URLs) | script de recorrido con cliente HTTP | 0 fallas; único 403 esperado: estudiante → `/panel/` |
| Instalación limpia | copia sin `.env` ni BD → `init_env` → `migrate` → `seed_demo` ×2 → `test` → `collectstatic` → servidor sin DEBUG sirviendo páginas y estáticos | OK |
| Revisión visual | Chrome headless 1366 px y 390 px: landing, inicio estudiante, SmartMatch, catálogo móvil, panel, préstamo, caso, informes, lección | Corregidos: contraste del logotipo y del botón de acceso, barra de comparación visible por error, relleno del menú lateral, actividad duplicada |

Defectos encontrados por las pruebas y corregidos antes de entregar: `SELECT … FOR UPDATE` sobre joins anulables (solo fallaba en PostgreSQL), parámetro vacío en el simulador SmartMatch (500), orden de validaciones al solicitar un recurso sin ejemplares, prueba de restauración dentro de transacción.

## Auditoría independiente

Ver `docs/AUDITORIA.md`: rastreo de 346 páginas, E2E‑01…07 en Chrome real (68 comprobaciones), 16 sondas de seguridad, 7 de inyección, 22 invariantes de BD y 384 vistas responsive. Se agregaron 12 pruebas de regresión en `tests/test_audit_regressions.py`.

## Detalle por prueba (ejecución en PostgreSQL, previa a la auditoría)

| Prueba | Resultado |
| --- | --- |
| test_admin_misc · test_manager_cannot_edit_other_campus_resource | ✅ ok |
| test_admin_misc · test_policy_versioned_and_module_flag | ✅ ok |
| test_admin_misc · test_support_ticket_flow_and_internal_notes | ✅ ok |
| test_admin_misc · test_tc011_category_appears_in_filters | ✅ ok |
| test_admin_misc · test_tc012_to_015_create_publish_unpublish_resource | ✅ ok |
| test_alerts_courses · test_critical_requires_verification | ✅ ok |
| test_alerts_courses · test_demo_course_two_lessons_50_100 | ✅ ok |
| test_alerts_courses · test_draft_course_hidden | ✅ ok |
| test_alerts_courses · test_e2e04_draft_publish_read_expire | ✅ ok |
| test_alerts_courses · test_e2e05_author_review_enroll_progress | ✅ ok |
| test_alerts_courses · test_tc049_progress_only_own | ✅ ok |
| test_alerts_courses · test_tc052_other_campus_alert_hidden | ✅ ok |
| test_alerts_courses · test_tc055_external_link_requires_https | ✅ ok |
| test_alerts_courses · test_tc056_manager_cannot_publish_global_or_campus | ✅ ok |
| test_auth_security · test_coordinator_cannot_grant_technical_roles | ✅ ok |
| test_auth_security · test_e2e06_manager_of_other_area_denied | ✅ ok |
| test_auth_security · test_last_admin_protection_and_self_change_blocked | ✅ ok |
| test_auth_security · test_logout_requires_post | ✅ ok |
| test_auth_security · test_notification_of_other_user_404 | ✅ ok |
| test_auth_security · test_rate_limit_after_five_failures | ✅ ok |
| test_auth_security · test_security_headers_and_no_store | ✅ ok |
| test_auth_security · test_tc001_student_login_redirects_to_portal | ✅ ok |
| test_auth_security · test_tc002_manager_login_redirects_to_panel | ✅ ok |
| test_auth_security · test_tc003_wrong_password_no_session_and_generic_message | ✅ ok |
| test_auth_security · test_tc004_logout_invalidates_session | ✅ ok |
| test_auth_security · test_tc005_student_denied_admin_routes_and_api | ✅ ok |
| test_auth_security · test_tc006_student_cannot_see_other_students_records | ✅ ok |
| test_auth_security · test_tc007_no_public_role_self_assignment | ✅ ok |
| test_auth_security · test_tc008_suspended_account_rejected_and_sessions_killed | ✅ ok |
| test_auth_security · test_tc009_invitation_single_use | ✅ ok |
| test_auth_security · test_tc062_063_role_assign_revoke_audited | ✅ ok |
| test_auth_security · test_tc066_health_has_no_secrets | ✅ ok |
| test_auth_security · test_tc072_xss_is_escaped | ✅ ok |
| test_auth_security · test_tc073_sqli_in_search_harmless | ✅ ok |
| test_auth_security · test_tc074_csrf_rejected | ✅ ok |
| test_cases · test_coordinator_supervises_read_only | ✅ ok |
| test_cases · test_e2e02_full_flow | ✅ ok |
| test_cases · test_reopen_after_resolution | ✅ ok |
| test_cases · test_student_cannot_impose_resolved | ✅ ok |
| test_cases · test_tc026_assignment_to_instructor_allows_attending | ✅ ok |
| test_cases · test_tc032_cannot_close_or_resolve_without_attention | ✅ ok |
| test_cases · test_tc034_invalid_attachment_rejected_valid_private | ✅ ok |
| test_cases · test_tc075_large_attachment_rejected | ✅ ok |
| test_loans · test_dashboard_counters_match_lists | ✅ ok |
| test_loans · test_db_constraint_one_active_loan_per_unit | ✅ ok |
| test_loans · test_duplicate_open_request_rejected | ✅ ok |
| test_loans · test_e2e01_full_loan_flow_inventory_available_busy_available | ✅ ok |
| test_loans · test_e2e07_parallel_approvals_only_one_wins | ✅ ok |
| test_loans · test_no_self_approval | ✅ ok |
| test_loans · test_student_cannot_change_stock_via_form_fields | ✅ ok |
| test_loans · test_tc017_second_approval_of_single_unit_rejected | ✅ ok |
| test_loans · test_tc020_damaged_return_goes_to_maintenance | ✅ ok |
| test_loans · test_tc023_cancelled_cannot_be_delivered | ✅ ok |
| test_loans · test_tc024_empty_search_state | ✅ ok |
| test_loans · test_tc035_double_submit_same_folio | ✅ ok |
| test_loans · test_validation_dates_and_max_days | ✅ ok |
| test_reports_admin · test_audit_scoped_and_append_only | ✅ ok |
| test_reports_admin · test_e2e08_report_and_export | ✅ ok |
| test_reports_admin · test_publish_resource_without_units_blocked | ✅ ok |
| test_reports_admin · test_reset_requires_confirmation | ✅ ok |
| test_reports_admin · test_tc033_maintenance_blocks_loans | ✅ ok |
| test_reports_admin · test_tc057_kpi_matches_database | ✅ ok |
| test_reports_admin · test_tc059_area_filter_no_leak | ✅ ok |
| test_reports_admin · test_tc061_export_without_permission_denied | ✅ ok |
| test_reports_admin · test_tc064_edit_resource_audited | ✅ ok |
| test_reports_admin · test_tc065_empty_dataset_shows_no_invented_values | ✅ ok |
| test_reports_admin · test_tc067_backup_restore_roundtrip | ✅ ok |
| test_reports_admin · test_tc076_seed_is_idempotent | ✅ ok |
| test_smartmatch · test_e2e03_need_to_request | ✅ ok |
| test_smartmatch · test_no_sensitive_inputs | ✅ ok |
| test_smartmatch · test_tc038_campus_filter | ✅ ok |
| test_smartmatch · test_tc039_disabled_or_unstocked_not_recommended | ✅ ok |
| test_smartmatch · test_tc041_no_results_shows_help | ✅ ok |
| test_smartmatch · test_tc042_new_weights_change_ranking | ✅ ok |
| test_smartmatch · test_tc043_manager_cannot_publish_rules | ✅ ok |
| test_smartmatch · test_tc044_invalid_weights_cannot_activate | ✅ ok |
| test_smartmatch · test_tc045_deterministic_tie_order | ✅ ok |

## Cobertura de la matriz TC del documento

Cubiertos por pruebas automatizadas: TC‑001…009, 011…017, 020, 021, 023…027, 029…032, 034…046, 048…057, 059…067, 072…076.
Verificados con el recorrido de humo y la revisión visual (sin aserción automatizada dedicada): TC‑018, 019 (también dentro de E2E‑01), 028, 047, 058, 068…071, 077 (todo sirve desde la máquina local, sin recursos externos), 078.
TC‑010 se automatizó durante la auditoría (`test_tc010_expired_session_requires_login`). No ejecutados: TC‑079 (revisión formal de logs) y TC‑080 (fallo de respaldo forzado; el comando sí rechaza respaldos vacíos). Accesibilidad: falta auditoría formal WCAG 2.2 con lector de pantalla.
Verificados manualmente: TC‑011…016, 018, 019, 021, 022, 025, 028, 033, 047, 058, 068…071, 077, 078.
No ejecutados: TC‑010 (expiración por tiempo real de sesión: configurada a 2 h, no se esperó), TC‑079 (revisión formal de logs), TC‑080 (fallo de respaldo forzado) — documentados como pendientes.
