from bot.i18n import localize
from bot.misc import EnvKeys


def user_profile_lines(user, first_name, target_id, *, overall_balance,
                       items_count, role, referrals, include_referral_id):
    """Build the common user-profile text lines shared by the admin profile views.

    Returns a list of lines (join with ``"\n"``). ``include_referral_id`` inserts
    the referral_id line — the read-only show-user view includes it, the
    action-panel view does not. Callers append their own extra lines afterward
    (blocked status, earnings stats).
    """
    lines = [
        localize('profile.caption', name=first_name, id=target_id),
        '',
        localize('profile.id', id=target_id),
        localize('profile.balance', amount=user.get('balance'), currency=EnvKeys.PAY_CURRENCY),
        localize('profile.total_topup', amount=overall_balance, currency=EnvKeys.PAY_CURRENCY),
        localize('profile.purchased_count', count=items_count),
        '',
    ]
    if include_referral_id:
        lines.append(localize('profile.referral_id', id=user.get('referral_id')))
    lines += [
        localize('admin.users.referrals', count=referrals),
        localize('admin.users.role', role=role),
        localize('profile.registration_date', dt=user.get('registration_date')),
    ]
    return lines
