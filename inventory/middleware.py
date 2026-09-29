from django.http import HttpResponse


class HealthCheckMiddleware:
    """Fly.io のヘルスチェック（GET /healthz）に「ok」と答える。

    ヘルスチェックは HTTPS を通らず、ホスト名も公開用のものではないので、
    SecurityMiddleware（HTTPS への転送）や ALLOWED_HOSTS の確認より前で答える。
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


def client_ip(request) -> str | None:
    """利用者の IP アドレス。Fly.io の手前の仕組みが Fly-Client-IP に入れてくれる。"""
    return request.META.get("HTTP_FLY_CLIENT_IP") or request.META.get("REMOTE_ADDR")
