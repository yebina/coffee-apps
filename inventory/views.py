from django.shortcuts import render

from .models import Coffee, GreenLot


def home(request):
    # 仮のホーム。画面はデモの見た目に合わせて、次の段階で作る（architecture.md「9」の 3〜8）
    return render(
        request,
        "inventory/home.html",
        {
            "coffees": Coffee.objects.with_stock().filter(is_active=True),
            "lots": GreenLot.objects.in_stock().filter(is_active=True),
        },
    )
