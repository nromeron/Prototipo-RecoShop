"""
mtls.py
=======
Identidad del cliente a partir del certificado de la autenticación mutua
(mTLS), parte del Protector del Canal de P-01.

uvicorn termina TLS con CERT_REQUIRED: un cliente sin certificado, o con
uno que no emitió la CA del prototipo, no completa el establecimiento del
canal. Este protocolo añade al `scope` ASGI de cada solicitud el CN del
certificado presentado (`client_cert_cn`). La aplicación toma la identidad
del cliente de ahí y no del cuerpo de la solicitud, de modo que el estado
por cliente (límite de tasa y sospecha) no se evade cambiando un
identificador declarado.

uvicorn 0.27 no expone el certificado del par en el scope; por eso se
extiende el protocolo h11 en lugar de usar un middleware.
"""

from typing import Optional

from uvicorn.protocols.http.h11_impl import H11Protocol


def _common_name(peercert: Optional[dict]) -> Optional[str]:
    if not peercert:
        return None
    for rdn in peercert.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return None


class MTLSH11Protocol(H11Protocol):
    def connection_made(self, transport):  # type: ignore[override]
        super().connection_made(transport)
        ssl_object = transport.get_extra_info("ssl_object")
        cn = _common_name(ssl_object.getpeercert()) if ssl_object is not None else None
        inner = self.app

        async def app_with_identity(scope, receive, send):
            if scope["type"] == "http":
                scope = dict(scope)
                scope["client_cert_cn"] = cn
            await inner(scope, receive, send)

        self.app = app_with_identity
