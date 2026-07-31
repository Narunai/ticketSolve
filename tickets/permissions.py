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
