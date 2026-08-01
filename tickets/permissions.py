from .models import CustomUser, Ticket


SYSTEM_ROLES = {
    CustomUser.SYSTEM_ADMIN,
    CustomUser.SYSTEM_SUB_ADMIN,
}

TICKET_STAFF_ROLES = SYSTEM_ROLES | {
    CustomUser.CLIENT_ADMIN,
    CustomUser.CLIENT_STAFF,
}

TENANT_ADMIN_ROLES = SYSTEM_ROLES | {
    CustomUser.CLIENT_ADMIN,
}


def is_system_staff(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in SYSTEM_ROLES)
    )


def is_ticket_staff(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in TICKET_STAFF_ROLES)
    )


def is_tenant_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.role in TENANT_ADMIN_ROLES)
    )


def can_manage_simple_password(actor, target):
    """Return whether actor may approve/reset target's Simple Password.

    Real passwords remain one-way hashes. This permission only controls the
    Simple Password workflow and deliberately protects Django
    superusers from app-level administrators.
    """
    if not actor or not actor.is_authenticated or not target or target.is_superuser:
        return False
    if actor.pk == target.pk:
        return bool(target.simple_password_enabled)
    if actor.is_superuser:
        return True
    if actor.role == CustomUser.SYSTEM_ADMIN:
        return True
    if actor.role == CustomUser.SYSTEM_SUB_ADMIN:
        return target.role not in {CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN}
    if actor.role == CustomUser.CLIENT_ADMIN and actor.company_id and target.company_id:
        return (
            target.company_id in actor.company.get_all_subsidiary_ids()
            and target.role not in {CustomUser.SYSTEM_ADMIN, CustomUser.SYSTEM_SUB_ADMIN}
        )
    return False


def can_approve_simple_password(actor, target):
    """Approval follows admin scope; account owners cannot self-approve."""
    return bool(actor and target and actor.pk != target.pk and can_manage_simple_password(actor, target))


def visible_tickets_for(user, queryset=None):
    """
    Return the only tickets a user may read.

    System staff can read all tenants, tenant staff can read their company tree,
    and regular client users can read only tickets they created.
    """
    queryset = queryset if queryset is not None else Ticket.objects.all()
    if not user or not user.is_authenticated:
        return queryset.none()
    if user.is_superuser or user.role in SYSTEM_ROLES:
        return queryset
    if not user.company_id:
        return queryset.none()

    queryset = queryset.filter(
        company_id__in=user.company.get_all_subsidiary_ids()
    )
    if user.role == CustomUser.CLIENT_USER:
        return queryset.filter(created_by=user)
    if user.role in {CustomUser.CLIENT_ADMIN, CustomUser.CLIENT_STAFF}:
        return queryset
    return queryset.none()


def manageable_tickets_for(user, queryset=None):
    queryset = visible_tickets_for(user, queryset)
    if not is_ticket_staff(user):
        return queryset.none()
    return queryset
