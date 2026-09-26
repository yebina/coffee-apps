"""同時に保存しても在庫を超えないこと（architecture.md 5.4）。本物の PostgreSQL で確かめる。"""

import threading
import time
from datetime import date

import pytest
from django.db import connection

from inventory import services
from inventory.models import Adjustment, Allocation, Roast, Sale
from inventory.services import SaleLine, StockError

pytestmark = pytest.mark.django_db(transaction=True)


def _race(monkeypatch, *jobs):
    """引当を試算したあとで少し待たせ、2つの保存がぶつかるようにして同時に実行する。"""
    original = services.plan_allocations

    def slow_plan(*args, **kwargs):
        plan = original(*args, **kwargs)
        time.sleep(0.3)
        return plan

    monkeypatch.setattr(services, "plan_allocations", slow_plan)

    barrier = threading.Barrier(len(jobs))
    results: list[object] = [None] * len(jobs)

    def run(i, job):
        try:
            barrier.wait()
            results[i] = job()
        except Exception as e:  # noqa: BLE001
            results[i] = e
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i, job)) for i, job in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_two_sales_cannot_oversell(monkeypatch, make_roast, product, channel):
    roast = make_roast()  # 425g。200g × 2 個の販売を2つ同時に（計 800g）

    def sale():
        return services.save_sale(
            Sale(sold_on=date(2026, 9, 20), channel=channel), [SaleLine(product, 2)]
        )

    results = _race(monkeypatch, sale, sale)

    assert sum(isinstance(r, Sale) for r in results) == 1
    assert sum(isinstance(r, StockError) for r in results) == 1
    assert Roast.objects.with_stock().get(pk=roast.pk).remaining_g == 25
    assert sum(a.weight_g for a in Allocation.objects.all()) == 400


def test_sale_and_adjustment_cannot_oversell(
    monkeypatch, make_roast, product, channel, tasting_reason
):
    roast = make_roast()  # 425g

    def sale():
        return services.save_sale(
            Sale(sold_on=date(2026, 9, 20), channel=channel), [SaleLine(product, 2)]
        )

    def adjust():
        time.sleep(0.1)  # 販売が先にロックを取る
        return services.save_adjustment(
            Adjustment(roast=roast, delta_g=-100, reason=tasting_reason)
        )

    results = _race(monkeypatch, sale, adjust)

    assert isinstance(results[0], Sale)
    assert isinstance(results[1], StockError)
    assert Roast.objects.with_stock().get(pk=roast.pk).remaining_g == 25
