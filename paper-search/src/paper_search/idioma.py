"""Aviso cuando el término de búsqueda no está escrito en inglés.

PubMed indexa mayoritariamente en inglés: buscar «síndrome de Dravet» devuelve
una fracción de lo que devuelve «Dravet syndrome». Este módulo detecta si el
término viene en español, catalán, euskera o gallego y deja un aviso para que
la persona pueda reescribirlo. **Nunca traduce ni bloquea**: la búsqueda sigue
con el término tal cual, igual que el aviso de alcance ambiguo.

La detección es local y determinista: léxico + morfología, sin llamada a Claude
(no merece una llamada de API, ver docs/decisions.md) y sin dependencias
nuevas. Las librerías de detección de idioma se descartaron por medición, no
por prejuicio: `langdetect` no tiene siquiera perfil de euskera ni de gallego,
y `py3langid` falla el 31% de los términos cortos de este dominio (clasifica
«distròfia muscular» como occitano, «enfermidades raras» como portugués y
—justo el falso positivo que hay que evitar— «Smith-Lemli-Opitz» como euskera
con 0.70 de confianza). Un término de búsqueda son una o dos palabras, y ahí
los detectores estadísticos no tienen suficiente señal.

El sesgo es deliberado hacia el falso negativo: solo se avisa con evidencia
positiva. Un aviso falso sobre `SCN1A` o sobre `de novo mutations` enseñaría a
ignorar todos los avisos de la herramienta, incluido el de alcance.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ESPANOL = "es"
CATALAN = "ca"
EUSKERA = "eu"
GALLEGO = "gl"

# --------------------------------------------------------------------------
# Léxico: palabras que aparecen de verdad en búsquedas de enfermedades raras.
# Se guardan plegadas (minúsculas y sin tildes, ver `_plegar`) para que
# «síndrome» y «sindrome» sean la misma entrada — mucha gente escribe sin
# tildes en un campo de búsqueda.
#
# Regla al ampliar estas listas: si la palabra también es inglesa, NO va aquí;
# va en INGLES. Ese es el origen de casi todos los falsos positivos.
# --------------------------------------------------------------------------
LEXICO: dict[str, frozenset[str]] = {
    ESPANOL: frozenset({
        "sindrome", "enfermedad", "enfermedades", "epilepsia", "distrofia",
        "retraso", "desarrollo", "convulsiones", "convulsion", "tratamiento",
        "mutaciones", "mutacion", "gen", "genes", "esclerosis", "raras",
        "raro", "rara", "ninos", "ninas", "deficiencia", "trastorno",
        "trastornos", "cerebro", "higado", "rinon", "sangre", "musculo",
        "hereditaria", "hereditario", "diagnostico", "sintomas", "causas",
        "estudio", "casos", "infantil", "terapia", "displasia", "ataxia",
        "atrofia", "insuficiencia", "crecimiento", "herencia", "portador",
        "pacientes", "tratamientos", "hallazgos", "pronostico", "leve",
        "grave", "temprano", "tardio", "huesos", "corazon", "pulmon",
        "piel", "vista", "oido", "habla", "marcha", "crisis",
    }),
    CATALAN: frozenset({
        "malaltia", "malalties", "distrofia", "epilepsia", "retard",
        "desenvolupament", "convulsions", "tractament", "tractaments",
        "mutacions", "mutacio", "esclerosi", "rares", "trastorn", "trastorns",
        "nens", "nenes", "deficit", "cervell", "fetge", "ronyo", "sang",
        "muscul", "hereditaria", "diagnostic", "simptomes", "causes",
        "estudi", "casos", "infantil", "terapia", "displasia", "atrofia",
        "insuficiencia", "creixement", "herencia", "portador", "pacients",
        "troballes", "pronostic", "lleu", "greu", "primerenc", "tarda",
        "ossos", "cor", "pulmo", "pell", "vista", "oida", "parla", "marxa",
        "aquesta", "aquest", "sobre",
    }),
    EUSKERA: frozenset({
        # Solo formas inequívocamente vascas: «sindrome» y «epilepsia» a secas
        # se escriben igual en castellano, y meterlas aquí hacía que
        # «síndrome de Dravet» se marcara también como euskera.
        "sindromea", "gaixotasuna", "gaixotasun", "gaixotasunak",
        "arraroak", "arraro", "arraroa", "atzerapena", "atzerapen", "garapen",
        "garapena", "mutazioak", "mutazio", "mutazioa", "genea", "geneak",
        "tratamendua", "tratamendu", "haurrak", "haur", "haurren", "burmuina",
        "gibela", "giltzurruna", "odola", "muskulua", "muskulu", "sintomak",
        "kausak", "azterketa", "kasuak", "sukarra", "konbultsioak",
        "gaitza", "gaitzak", "nahasteak", "nahaste", "hazkuntza",
        "herentzia", "gaixoak", "aurkikuntzak", "arina", "larria", "goiztiarra",
        "hezurrak", "bihotza", "birika", "larruazala", "ikusmena", "entzumena",
        "hizkuntza", "ibilera", "sistemaren", "umeen", "bere", "honen",
    }),
    GALLEGO: frozenset({
        "enfermidade", "enfermidades", "doenza", "doenzas", "atraso",
        "desenvolvemento", "tratamento", "tratamentos", "mutacions",
        "mutacion", "xene", "xenes", "xenetica", "xenetico", "converxencia",
        "conxenita", "conxenito", "raras", "raro", "rara", "nenos", "nenas",
        "deficiencia", "trastorno", "trastornos", "cerebro", "figado", "ril",
        "sangue", "musculo", "hereditaria", "diagnostico", "sintomas",
        "causas", "estudo", "casos", "infantil", "terapia", "displasia",
        "ataxia", "atrofia", "insuficiencia", "crecemento", "herdanza",
        "portador", "pacientes", "achados", "prognostico", "leve", "grave",
        "temperan", "tardio", "osos", "corazon", "pulmon", "pel", "vista",
        "oido", "fala", "marcha", "metabolismo",
    }),
}

# --------------------------------------------------------------------------
# Sufijos morfológicos: dan alcance sin tener que listar todo el vocabulario.
# Solo se aplican a palabras de >= LONGITUD_MINIMA_SUFIJO letras, para que un
# sufijo corto no case con una palabra corta cualquiera.
#
# Ausencias deliberadas, todas por colisión con el inglés médico:
#   -ment  (ca): treatment, development, impairment, management
#   -osa   (es): mucosa, serosa son inglés médico
#   -sion  (es): lesion, expression, vision
#   -plasia: dysplasia es inglés
# --------------------------------------------------------------------------
SUFIJOS: dict[str, tuple[str, ...]] = {
    ESPANOL: ("cion", "ciones", "dad", "dades", "miento", "mientos", "encia",
              "patia", "patias"),
    # "sio"/"sions": el inglés nunca termina así (hipertensió, pressió).
    CATALAN: ("cio", "cions", "sio", "sions", "tat", "tats", "encia", "esa",
              "patia", "paties"),
    # Aglutinación vasca: los sufijos de caso y de derivación son inconfundibles
    # y no aparecen en el inglés médico. Por eso el euskera es la lengua MÁS
    # fiable de las cuatro con este método, pese a ser la típicamente peor
    # servida por los detectores estadísticos.
    EUSKERA: ("tasuna", "tasun", "arena", "aren", "etan", "ekin", "tzeko",
              "tzen", "keta", "kuntza", "ntza", "dura", "garri", "tegi",
              "ekoa", "koa", "rako"),
    GALLEGO: ("cion", "cions", "idade", "idades", "mento", "mentos", "encia",
              "patia", "patias"),
}

# --------------------------------------------------------------------------
# Grafías: secuencias raras en el inglés y en el latín médico.
# Solo se buscan en tokens en minúscula (ver `detectar`), porque en nombres
# propios son frecuentísimas: Opitz, Retzius, Peutz-Jeghers, Creutzfeldt.
# "ts" queda fuera a propósito: aparece en cualquier plural inglés (variants,
# patients, results) y provocaba falsos positivos.
# --------------------------------------------------------------------------
GRAFIAS: dict[str, tuple[str, ...]] = {
    CATALAN: ("l·l", "ny", "tx"),
    EUSKERA: ("tx", "tz", "kk", "rtz", "ntz"),
}

#: Preposiciones y artículos romances. Son señal de "esto no es inglés", pero
#: NUNCA disparan el aviso por sí solas: el inglés médico está lleno de
#: locuciones que las llevan — "de novo mutations", "del 22q11 syndrome",
#: "La Crosse encephalitis", "El Escorial criteria", "torsades de pointes".
#: Solo suman como refuerzo cuando ya hay otra evidencia.
FUNCIONALES_ROMANCE = frozenset({
    "de", "del", "dels", "da", "do", "dos", "das", "la", "el", "els", "les",
    "los", "las", "en", "un", "una", "unha", "e", "y", "i", "o", "a", "ao",
    "coa", "amb", "para", "con", "sobre", "polo", "pola",
})

#: Palabras que también son inglesas. Una palabra de esta lista no aporta
#: evidencia jamás, aunque aparezca en algún léxico de arriba. Es la guarda que
#: evita avisar a quien ya está buscando en inglés: sin ella, "muscular
#: dystrophy" disparaba por «muscular» y "rare disease treatment" por el
#: sufijo «-ment».
INGLES = frozenset({
    "muscular", "treatment", "gene", "genes", "rare", "disease", "diseases",
    "syndrome", "syndromes", "delay", "seizures", "seizure", "epilepsy",
    "dystrophy", "sclerosis", "development", "developmental", "mutations",
    "mutation", "cerebral", "infantile", "familial", "congenital",
    "hereditary", "severe", "early", "onset", "children", "brain", "liver",
    "blood", "kidney", "diagnosis", "symptoms", "causes", "study", "studies",
    "cases", "the", "and", "with", "for", "of", "in", "on", "at", "a", "an",
    "to", "deficiency", "disorder", "disorders", "management", "assessment",
    "impairment", "myoclonic", "febrile", "tuberous", "muscle", "patients",
    "patient", "review", "therapy", "clinical", "novo", "vitro", "vivo",
    "criteria", "variants", "variant", "deletion", "duplication", "carrier",
    "growth", "bone", "bones", "heart", "lung", "skin", "speech", "gait",
    "ataxia", "atrophy", "phenotype", "genotype", "inheritance", "outcome",
    "outcomes", "findings", "prognosis", "mild", "late", "vision", "hearing",
})

#: Un sufijo solo cuenta en palabras de al menos esta longitud.
LONGITUD_MINIMA_SUFIJO = 6

#: Palabras (sin contar genes ni acrónimos) que debe haber para considerar el
#: refuerzo de funcionales: con una sola palabra no hay sintagma que reforzar.
MINIMO_PALABRAS_REFUERZO = 2

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _plegar(texto: str) -> str:
    """Minúsculas y sin tildes: «Síndrome» y «sindrome» son la misma palabra."""
    descompuesto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def _es_codigo(token: str) -> bool:
    """¿Es un gen o un acrónimo? SCN1A, MECP2, TSC1, DMD, 22q11.

    Se mira sobre el token original, sin plegar, porque la pista es la caja:
    todo mayúsculas, o con dígitos. Estos tokens se apartan antes de analizar
    nada, que es lo que impide que un nombre de gen dispare el aviso.
    """
    if any(c.isdigit() for c in token):
        return True
    letras = [c for c in token if c.isalpha()]
    return bool(letras) and all(c.isupper() for c in letras)


@dataclass(frozen=True)
class ResultadoIdioma:
    """Qué se detectó en un término y con qué evidencia."""

    #: Códigos de lengua detectados, ordenados. Puede haber varias: «síndrome
    #: de Dravet» es idéntico en español, catalán y gallego, y no hay forma
    #: —ni necesidad— de desempatar.
    lenguas: tuple[str, ...] = ()
    #: Qué regla disparó cada detección. Es material de depuración y de tests;
    #: no se enseña al usuario.
    evidencia: tuple[str, ...] = ()

    @property
    def avisa(self) -> bool:
        return bool(self.lenguas)

    def aviso(self, termino: str) -> str | None:
        """Texto para CLI y web, o `None` si el término no necesita aviso."""
        if not self.avisa:
            return None
        # No se nombra la lengua concreta a propósito, aunque `lenguas` la
        # traiga. Buena parte del vocabulario médico se escribe igual en las
        # tres lenguas romances («síndrome de Dravet», «distrofia muscular»),
        # así que nombrar una sería acertar por azar; y decirle «parece estar
        # en español» a quien escribió en euskera es un error que se ve. El
        # consejo —reescribir en inglés— es el mismo en los cuatro casos.
        return (
            f"El término «{termino}» parece estar escrito en español o en una "
            f"lengua cooficial (catalán, euskera o gallego). PubMed indexa "
            f"sobre todo artículos en inglés, así que es probable que "
            f"encuentres bastantes menos resultados de los que hay: prueba a "
            f"reescribirlo en inglés (por ejemplo «Dravet syndrome» en vez de "
            f"«síndrome de Dravet», o el nombre del gen, que se escribe igual "
            f"en todos los idiomas). La búsqueda se ha ejecutado igualmente "
            f"con el término tal cual."
        )


def detectar_idioma(termino: str) -> ResultadoIdioma:
    """Detecta si `termino` está en español, catalán, euskera o gallego.

    Devuelve las lenguas compatibles con la evidencia encontrada, o un
    resultado vacío (`avisa == False`) si no hay ninguna. Solo se afirma con
    evidencia positiva: ante la duda, no se avisa.
    """
    tokens = _TOKEN.findall(termino or "")

    # 1. Fuera los genes y acrónimos: «SCN1A» no es una palabra de ningún
    #    idioma, y es justo lo que más se busca en esta herramienta.
    palabras = [t for t in tokens if not _es_codigo(t)]
    if not palabras:
        return ResultadoIdioma()

    # 2. Fuera las palabras que también son inglesas: no pueden ser evidencia
    #    de nada, y son el origen habitual de los falsos positivos.
    utiles = [t for t in palabras if _plegar(t) not in INGLES]
    plegadas = [_plegar(t) for t in utiles]

    lenguas: set[str] = set()
    evidencia: list[str] = []

    for lengua, vocabulario in LEXICO.items():
        for palabra in plegadas:
            if palabra in vocabulario:
                lenguas.add(lengua)
                evidencia.append(f"lexico:{lengua}:{palabra}")

    for lengua, sufijos in SUFIJOS.items():
        for palabra in plegadas:
            if len(palabra) >= LONGITUD_MINIMA_SUFIJO and palabra.endswith(sufijos):
                lenguas.add(lengua)
                evidencia.append(f"sufijo:{lengua}:{palabra}")

    # 3. Las grafías, solo en tokens en minúscula: en un apellido («Opitz»,
    #    «Peutz», «Creutzfeldt») no significan nada.
    for lengua, marcas in GRAFIAS.items():
        for original, palabra in zip(utiles, plegadas):
            if original[:1].isupper():
                continue
            for marca in marcas:
                if marca in palabra:
                    lenguas.add(lengua)
                    evidencia.append(f"grafia:{lengua}:{marca}")

    # 4. Refuerzo, nunca disparo (ver FUNCIONALES_ROMANCE).
    if lenguas and len(palabras) >= MINIMO_PALABRAS_REFUERZO:
        for palabra in plegadas:
            if palabra in FUNCIONALES_ROMANCE:
                evidencia.append(f"refuerzo:{palabra}")

    return ResultadoIdioma(
        lenguas=tuple(sorted(lenguas)), evidencia=tuple(evidencia)
    )


def aviso_de_idioma(termino: str) -> str | None:
    """Atajo: el texto del aviso para `termino`, o `None` si no hace falta."""
    return detectar_idioma(termino).aviso(termino)
