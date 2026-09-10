"""HTTPS with certificate-fingerprint pinning for the agent.

A runner enrolled with `--fingerprint sha256:...` accepts ONLY a control plane presenting that exact
certificate, self-signed or not. Without a pin, the system CA store applies as usual.
"""
import http.client
import ssl
import urllib.request

from .certs import fingerprint_der


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    pin: str = ""

    def connect(self):
        super().connect()
        der = self.sock.getpeercert(binary_form=True)
        got = fingerprint_der(der)
        if got != self.pin:
            self.close()
            raise ssl.SSLError(f"control plane certificate fingerprint {got} does not match pinned {self.pin}")


class PinnedHandler(urllib.request.HTTPSHandler):
    def __init__(self, pin: str):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE       # the pin IS the verification
        super().__init__(context=ctx)
        self.pin = pin

    def https_open(self, req):
        pin = self.pin

        def factory(host, **kw):
            c = PinnedHTTPSConnection(host, context=self._context, **kw)
            c.pin = pin
            return c
        return self.do_open(factory, req)


def opener(pin: str = "") -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(PinnedHandler(pin)) if pin else urllib.request.build_opener()
