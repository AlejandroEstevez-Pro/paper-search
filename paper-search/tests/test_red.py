"""Tests del modo de red local.

Lo que más importa aquí es lo que NO pasa: que el servidor no se abra a la
wifi salvo que alguien lo pida a propósito. Un fallo en esa dirección expone
los favoritos, el historial de búsquedas y la clave de la API a cualquiera
conectado a la misma red, así que se prueba desde varios ángulos.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

import app as web
from paper_search.red import (
    FLAG_RED,
    HOST_LOCAL,
    HOST_TODAS,
    VARIABLE_RED,
    RedError,
    host_para,
    ip_local,
    modo_red_activado,
    texto_arranque,
    url_para_el_movil,
)


# ------------------------------------- por defecto, NO se abre a la red


def test_sin_decir_nada_no_se_activa():
    assert modo_red_activado([], {}) is False


def test_con_los_argumentos_normales_tampoco():
    """Los flags de siempre no deben activarlo por efecto colateral."""
    for argv in ([], ["--debug"], ["--port", "5000"], ["algo"], ["--redis"]):
        assert modo_red_activado(argv, {}) is False, argv


def test_el_host_por_defecto_es_solo_este_equipo():
    assert host_para(False) == HOST_LOCAL
    assert HOST_LOCAL == "127.0.0.1"


def test_el_modulo_de_la_app_declara_el_host_local():
    """`app.HOST` sigue siendo 127.0.0.1: el modo red no cambia el valor por
    defecto, lo elige en el arranque."""
    assert web.HOST == HOST_LOCAL


def test_una_variable_de_entorno_ajena_no_lo_activa():
    assert modo_red_activado([], {"PAPER_SEARCH_DB": "x", "RED": "1"}) is False


@pytest.mark.parametrize("valor", ["", "0", "no", "false", "off", " ", "quizá"])
def test_la_variable_con_un_valor_que_no_es_si_no_activa(valor):
    """Ante la duda, no se abre: el valor tiene que decir «sí» claramente."""
    assert modo_red_activado([], {VARIABLE_RED: valor}) is False


# ------------------------------------------------- activación explícita


def test_el_flag_lo_activa():
    assert modo_red_activado([FLAG_RED], {}) is True


def test_el_flag_funciona_junto_a_otros_argumentos():
    assert modo_red_activado(["algo", FLAG_RED, "otro"], {}) is True


@pytest.mark.parametrize("valor", ["1", "true", "si", "sí", "yes", "on", "SI", "True"])
def test_la_variable_de_entorno_tambien_lo_activa(valor):
    assert modo_red_activado([], {VARIABLE_RED: valor}) is True


def test_activado_escucha_en_todas_las_interfaces():
    assert host_para(True) == HOST_TODAS
    assert HOST_TODAS == "0.0.0.0"


# ----------------------------------------------------- detección de la IP


def test_la_ip_local_es_una_ipv4_valida_y_no_loopback():
    """O devuelve algo usable, o falla con un mensaje que explique qué hacer."""
    try:
        direccion = ip_local()
    except RedError as exc:
        assert "ipconfig" in str(exc) or "wifi" in str(exc).lower()
        return

    analizada = ipaddress.ip_address(direccion)
    assert analizada.version == 4
    assert not analizada.is_loopback


def test_si_no_hay_red_falla_con_un_mensaje_util(monkeypatch):
    """Sin conexión no se puede saber la IP: hay que decirlo, no adivinar."""

    class SocketRoto:
        def connect(self, destino):
            raise OSError("network is unreachable")

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: SocketRoto())

    with pytest.raises(RedError) as excinfo:
        ip_local()

    mensaje = str(excinfo.value)
    assert "wifi" in mensaje.lower()
    assert "ipconfig" in mensaje  # dice cómo mirarlo a mano


def test_si_solo_hay_loopback_se_dice_en_vez_de_devolverlo(monkeypatch):
    """Devolver 127.0.0.1 como «la IP del móvil» sería mandar a probar una
    dirección que no puede funcionar."""

    class SocketLoopback:
        def connect(self, destino):
            pass

        def getsockname(self):
            return ("127.0.0.1", 12345)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: SocketLoopback())

    with pytest.raises(RedError, match="loopback"):
        ip_local()


def test_la_deteccion_no_manda_ningun_paquete(monkeypatch):
    """`connect` sobre UDP solo elige interfaz. Si algún día alguien lo
    cambiara por algo que envía datos, este test lo señala."""
    enviados = []

    class SocketEspia:
        def connect(self, destino):
            self.destino = destino

        def send(self, datos):  # pragma: no cover - no debe llamarse
            enviados.append(datos)

        def sendto(self, *a):  # pragma: no cover - no debe llamarse
            enviados.append(a)

        def getsockname(self):
            return ("192.168.1.42", 12345)

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a, **k: SocketEspia())

    assert ip_local() == "192.168.1.42"
    assert enviados == []


def test_la_url_para_el_movil_lleva_ip_y_puerto(monkeypatch):
    import paper_search.red as red

    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.42")

    assert red.url_para_el_movil(5000) == "http://192.168.1.42:5000"


# ------------------------------------------------ la advertencia se ve


def test_en_modo_normal_no_hay_advertencia():
    texto = texto_arranque(5000, False)

    assert "127.0.0.1:5000" in texto
    assert "MODO RED" not in texto
    assert "contraseña" not in texto


def test_en_modo_red_la_advertencia_es_visible(monkeypatch):
    import paper_search.red as red

    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.42")

    texto = red.texto_arranque(5000, True)

    assert "MODO RED LOCAL ACTIVADO" in texto
    assert "http://192.168.1.42:5000" in texto


def test_la_advertencia_dice_QUE_queda_expuesto(monkeypatch):
    """Un «ten cuidado» genérico no lo lee nadie: hay que decir qué se arriesga."""
    import paper_search.red as red

    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.42")

    texto = red.texto_arranque(5000, True).lower()

    assert "no hay contraseña" in texto
    assert "favoritos" in texto and "notas" in texto
    assert "buscado" in texto           # el historial
    assert "cuota" in texto and "dinero" in texto  # el coste real


def test_la_advertencia_dice_como_volver_atras(monkeypatch):
    import paper_search.red as red

    monkeypatch.setattr(red, "ip_local", lambda: "192.168.1.42")

    assert FLAG_RED in red.texto_arranque(5000, True)


def test_si_no_se_sabe_la_ip_la_advertencia_sale_igual(monkeypatch):
    """El servidor YA está escuchando en toda la red: no saber la IP no puede
    hacer que el aviso desaparezca."""
    import paper_search.red as red

    def revienta():
        raise RedError("no hay wifi; míralo con ipconfig")

    monkeypatch.setattr(red, "ip_local", revienta)

    texto = red.texto_arranque(5000, True)

    assert "MODO RED LOCAL ACTIVADO" in texto
    assert "no hay contraseña" in texto.lower()
    assert "ipconfig" in texto


# --------------------------------------------- lo de antes sigue igual


def test_arrancar_sin_argumentos_escucha_solo_en_local(monkeypatch):
    """El test que de verdad protege: `main()` sin flags no abre la red."""
    llamadas = {}

    monkeypatch.setattr(web.app, "run", lambda **kw: llamadas.update(kw))
    monkeypatch.setattr(web.sys, "argv", ["app.py"])
    monkeypatch.delenv(VARIABLE_RED, raising=False)

    web.main()

    assert llamadas["host"] == HOST_LOCAL


def test_arrancar_con_el_flag_escucha_en_todas(monkeypatch):
    llamadas = {}

    monkeypatch.setattr(web.app, "run", lambda **kw: llamadas.update(kw))

    web.main([FLAG_RED])

    assert llamadas["host"] == HOST_TODAS


def test_el_puerto_no_cambia(monkeypatch):
    llamadas = {}
    monkeypatch.setattr(web.app, "run", lambda **kw: llamadas.update(kw))

    web.main([])

    assert llamadas["port"] == web.PUERTO


def test_el_lanzador_de_red_existe_y_pide_confirmacion():
    """Doble clic no debe bastar: el .bat pregunta antes de abrir la red."""
    from pathlib import Path

    guion = (Path(__file__).resolve().parents[1] / "run-red.bat").read_text(
        encoding="utf-8", errors="replace"
    )

    assert "--red" in guion
    assert "set /p" in guion            # pregunta
    assert "Cancelado" in guion         # y respeta el «no»
