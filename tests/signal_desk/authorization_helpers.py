"""Real grants for isolated provider tests; no production policy or credentials."""
from decimal import Decimal
import uuid

from insightbot.signal_desk import authorization as a, costcontrol as c


def approved_plan(plan, tmp_path, limit='5', at=None):
    path = tmp_path / 'spend.jsonl'
    current = a.policy(path, plan['brand_id'])
    rule = a.set_policy(path, plan['brand_id'], monthly_limit=max(Decimal('5'), Decimal(limit)),
                        enabled=True, allow_renew=False, renew_until=None,
                        expected_version=current['version'] if current else 0, actor='fixture-admin', at=at)
    preview = a.preview(path, plan, at=at)
    plan['authorization'] = a.issue(path, plan, actor='fixture-researcher',
        confirmation_id=uuid.uuid4().hex, approval_token=preview['approval_token'], at=at)
    if Decimal(limit) != Decimal(rule['monthly_limit']):
        a.set_policy(path, plan['brand_id'], monthly_limit=limit, enabled=True, allow_renew=False,
                     renew_until=None, expected_version=rule['version'], actor='fixture-admin', at=at)
    return plan
