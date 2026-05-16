from __future__ import annotations

import csv
import json
import os
import re
import time
import html as html_lib
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import streamlit as st
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_openrouter import ChatOpenRouter
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent


# ============================================================
# 1. CONFIGURACIÓN GENERAL
# ============================================================

load_dotenv()

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
RAZONAMIENTOS_DIR = BASE_DIR / "razonamientos"

APP_VERSION = "4.0"

HEADERS = {
    "User-Agent": "ProyectoAcademicoClickbait/4.0 (+uso académico; contacto: localhost)"
}

ABC_CATEGORIAS = {
    "Nacional": "https://www.abc.es/espana/",
    "Internacional": "https://www.abc.es/internacional/",
    "Cultura": "https://www.abc.es/cultura/",
}

HUFFPOST_CATEGORIAS = {
    "Virales": {
        "seccion": "virales",
        "extensiones": [
            "virales#int=submenu_3",
            "virales/2",
            "virales/3",
            "virales/4",
            "virales/5",
        ],
    },
    "Cultura": {
        "seccion": "life/cultura",
        "extensiones": [
            "life/cultura",
            "life/cultura/2",
            "life/cultura/3",
            "life/cultura/4",
            "life/cultura/5",
        ],
    },
    "Nacional": {
        "seccion": "politica",
        "extensiones": [
            "politica#int=ham_1",
            "politica/2",
            "politica/3",
            "politica/4",
            "politica/5",
        ],
    },
    "Internacional": {
        "seccion": "global",
        "extensiones": [
            "global#int=submenu_2",
            "global/2",
            "global/3",
            "global/4",
            "global/5",
        ],
    },
}

OKDIARIO_CATEGORIAS = {
    "Nacional": "https://okdiario.com/espana/feed",
    "Internacional": "https://okdiario.com/internacional/feed",
    "Cultura": "https://okdiario.com/cultura/feed",
}

MINUTOS20_CATEGORIAS = {
    "Nacional": "https://www.20minutos.es/rss/nacional/",
    "Internacional": "https://www.20minutos.es/rss/internacional/",
    "Cultura": "https://www.20minutos.es/rss/cultura/",
}

ELCONFIDENCIAL_CATEGORIAS = {
    "Nacional": "https://rss.elconfidencial.com/espana/",
    "Internacional": "https://rss.elconfidencial.com/mundo/",
    "Cultura": "https://rss.elconfidencial.com/cultura/",
}

ELDIARIO_CATEGORIAS = {
    "Nacional": "https://www.eldiario.es/rss/politica",
    "Internacional": "https://www.eldiario.es/rss/internacional",
    "Cultura": "https://www.eldiario.es/rss/cultura",
}

RTVE_CATEGORIAS = {
    "Nacional": "https://www.rtve.es/noticias/espana/",
    "Internacional": "https://www.rtve.es/noticias/internacional/",
    "Cultura": "https://www.rtve.es/noticias/cultura/",
}

MEDITERRANEO_CATEGORIAS = {
    "Internacional": [
        {"seccion": "internacional", "extension": "internacional"},
    ],
    "Nacional": [
        {"seccion": "espana/andalucia", "extension": "espana/andalucia"},
        {"seccion": "espana/ceuta-y-melilla", "extension": "espana/ceuta-y-melilla"},
        {"seccion": "sucesos-espana", "extension": "sucesos-espana"},
    ],
}

LAVANGUARDIA_CATEGORIAS = {
    "Nacional": "https://www.lavanguardia.com/politica",
    "Internacional": "https://www.lavanguardia.com/internacional",
    "Cultura": "https://www.lavanguardia.com/cultura",
}

CAMPOS_NOTICIA = [
    "Link",
    "Periódico",
    "Fecha",
    "Título",
    "Subtítulo",
    "Categoría",
    "Contenido",
]

CAMPOS_CLASIFICACION = [
    "cb",
    "cb_score",
    "cb_label",
]

CAMPOS_JSON_FINAL = CAMPOS_NOTICIA + CAMPOS_CLASIFICACION

# Log TSV: aunque el fichero conserva extensión .csv, el separador real es tabulador.
# Titular se deja explícito para identificar rápidamente la noticia en Excel/Sheets.
CAMPOS_LOG = [
    "FechaAnalisis",
    "Modelo",
    "ArchivoJSON",
    "EstadoJSON",
    "Link",
    "Periódico",
    "Fecha",
    "Titular",
    "Título",
    "Subtítulo",
    "Categoría",
    "cb",
    "cb_score",
    "cb_label",
    "Motivo",
    "RespuestaAgente",
]


# ============================================================
# 2. FUNCIONES DE LIMPIEZA, JSON Y LOGS
# ============================================================

def limpiar_texto(texto: str | None) -> str | None:
    """Limpia espacios raros y saltos de línea."""
    if texto is None:
        return None

    texto = html_lib.unescape(str(texto))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpiar_html(texto_html: str | None, quitar_enlaces: bool = False) -> str | None:
    """Convierte un fragmento HTML en texto limpio."""
    if not texto_html:
        return None

    soup = BeautifulSoup(str(texto_html), "html.parser")

    if quitar_enlaces:
        for a in soup.find_all("a"):
            a.decompose()

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return limpiar_texto(soup.get_text(" ", strip=True))


def limpiar_campo_tsv(valor: object) -> str:
    """
    Limpia un valor antes de escribirlo en el log separado por tabuladores.
    """
    if valor is None:
        return ""

    texto = str(valor)
    texto = texto.replace("\t", " ")
    texto = re.sub(r"[\r\n]+", " | ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar_url(url: str | None) -> str:
    """Elimina fragmentos de URL para evitar duplicados del tipo #int=..."""
    if not url:
        return ""

    parsed = urlparse(str(url).strip())
    parsed = parsed._replace(fragment="")
    return urlunparse(parsed)


def normalizar_bool(valor: object) -> bool:
    """Convierte valores del LLM a booleano evitando que 'False' sea True."""
    if isinstance(valor, bool):
        return valor

    if isinstance(valor, (int, float)):
        return bool(valor)

    if isinstance(valor, str):
        texto = valor.strip().lower()
        if texto in {"true", "1", "sí", "si", "yes", "clickbait"}:
            return True
        if texto in {"false", "0", "no", "no clickbait", "noclickbait"}:
            return False

    return bool(valor)


def cargar_json(ruta: Path) -> list[dict]:
    """Carga un JSON si existe. Si no existe, devuelve lista vacía."""
    DATA_DIR.mkdir(exist_ok=True)

    if not ruta.exists():
        return []

    contenido = ruta.read_text(encoding="utf-8").strip()

    if not contenido:
        return []

    datos = json.loads(contenido)

    if not isinstance(datos, list):
        raise ValueError(f"El archivo {ruta} existe, pero no contiene una lista JSON.")

    return datos


def guardar_json(ruta: Path, datos: list[dict]) -> None:
    """Guarda una lista de diccionarios en JSON."""
    DATA_DIR.mkdir(exist_ok=True)

    ruta.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalizar_articulo_para_json(articulo: dict) -> dict:
    """Mantiene la estructura base de noticia que ya usáis."""
    articulo_normalizado = {
        campo: articulo.get(campo)
        for campo in CAMPOS_NOTICIA
    }

    articulo_normalizado["Link"] = normalizar_url(articulo_normalizado.get("Link"))
    return articulo_normalizado


def normalizar_clasificacion(cb: bool, cb_score: float, cb_label: str) -> dict:
    """
    Normaliza la clasificación final.

    cb_score representa confianza en la etiqueta asignada, de 0 a 1.
    Por eso una noticia NO clickbait puede tener cb_score=0.9273.
    """
    cb_bool = normalizar_bool(cb)

    try:
        score = float(cb_score)
    except Exception:
        score = 0.0

    score = max(0.0, min(1.0, score))
    score = round(score, 4)

    etiqueta = "Clickbait" if cb_bool else "NO Clickbait"

    if cb_label not in {"Clickbait", "NO Clickbait"}:
        cb_label = etiqueta

    if cb_bool and cb_label != "Clickbait":
        cb_label = "Clickbait"

    if not cb_bool and cb_label != "NO Clickbait":
        cb_label = "NO Clickbait"

    return {
        "cb": cb_bool,
        "cb_score": score,
        "cb_label": cb_label,
    }


def construir_articulo_clasificado(
    articulo: dict,
    cb: bool,
    cb_score: float,
    cb_label: str,
) -> dict:
    """Une la noticia original con la clasificación del agente."""
    articulo_base = normalizar_articulo_para_json(articulo)
    clasificacion = normalizar_clasificacion(cb, cb_score, cb_label)

    articulo_final = {
        **articulo_base,
        **clasificacion,
    }

    return {
        campo: articulo_final.get(campo)
        for campo in CAMPOS_JSON_FINAL
    }


def buscar_indice_por_link(articulos: list[dict], link: str | None) -> int | None:
    """Busca una noticia por Link normalizado dentro de una lista de artículos."""
    link_normalizado = normalizar_url(link)

    if not link_normalizado:
        return None

    for indice, articulo in enumerate(articulos):
        if normalizar_url(articulo.get("Link")) == link_normalizado:
            return indice

    return None


def obtener_ruta_json_medio(periodico: str) -> Path:
    """
    Devuelve el JSON correspondiente al medio.
    """
    rutas = {
        "ABC": DATA_DIR / "ABC.json",
        "HuffPost": DATA_DIR / "elhuffpost.json",
        "OkDiario": DATA_DIR / "okdiario.json",
        "20minutos": DATA_DIR / "20minutos.json",
        "El Confidencial": DATA_DIR / "elconfidencial.json",
        "ElDiario": DATA_DIR / "eldiario.json",
        "RTVE": DATA_DIR / "RTVE.json",
        "Mediterráneo Digital": DATA_DIR / "mediterraneodigital.json",
        "La Vanguardia": DATA_DIR / "lavanguardia.json",
    }

    if periodico not in rutas:
        nombre_seguro = re.sub(r"[^a-zA-Z0-9_-]+", "", periodico).lower()
        return DATA_DIR / f"{nombre_seguro}.json"

    return rutas[periodico]


def articulo_ya_guardado(articulo: dict) -> bool:
    """Comprueba si una noticia ya existe en el JSON de su medio."""
    ruta_json = obtener_ruta_json_medio(str(articulo.get("Periódico", "")))
    datos = cargar_json(ruta_json)
    return buscar_indice_por_link(datos, articulo.get("Link")) is not None


def obtener_articulo_guardado(articulo: dict) -> dict | None:
    """Devuelve la noticia ya guardada si existe en el JSON de su medio."""
    ruta_json = obtener_ruta_json_medio(str(articulo.get("Periódico", "")))
    datos = cargar_json(ruta_json)
    indice = buscar_indice_por_link(datos, articulo.get("Link"))

    if indice is None:
        return None

    return datos[indice]


def guardar_articulo_clasificado(
    articulo: dict,
    cb: bool,
    cb_score: float,
    cb_label: str,
) -> tuple[str, Path]:
    """
    Guarda una noticia clasificada en el JSON del medio correspondiente.

    - Si la noticia NO existe, se añade.
    - Si la noticia YA existe, no se sobrescribe y no se duplica.
    """
    ruta_json = obtener_ruta_json_medio(str(articulo.get("Periódico", "")))
    articulos_existentes = cargar_json(ruta_json)

    indice_existente = buscar_indice_por_link(
        articulos=articulos_existentes,
        link=articulo.get("Link"),
    )

    if indice_existente is not None:
        return "omitida: ya existía en el JSON y no se sobrescribió", ruta_json

    articulo_clasificado = construir_articulo_clasificado(
        articulo=articulo,
        cb=cb,
        cb_score=cb_score,
        cb_label=cb_label,
    )

    articulos_existentes.append(articulo_clasificado)
    guardar_json(ruta_json, articulos_existentes)

    return "añadida", ruta_json


def deduplicar_articulos(articulos: list[dict]) -> list[dict]:
    """Elimina duplicados dentro de la misma ejecución por Link normalizado."""
    vistos: set[str] = set()
    resultado: list[dict] = []

    for articulo in articulos:
        link = normalizar_url(articulo.get("Link"))

        if not link:
            continue

        if link in vistos:
            continue

        vistos.add(link)
        articulo["Link"] = link
        resultado.append(articulo)

    return resultado


def crear_ruta_log_ejecucion() -> Path:
    """
    Crea una ruta de log por ejecución con formato yyyy-mm-dd-HH_mm.csv.
    """
    RAZONAMIENTOS_DIR.mkdir(exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d-%H_%M")
    ruta_base = RAZONAMIENTOS_DIR / f"{fecha}.csv"

    if not ruta_base.exists():
        return ruta_base

    for numero in range(2, 100):
        ruta_candidata = RAZONAMIENTOS_DIR / f"{fecha}-{numero:02d}.csv"

        if not ruta_candidata.exists():
            return ruta_candidata

    fecha_con_segundos = datetime.now().strftime("%Y-%m-%d-%H_%M_%S")
    return RAZONAMIENTOS_DIR / f"{fecha_con_segundos}.csv"


def guardar_razonamiento_csv(
    ruta_log: Path,
    articulo: dict,
    modelo: str,
    cb: bool,
    cb_score: float,
    cb_label: str,
    motivo: str,
    respuesta_agente: str,
    archivo_json: Path,
    estado_json: str,
) -> Path:
    """Añade una fila al CSV/TSV de razonamientos de la ejecución actual."""
    ruta_log.parent.mkdir(exist_ok=True)
    clasificacion = normalizar_clasificacion(cb, cb_score, cb_label)

    fila_sin_limpiar = {
        "FechaAnalisis": datetime.now().isoformat(timespec="seconds"),
        "Modelo": modelo,
        "ArchivoJSON": str(archivo_json),
        "EstadoJSON": estado_json,
        "Link": articulo.get("Link"),
        "Periódico": articulo.get("Periódico"),
        "Fecha": articulo.get("Fecha"),
        "Titular": articulo.get("Título"),
        "Título": articulo.get("Título"),
        "Subtítulo": articulo.get("Subtítulo"),
        "Categoría": articulo.get("Categoría"),
        "cb": clasificacion["cb"],
        "cb_score": clasificacion["cb_score"],
        "cb_label": clasificacion["cb_label"],
        "Motivo": motivo,
        "RespuestaAgente": respuesta_agente,
    }

    fila = {
        campo: limpiar_campo_tsv(fila_sin_limpiar.get(campo, ""))
        for campo in CAMPOS_LOG
    }

    existe = ruta_log.exists()

    with ruta_log.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=CAMPOS_LOG,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )

        if not existe:
            writer.writeheader()

        writer.writerow(fila)

    return ruta_log


# ============================================================
# 3. DESCARGA HTML / RSS
# ============================================================

def obtener_soup(url: str, timeout: int = 15) -> BeautifulSoup:
    """Descarga una página y la transforma en objeto BeautifulSoup."""
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def obtener_bytes(url: str, timeout: int = 15) -> bytes:
    """Descarga contenido binario/textual manteniendo headers comunes."""
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.content


def parsear_fecha_rss(fecha_raw: str | None) -> str | None:
    """Convierte una fecha RSS a YYYY-MM-DD."""
    if not fecha_raw:
        return None

    try:
        return parsedate_to_datetime(fecha_raw).strftime("%Y-%m-%d")
    except Exception:
        match = re.search(r"\d{4}-\d{2}-\d{2}", fecha_raw)
        return match.group(0) if match else None


def nombre_local_xml(tag: str) -> str:
    """Devuelve el nombre local de una etiqueta XML con o sin namespace."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag.split(":")[-1]


def texto_xml(item: ET.Element, nombres: set[str], ultimo: bool = False) -> str | None:
    """Extrae texto de hijos XML comparando por nombre local."""
    coincidencias = []

    for child in list(item):
        if nombre_local_xml(child.tag) in nombres:
            texto = "".join(child.itertext()).strip()
            if texto:
                coincidencias.append(texto)

    if not coincidencias:
        return None

    return coincidencias[-1] if ultimo else coincidencias[0]


def extraer_items_rss(url: str) -> list[ET.Element]:
    """Extrae items de un RSS usando ElementTree; si falla, devuelve lista vacía."""
    contenido = obtener_bytes(url)

    try:
        root = ET.fromstring(contenido)
    except Exception:
        return []

    return list(root.findall(".//item"))


def extraer_json_ld(soup: BeautifulSoup) -> list[dict]:
    """Devuelve diccionarios JSON-LD presentes en una página."""
    resultados: list[dict] = []

    def recolectar(objeto):
        if isinstance(objeto, dict):
            resultados.append(objeto)
            for valor in objeto.values():
                recolectar(valor)
        elif isinstance(objeto, list):
            for item in objeto:
                recolectar(item)

    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        texto = script.get_text(strip=True)
        if not texto:
            continue

        try:
            data = json.loads(texto, strict=False)
        except Exception:
            continue

        recolectar(data)

    return resultados


def extraer_campo_json_ld(soup: BeautifulSoup, campos: list[str]) -> str | None:
    """Busca el primer campo disponible en objetos JSON-LD."""
    for obj in extraer_json_ld(soup):
        for campo in campos:
            valor = obj.get(campo)
            if isinstance(valor, str) and valor.strip():
                return limpiar_texto(valor)
    return None


def extraer_meta(soup: BeautifulSoup, nombres: list[dict]) -> str | None:
    """Busca content en meta tags por atributos."""
    for attrs in nombres:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return limpiar_texto(tag.get("content"))
    return None


# ============================================================
# 4. LECTORES DE MEDIOS
# ============================================================

class LectorRSSBase:
    """Lector base para medios que exponen noticias por RSS."""

    periodico = ""
    categorias: dict[str, str] = {}
    usar_resumen_como_contenido = False
    quitar_enlaces_subtitulo = False

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        url_feed = self.categorias[categoria]
        articulos = self.extraer_articulos_feed(url_feed, categoria, max_links)

        links = []
        for articulo in articulos:
            link = normalizar_url(articulo.get("Link"))
            if not link:
                continue
            self._cache[link] = articulo
            links.append(link)

        return links

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        return self._cache.get(normalizar_url(url_articulo))

    def extraer_articulos_feed(self, url_feed: str, categoria: str, max_links: int) -> list[dict]:
        articulos: list[dict] = []

        try:
            items = extraer_items_rss(url_feed)
        except Exception as exc:
            print(f"Error leyendo RSS {url_feed}: {exc}")
            return articulos

        for item in items[:max_links]:
            titulo = texto_xml(item, {"title"})
            link = texto_xml(item, {"link"})
            fecha_raw = texto_xml(item, {"pubDate", "published", "updated"})
            descripcion_html = texto_xml(item, {"description", "summary"})
            contenido_html = texto_xml(item, {"encoded", "content"}, ultimo=True)

            subtitulo = limpiar_html(
                descripcion_html,
                quitar_enlaces=self.quitar_enlaces_subtitulo,
            )

            if self.usar_resumen_como_contenido:
                contenido = subtitulo
            else:
                contenido = limpiar_html(contenido_html) or subtitulo

            articulo = {
                "Link": normalizar_url(link),
                "Periódico": self.periodico,
                "Fecha": parsear_fecha_rss(fecha_raw),
                "Título": limpiar_texto(titulo),
                "Subtítulo": subtitulo,
                "Categoría": categoria,
                "Contenido": contenido,
            }

            if articulo["Link"] and articulo["Título"] and articulo["Contenido"]:
                articulos.append(articulo)

        return articulos


class LectorABC:
    """Lector específico para ABC."""

    periodico = "ABC"
    categorias = ABC_CATEGORIAS

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        url_categoria = self.categorias[categoria]
        soup = obtener_soup(url_categoria)

        links: list[str] = []

        for a in soup.select("a.v-a-lnk, h2.v-a-t a"):
            href = a.get("href")

            if not href:
                continue

            url_absoluta = normalizar_url(urljoin(url_categoria, href))
            parsed = urlparse(url_absoluta)

            if not parsed.netloc.endswith("abc.es"):
                continue

            if not parsed.path.endswith(".html"):
                continue

            if url_absoluta not in links:
                links.append(url_absoluta)

            if len(links) >= max_links:
                break

        return links

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        try:
            soup = obtener_soup(url_articulo)

            script = soup.find("script", id="evo-swg-markup")

            if script is None:
                print(f"No se encontró JSON-LD en {url_articulo}")
                return None

            json_text = script.get_text(strip=True)
            data = json.loads(json_text, strict=False)

            if isinstance(data, list):
                candidatos = [
                    item for item in data
                    if isinstance(item, dict)
                ]
                data = next(
                    (item for item in candidatos if "headline" in item),
                    candidatos[0] if candidatos else {},
                )

            fecha_completa = data.get("datePublished")
            fecha = fecha_completa[:10] if fecha_completa else None

            main_entity = data.get("mainEntityOfPage") or {}

            if isinstance(main_entity, dict):
                link = main_entity.get("@id", url_articulo)
            else:
                link = url_articulo

            articulo = {
                "Link": normalizar_url(link),
                "Periódico": self.periodico,
                "Fecha": fecha,
                "Título": limpiar_texto(data.get("headline")),
                "Subtítulo": limpiar_texto(data.get("description")),
                "Categoría": categoria,
                "Contenido": limpiar_texto(data.get("articleBody")),
            }

            if not articulo["Título"] or not articulo["Contenido"]:
                return None

            return articulo

        except json.JSONDecodeError:
            print(f"Error leyendo JSON-LD en {url_articulo}")
            return None

        except Exception as exc:
            print(f"Error extrayendo {url_articulo}: {exc}")
            return None


class LectorHuffPost:
    """Lector específico para HuffPost."""

    periodico = "HuffPost"
    dominio = "www.huffingtonpost.es"
    base = f"https://{dominio}"
    categorias = HUFFPOST_CATEGORIAS

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        config = self.categorias[categoria]
        seccion = config["seccion"]
        extensiones = config["extensiones"]

        links: list[str] = []

        for extension in extensiones:
            url_seccion = urljoin(self.base + "/", extension)
            soup = obtener_soup(url_seccion)

            for enlace in soup.find_all("a"):
                href = enlace.get("href")

                if not href:
                    continue

                url_absoluta = normalizar_url(urljoin(self.base, href))
                parsed = urlparse(url_absoluta)

                if parsed.netloc != self.dominio:
                    continue

                if not parsed.path.startswith(f"/{seccion}/"):
                    continue

                if not parsed.path.endswith(".html"):
                    continue

                if url_absoluta not in links:
                    links.append(url_absoluta)

                if len(links) >= max_links:
                    return links

            time.sleep(0.3)

            if len(links) >= max_links:
                break

        return links

    def extraer_fecha_json_ld(self, soup: BeautifulSoup) -> str | None:
        fecha = extraer_campo_json_ld(soup, ["datePublished", "dateModified"])
        return fecha[:10] if fecha else None

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        try:
            soup = obtener_soup(url_articulo)

            titulo = soup.find("h1")
            titulo = titulo.get_text(" ", strip=True) if titulo else None

            subtitulo = soup.find("h2")
            subtitulo = subtitulo.get_text(" ", strip=True) if subtitulo else None

            cuerpo = soup.find("div", class_="c-detail__body")

            if cuerpo:
                parrafos = cuerpo.find_all("p")
                contenido = "\n".join(
                    p.get_text(" ", strip=True).replace("  ", " ")
                    for p in parrafos
                )
            else:
                contenido = ""

            fecha = self.extraer_fecha_json_ld(soup)
            if not fecha:
                fecha = datetime.now().strftime("%Y-%m-%d")

            categoria_guardado = "Cultura" if categoria == "Virales" else categoria

            articulo = {
                "Link": normalizar_url(url_articulo),
                "Periódico": self.periodico,
                "Fecha": fecha,
                "Título": limpiar_texto(titulo),
                "Subtítulo": limpiar_texto(subtitulo),
                "Categoría": categoria_guardado,
                "Contenido": limpiar_texto(contenido),
            }

            if not articulo["Título"] or not articulo["Contenido"]:
                return None

            return articulo

        except Exception as exc:
            print(f"Error extrayendo {url_articulo}: {exc}")
            return None


class LectorOkDiario(LectorRSSBase):
    periodico = "OkDiario"
    categorias = OKDIARIO_CATEGORIAS
    quitar_enlaces_subtitulo = True


class Lector20Minutos(LectorRSSBase):
    periodico = "20minutos"
    categorias = MINUTOS20_CATEGORIAS


class LectorElConfidencial(LectorRSSBase):
    periodico = "El Confidencial"
    categorias = ELCONFIDENCIAL_CATEGORIAS


class LectorElDiario(LectorRSSBase):
    periodico = "ElDiario"
    categorias = ELDIARIO_CATEGORIAS
    usar_resumen_como_contenido = True

    def extraer_articulos_feed(self, url_feed: str, categoria: str, max_links: int) -> list[dict]:
        articulos = super().extraer_articulos_feed(url_feed, categoria, max_links)
        for articulo in articulos:
            articulo["Subtítulo"] = articulo.get("Subtítulo") or ""
        return articulos


class LectorRTVE:
    """Lector específico para RTVE basado en scraping de secciones."""

    periodico = "RTVE"
    categorias = RTVE_CATEGORIAS

    def limpiar_titulo(self, titulo: str | None) -> str | None:
        titulo = limpiar_texto(titulo)
        if not titulo:
            return None
        return re.sub(r"^\d{1,2}:\d{2}\s*min", "", titulo).strip()

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        url_categoria = self.categorias[categoria]
        soup = obtener_soup(url_categoria, timeout=20)
        articles = soup.find_all("article")

        links: list[str] = []

        for art in articles:
            a_tag = art.find("a", href=True)
            if not a_tag:
                continue

            link = normalizar_url(urljoin(url_categoria, a_tag["href"]))

            if "/noticias/" not in link:
                continue

            if link not in links:
                links.append(link)

            if len(links) >= max_links:
                break

        return links

    def extraer_fecha(self, soup: BeautifulSoup) -> str | None:
        time_tag = soup.find("time")

        if time_tag:
            raw = time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
            match = re.search(r"\d{4}-\d{2}-\d{2}", raw)
            if match:
                return match.group(0)

        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if meta and meta.get("content"):
            match = re.search(r"\d{4}-\d{2}-\d{2}", meta["content"])
            if match:
                return match.group(0)

        return None

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        try:
            soup = obtener_soup(url_articulo, timeout=20)

            titulo = self.limpiar_titulo(
                extraer_meta(soup, [{"property": "og:title"}])
                or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)
            )

            subtitulo = extraer_meta(soup, [{"name": "description"}, {"property": "og:description"}])

            article = soup.find("article")
            parrafos = article.find_all("p") if article else soup.find_all("p")

            textos = []
            for p in parrafos:
                txt = limpiar_texto(p.get_text(" ", strip=True))
                if txt and len(txt) > 40:
                    textos.append(txt)

            if subtitulo and textos and textos[0] == subtitulo:
                textos = textos[1:]

            contenido = " ".join(textos[:8]) if textos else ""

            articulo = {
                "Link": normalizar_url(url_articulo),
                "Periódico": self.periodico,
                "Fecha": self.extraer_fecha(soup),
                "Título": titulo,
                "Subtítulo": subtitulo,
                "Categoría": categoria,
                "Contenido": limpiar_texto(contenido),
            }

            if not articulo["Título"] or not articulo["Contenido"]:
                return None

            return articulo

        except Exception as exc:
            print(f"Error extrayendo RTVE {url_articulo}: {exc}")
            return None


class LectorMediterraneoDigital:
    """Lector específico para Mediterráneo Digital."""

    periodico = "Mediterráneo Digital"
    dominio = "www.mediterraneodigital.com"
    base = f"https://{dominio}"
    categorias = MEDITERRANEO_CATEGORIAS

    def obtener_urls_config(
        self,
        seccion: str,
        extension: str,
        max_links: int,
        limit: int = 7,
        limite_peticiones: int = 10,
    ) -> list[str]:
        urls: list[str] = []
        start = 0
        contador = 0

        while contador < limite_peticiones and len(urls) < max_links:
            url = f"{self.base}/{seccion}?limit={limit}&start={start}&tmpl=component"

            try:
                soup = obtener_soup(url)
            except Exception:
                break

            enlaces = soup.find_all("a", href=True)
            nuevos: list[str] = []

            for a in enlaces:
                href = a["href"]
                absoluta = normalizar_url(urljoin(self.base, href))

                if absoluta.startswith(f"{self.base}/{extension}/"):
                    nuevos.append(absoluta)

            if not nuevos:
                break

            for u in nuevos:
                if u not in urls:
                    urls.append(u)
                    if len(urls) >= max_links:
                        break

            start += limit
            contador += 1

        return urls

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        configs = self.categorias[categoria]
        links: list[str] = []

        for config in configs:
            disponibles = self.obtener_urls_config(
                seccion=config["seccion"],
                extension=config["extension"],
                max_links=max_links,
            )

            for link in disponibles:
                if link not in links:
                    links.append(link)

                if len(links) >= max_links:
                    return links

        return links

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        try:
            soup = obtener_soup(url_articulo)

            h1 = soup.find("h1", class_="article-title") or soup.find("h1")
            if h1:
                a = h1.find("a")
                titulo = a.get_text(" ", strip=True) if a else h1.get_text(" ", strip=True)
            else:
                titulo = None

            subtitulo = soup.find("h2")
            subtitulo = subtitulo.get_text(" ", strip=True) if subtitulo else None

            cuerpo = soup.find("section", class_="article-content clearfix") or soup.find("article")

            if cuerpo:
                parrafos = cuerpo.find_all("p")
                contenido = "\n".join(
                    p.get_text(" ", strip=True).replace("  ", " ")
                    for p in parrafos
                )
            else:
                contenido = ""

            articulo = {
                "Link": normalizar_url(url_articulo),
                "Periódico": self.periodico,
                "Fecha": datetime.now().strftime("%Y-%m-%d"),
                "Título": limpiar_texto(titulo),
                "Subtítulo": limpiar_texto(subtitulo),
                "Categoría": categoria,
                "Contenido": limpiar_texto(contenido),
            }

            if not articulo["Título"] or not articulo["Contenido"]:
                return None

            return articulo

        except Exception as exc:
            print(f"Error extrayendo Mediterráneo Digital {url_articulo}: {exc}")
            return None


class LectorLaVanguardia:
    """
    Lector específico para La Vanguardia.

    El notebook subido importaba un script externo no incluido. Aquí se implementa
    un lector directo de secciones públicas y extracción genérica por meta/JSON-LD.
    """

    periodico = "La Vanguardia"
    dominio = "www.lavanguardia.com"
    categorias = LAVANGUARDIA_CATEGORIAS

    def obtener_links_categoria(self, categoria: str, max_links: int = 5) -> list[str]:
        url_categoria = self.categorias[categoria]
        soup = obtener_soup(url_categoria)
        parsed_categoria = urlparse(url_categoria)
        prefijo = parsed_categoria.path.rstrip("/") + "/"

        links: list[str] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href")
            link = normalizar_url(urljoin(url_categoria, href))
            parsed = urlparse(link)

            if parsed.netloc != self.dominio:
                continue

            if not parsed.path.startswith(prefijo):
                continue

            # Se evitan portadas y subsecciones vacías.
            if parsed.path.rstrip("/") == parsed_categoria.path.rstrip("/"):
                continue

            if link not in links:
                links.append(link)

            if len(links) >= max_links:
                break

        return links

    def extraer_fecha(self, soup: BeautifulSoup) -> str | None:
        fecha = extraer_campo_json_ld(soup, ["datePublished", "dateModified"])
        if fecha:
            match = re.search(r"\d{4}-\d{2}-\d{2}", fecha)
            if match:
                return match.group(0)

        meta_fecha = extraer_meta(soup, [{"property": "article:published_time"}])
        if meta_fecha:
            match = re.search(r"\d{4}-\d{2}-\d{2}", meta_fecha)
            if match:
                return match.group(0)

        return None

    def extraer_articulo(self, url_articulo: str, categoria: str) -> dict | None:
        try:
            soup = obtener_soup(url_articulo)

            titulo = (
                extraer_campo_json_ld(soup, ["headline"])
                or extraer_meta(soup, [{"property": "og:title"}])
                or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)
            )

            subtitulo = (
                extraer_campo_json_ld(soup, ["description"])
                or extraer_meta(soup, [{"name": "description"}, {"property": "og:description"}])
            )

            contenido = extraer_campo_json_ld(soup, ["articleBody"])

            if not contenido:
                article = soup.find("article")
                parrafos = article.find_all("p") if article else soup.find_all("p")
                textos = [
                    limpiar_texto(p.get_text(" ", strip=True))
                    for p in parrafos
                ]
                textos = [txt for txt in textos if txt and len(txt) > 40]
                contenido = " ".join(textos[:10])

            articulo = {
                "Link": normalizar_url(url_articulo),
                "Periódico": self.periodico,
                "Fecha": self.extraer_fecha(soup),
                "Título": limpiar_texto(titulo),
                "Subtítulo": limpiar_texto(subtitulo),
                "Categoría": categoria,
                "Contenido": limpiar_texto(contenido),
            }

            if not articulo["Título"] or not articulo["Contenido"]:
                return None

            return articulo

        except Exception as exc:
            print(f"Error extrayendo La Vanguardia {url_articulo}: {exc}")
            return None


LECTORES = {
    "ABC": LectorABC,
    "HuffPost": LectorHuffPost,
    "OkDiario": LectorOkDiario,
    "20minutos": Lector20Minutos,
    "El Confidencial": LectorElConfidencial,
    "ElDiario": LectorElDiario,
    "RTVE": LectorRTVE,
    "Mediterráneo Digital": LectorMediterraneoDigital,
    "La Vanguardia": LectorLaVanguardia,
}


# Relación explícita entre medios de la interfaz y ficheros de salida.
ARCHIVOS_JSON_POR_MEDIO = {
    medio: obtener_ruta_json_medio(medio)
    for medio in LECTORES.keys()
}


def obtener_categorias_disponibles(medios: list[str]) -> list[str]:
    """Devuelve la unión de categorías disponibles en los medios seleccionados."""
    categorias: set[str] = set()

    for medio in medios:
        lector_cls = LECTORES[medio]
        categorias.update(lector_cls.categorias.keys())

    return sorted(categorias)


def obtener_articulos(
    medios: list[str],
    categorias: list[str],
    max_por_categoria: int,
    pausa_segundos: float,
) -> list[dict]:
    """
    Obtiene artículos de los medios y categorías seleccionadas.

    Si un medio no tiene una categoría concreta, se ignora esa combinación.
    """
    articulos: list[dict] = []

    for medio in medios:
        lector = LECTORES[medio]()

        for categoria in categorias:
            if categoria not in lector.categorias:
                continue

            try:
                links = lector.obtener_links_categoria(
                    categoria=categoria,
                    max_links=max_por_categoria,
                )
            except Exception as exc:
                print(f"Error obteniendo enlaces de {medio} / {categoria}: {exc}")
                continue

            for link in links:
                try:
                    articulo = lector.extraer_articulo(link, categoria)
                except Exception as exc:
                    print(f"Error extrayendo artículo {link}: {exc}")
                    articulo = None

                if articulo:
                    articulos.append(articulo)

                time.sleep(pausa_segundos)

    return deduplicar_articulos(articulos)


# ============================================================
# 5. MODELO LLM
# ============================================================

def crear_llm(temperatura: float = 0.0) -> ChatOpenRouter:
    """
    Crea el modelo de OpenRouter.

    OPENROUTER_API_KEY y OPENROUTER_MODEL deben estar en .env.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    modelo = os.getenv("OPENROUTER_MODEL")

    if not api_key:
        raise ValueError("Falta OPENROUTER_API_KEY en el fichero .env.")

    if not modelo:
        raise ValueError("Falta OPENROUTER_MODEL en el fichero .env.")

    return ChatOpenRouter(
        model=modelo,
        temperature=temperatura,
        max_tokens=900,
        max_retries=2,
    )


# ============================================================
# 6. TOOL DEL AGENTE
# ============================================================

class GuardarClasificacionArgs(BaseModel):
    """
    Argumentos que el LLM debe generar para guardar la clasificación
    de una noticia.
    """

    cb: bool = Field(
        description="True si la noticia es clickbait. False si no es clickbait."
    )

    cb_score: float = Field(
        description=(
            "Confianza entre 0 y 1 en la etiqueta asignada. "
            "No es necesariamente la probabilidad de clickbait."
        )
    )

    cb_label: Literal["Clickbait", "NO Clickbait"] = Field(
        description="Etiqueta textual de la clasificación."
    )

    motivo: str = Field(
        description="Explicación breve del criterio usado para clasificar la noticia."
    )


def recortar_texto(texto: str | None, limite: int = 3500) -> str:
    """Recorta textos largos para no llenar demasiado el contexto del LLM."""
    if not texto:
        return ""

    if len(texto) <= limite:
        return texto

    return texto[:limite] + "..."


def construir_input_articulo(articulo: dict) -> str:
    """Construye el texto que verá el agente."""
    return f"""
Analiza esta noticia:

Link: {articulo.get("Link")}
Periódico: {articulo.get("Periódico")}
Fecha: {articulo.get("Fecha")}
Categoría: {articulo.get("Categoría")}

Título:
{articulo.get("Título")}

Subtítulo:
{articulo.get("Subtítulo")}

Contenido:
{recortar_texto(articulo.get("Contenido"))}
"""


def crear_agente_para_articulo(llm: ChatOpenRouter, articulo: dict) -> tuple[AgentExecutor, dict]:
    """
    Crea un agente para analizar una noticia concreta.

    La herramienta usa una clausura: el LLM clasifica, pero Python guarda
    exactamente la noticia extraída por el scraper, en el JSON de su medio.
    """
    estado_guardado = {
        "estado_json": "no ejecutado",
        "archivo_json": obtener_ruta_json_medio(str(articulo.get("Periódico", ""))),
    }

    @tool("guardar_clasificacion_noticia", args_schema=GuardarClasificacionArgs)
    def guardar_clasificacion_noticia(
        cb: bool,
        cb_score: float,
        cb_label: str,
        motivo: str,
    ) -> str:
        """
        Guarda la noticia actual en el JSON de su medio con su clasificación.

        Debes usar esta herramienta exactamente una vez para cada noticia nueva analizada.
        """
        estado, ruta_json = guardar_articulo_clasificado(
            articulo=articulo,
            cb=cb,
            cb_score=cb_score,
            cb_label=cb_label,
        )

        estado_guardado["estado_json"] = estado
        estado_guardado["archivo_json"] = ruta_json

        clasificacion = normalizar_clasificacion(cb, cb_score, cb_label)

        return (
            f"Clasificación procesada correctamente.\n"
            f"Archivo JSON: {ruta_json}\n"
            f"Estado en JSON: noticia {estado}.\n"
            f"cb: {clasificacion['cb']}\n"
            f"cb_score: {clasificacion['cb_score']}\n"
            f"cb_label: {clasificacion['cb_label']}\n"
            f"Motivo: {motivo}"
        )

    herramientas = [guardar_clasificacion_noticia]

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """
Eres un agente de PLN especializado en detectar clickbait en noticias de prensa española.

Tu tarea:
1. Leer la noticia.
2. Decidir si es clickbait o no en base a:
   - El titular es sensacionalista o exagerado.
   - Lo que se plantea en el titular no se corresponde con el contenido.
   - Hay mucha redundancia en el contenido que no aporta información real.
   - El titular o subtítulo crea curiosidad artificial ocultando información clave.
   - El titular promete una revelación que el contenido no justifica.
3. Debes llamar exactamente una vez a la herramienta guardar_clasificacion_noticia.
4. No puedes terminar sin usar la herramienta.
5. Después de usar la herramienta, responde con un resumen breve de tu decisión.

Definición operativa de clickbait:
Una noticia puede considerarse clickbait si el titular o el subtítulo intentan atraer clics
mediante exageración, ambigüedad, suspense artificial, carga emocional excesiva,
promesas vagas, curiosidad incompleta o desajuste entre titular y contenido.

No consideres clickbait una noticia solo por ser interesante, polémica o importante.
Si el titular es informativo, concreto y proporcional al contenido, no es clickbait.

Campos que debes enviar a la herramienta:
- cb: true si es clickbait, false si no lo es.
- cb_score: número entre 0 y 1 que representa tu confianza en la etiqueta asignada.
  Ejemplo: si decides NO Clickbait con mucha confianza, cb=false y cb_score=0.93.
- cb_label: "Clickbait" o "NO Clickbait".
- motivo: explicación breve del criterio usado.

Formato de tu respuesta final:
Veredicto: CLICKBAIT o NO CLICKBAIT
Confianza: número de 0 a 1
Motivo: explicación breve
"""
        ),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agente = create_tool_calling_agent(
        llm,
        herramientas,
        prompt,
    )

    ejecutor = AgentExecutor(
        agent=agente,
        tools=herramientas,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        max_iterations=3,
    )

    return ejecutor, estado_guardado


def extraer_clasificacion_de_pasos(pasos: list) -> dict | None:
    """Extrae los argumentos con los que el agente llamó a la herramienta."""
    for accion, _observacion in pasos:
        if getattr(accion, "tool", "") != "guardar_clasificacion_noticia":
            continue

        tool_input = getattr(accion, "tool_input", None)

        if isinstance(tool_input, dict):
            cb = tool_input.get("cb")
            cb_score = tool_input.get("cb_score")
            cb_label = tool_input.get("cb_label")
            motivo = tool_input.get("motivo", "")

            clasificacion = normalizar_clasificacion(
                cb=cb,
                cb_score=float(cb_score),
                cb_label=str(cb_label),
            )

            return {
                **clasificacion,
                "Motivo": str(motivo),
            }

    return None


def analizar_articulo_con_agente(
    llm: ChatOpenRouter,
    articulo: dict,
    ruta_log_ejecucion: Path,
) -> dict:
    """Ejecuta el agente sobre una noticia y devuelve un resumen."""
    ruta_json = obtener_ruta_json_medio(str(articulo.get("Periódico", "")))
    articulo_existente = obtener_articulo_guardado(articulo)

    if articulo_existente is not None:
        return {
            "Periódico": articulo.get("Periódico"),
            "Archivo JSON": str(ruta_json),
            "Título": articulo.get("Título"),
            "Categoría": articulo.get("Categoría"),
            "Link": articulo.get("Link"),
            "cb": articulo_existente.get("cb"),
            "cb_score": articulo_existente.get("cb_score"),
            "cb_label": articulo_existente.get("cb_label", "YA EXISTÍA"),
            "Motivo": "Omitida: la noticia ya estaba guardada en el JSON del medio.",
            "Respuesta del agente": "No se llamó al LLM para evitar duplicar o sobrescribir la noticia.",
            "Estado JSON": "omitida: ya existía",
            "Guardada en JSON": False,
            "Log CSV": "",
        }

    agente, estado_guardado = crear_agente_para_articulo(llm, articulo)

    resultado = agente.invoke({
        "input": construir_input_articulo(articulo)
    })

    respuesta_agente = resultado.get("output", "")
    pasos = resultado.get("intermediate_steps", [])
    clasificacion = extraer_clasificacion_de_pasos(pasos)

    if clasificacion is None:
        return {
            "Periódico": articulo.get("Periódico"),
            "Archivo JSON": str(ruta_json),
            "Título": articulo.get("Título"),
            "Categoría": articulo.get("Categoría"),
            "Link": articulo.get("Link"),
            "cb": None,
            "cb_score": None,
            "cb_label": "SIN CLASIFICAR",
            "Motivo": "El agente no llamó a la herramienta de guardado.",
            "Respuesta del agente": respuesta_agente,
            "Estado JSON": "no guardada",
            "Guardada en JSON": False,
            "Log CSV": "",
        }

    archivo_json = Path(estado_guardado["archivo_json"])
    estado_json = str(estado_guardado["estado_json"])

    ruta_log = guardar_razonamiento_csv(
        ruta_log=ruta_log_ejecucion,
        articulo=articulo,
        modelo=os.getenv("OPENROUTER_MODEL", ""),
        cb=clasificacion["cb"],
        cb_score=clasificacion["cb_score"],
        cb_label=clasificacion["cb_label"],
        motivo=clasificacion["Motivo"],
        respuesta_agente=respuesta_agente,
        archivo_json=archivo_json,
        estado_json=estado_json,
    )

    return {
        "Periódico": articulo.get("Periódico"),
        "Archivo JSON": str(archivo_json),
        "Título": articulo.get("Título"),
        "Categoría": articulo.get("Categoría"),
        "Link": articulo.get("Link"),
        "cb": clasificacion["cb"],
        "cb_score": clasificacion["cb_score"],
        "cb_label": clasificacion["cb_label"],
        "Motivo": clasificacion["Motivo"],
        "Respuesta del agente": respuesta_agente,
        "Estado JSON": estado_json,
        "Guardada en JSON": estado_json == "añadida",
        "Log CSV": str(ruta_log),
    }


# ============================================================
# 7. INTERFAZ STREAMLIT
# ============================================================

def inicializar_estado_interfaz() -> None:
    """Inicializa variables de sesión para que la ejecución no desaparezca al tocar widgets."""
    if "ultima_ejecucion" not in st.session_state:
        st.session_state["ultima_ejecucion"] = None


def preparar_resumen_ui(resultados: list[dict]) -> list[dict]:
    """Prepara el resumen para la tabla de Streamlit sin mostrar el booleano cb."""
    columnas_resumen = [
        "Periódico",
        "Título",
        "Categoría",
        "Etiqueta",
        "Score",
        "Motivo",
        "Estado JSON",
        "Archivo JSON",
        "Link",
    ]

    filas = []

    for resultado in resultados:
        fila = {
            "Periódico": resultado.get("Periódico"),
            "Título": resultado.get("Título"),
            "Categoría": resultado.get("Categoría"),
            "Etiqueta": resultado.get("cb_label"),
            "Score": resultado.get("cb_score"),
            "Motivo": resultado.get("Motivo"),
            "Estado JSON": resultado.get("Estado JSON"),
            "Archivo JSON": resultado.get("Archivo JSON"),
            "Link": resultado.get("Link"),
        }

        filas.append({columna: fila.get(columna) for columna in columnas_resumen})

    return filas


def mostrar_detalle_resultado(resultado: dict) -> None:
    """Muestra una noticia clasificada sin repetir la respuesta completa del agente."""
    col1, col2 = st.columns(2)

    with col1:
        st.metric("Etiqueta", resultado.get("cb_label"))

    with col2:
        st.metric("Score", resultado.get("cb_score"))

    st.write("**Estado JSON:**", resultado.get("Estado JSON"))
    st.write("**Archivo JSON:**", resultado.get("Archivo JSON"))
    st.write("**Motivo:**", resultado.get("Motivo"))
    st.write("**Link:**", resultado.get("Link"))


def calcular_totales(resultados: list[dict]) -> dict:
    """Calcula métricas de la ejecución."""
    total_anadidas = sum(
        1 for resultado in resultados
        if resultado.get("Estado JSON") == "añadida"
    )

    total_omitidas = sum(
        1 for resultado in resultados
        if str(resultado.get("Estado JSON", "")).startswith("omitida")
    )

    total_clickbait = sum(
        1 for resultado in resultados
        if resultado.get("cb") is True
    )

    total_no_clickbait = sum(
        1 for resultado in resultados
        if resultado.get("cb") is False
    )

    return {
        "total_anadidas": total_anadidas,
        "total_omitidas": total_omitidas,
        "total_clickbait": total_clickbait,
        "total_no_clickbait": total_no_clickbait,
    }


def guardar_ejecucion_en_estado(
    medios: list[str],
    categorias: list[str],
    articulos: list[dict],
    resultados: list[dict],
    ruta_log_ejecucion: Path,
) -> None:
    """Guarda la última ejecución para que no desaparezca al cambiar widgets."""
    st.session_state["ultima_ejecucion"] = {
        "fecha_interfaz": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "medios": medios,
        "categorias": categorias,
        "num_articulos": len(articulos),
        "resultados": resultados,
        "ruta_log_ejecucion": str(ruta_log_ejecucion),
        "rutas_json": {
            medio: str(obtener_ruta_json_medio(medio))
            for medio in medios
        },
        **calcular_totales(resultados),
    }


def mostrar_ejecucion_guardada() -> None:
    """Muestra la última ejecución aunque Streamlit haya rerenderizado la página."""
    ejecucion = st.session_state.get("ultima_ejecucion")

    if not ejecucion:
        return

    resultados = ejecucion.get("resultados", [])

    st.subheader("Última ejecución mostrada")
    st.caption(
        f"Ejecutada el {ejecucion.get('fecha_interfaz')} | "
        f"Medios: {', '.join(ejecucion.get('medios', []))} | "
        f"Categorías: {', '.join(ejecucion.get('categorias', []))}"
    )

    if st.button("Limpiar resultados mostrados"):
        st.session_state["ultima_ejecucion"] = None
        st.rerun()

    st.write(
        f"Noticias extraídas sin duplicados en esa ejecución: "
        f"{ejecucion.get('num_articulos', len(resultados))}"
    )

    st.subheader("Resultados de la última ejecución")

    for indice, resultado in enumerate(resultados, start=1):
        titulo = resultado.get("Título", "Sin título")
        periodico = resultado.get("Periódico", "Medio")
        categoria = resultado.get("Categoría", "Categoría")

        with st.expander(f"{indice}. [{periodico} | {categoria}] {titulo}"):
            mostrar_detalle_resultado(resultado)

    st.subheader("Resumen de la última ejecución")
    st.dataframe(preparar_resumen_ui(resultados), use_container_width=True)

    st.success(
        "Proceso terminado. "
        f"Noticias nuevas añadidas: {ejecucion.get('total_anadidas', 0)}. "
        f"Noticias omitidas por estar ya guardadas: {ejecucion.get('total_omitidas', 0)}. "
        f"Clickbait: {ejecucion.get('total_clickbait', 0)}. "
        f"NO Clickbait: {ejecucion.get('total_no_clickbait', 0)}."
    )

    rutas_json = ejecucion.get("rutas_json", {})

    if rutas_json:
        st.info(
            "JSON actualizados por medio:\n"
            + "\n".join(
                f"- {medio}: {ruta}"
                for medio, ruta in rutas_json.items()
            )
        )

    ruta_log = Path(ejecucion.get("ruta_log_ejecucion", ""))

    if ruta_log.exists():
        st.info(f"Log de razonamientos de esta ejecución: {ruta_log}")
    else:
        st.info(
            "No se creó CSV de razonamientos porque todas las noticias "
            "extraídas ya estaban guardadas y se omitieron."
        )


def ejecutar_y_mostrar_agente(
    medios: list[str],
    categorias: list[str],
    max_por_categoria: int,
    pausa_segundos: float,
) -> None:
    """Ejecuta scraping + agente y muestra resultados en directo."""
    llm = crear_llm(temperatura=0.0)
    ruta_log_ejecucion = crear_ruta_log_ejecucion()

    st.subheader("1. Obteniendo noticias")
    articulos = obtener_articulos(
        medios=medios,
        categorias=categorias,
        max_por_categoria=max_por_categoria,
        pausa_segundos=pausa_segundos,
    )

    st.write(f"Noticias extraídas sin duplicados en esta ejecución: {len(articulos)}")

    if not articulos:
        st.warning("No se encontraron artículos.")
        guardar_ejecucion_en_estado(
            medios=medios,
            categorias=categorias,
            articulos=[],
            resultados=[],
            ruta_log_ejecucion=ruta_log_ejecucion,
        )
        return

    st.subheader("2. Analizando noticias nuevas con el agente")

    resultados = []
    progreso = st.progress(0)

    for indice, articulo in enumerate(articulos, start=1):
        titulo = articulo.get("Título", "Sin título")
        periodico = articulo.get("Periódico", "Medio")
        categoria = articulo.get("Categoría", "Categoría")

        with st.expander(f"{indice}. [{periodico} | {categoria}] {titulo}"):
            resultado = analizar_articulo_con_agente(
                llm=llm,
                articulo=articulo,
                ruta_log_ejecucion=ruta_log_ejecucion,
            )
            resultados.append(resultado)
            mostrar_detalle_resultado(resultado)

        progreso.progress(indice / len(articulos))

    st.subheader("3. Resumen")
    st.dataframe(preparar_resumen_ui(resultados), use_container_width=True)

    totales = calcular_totales(resultados)

    st.success(
        "Proceso terminado. "
        f"Noticias nuevas añadidas: {totales['total_anadidas']}. "
        f"Noticias omitidas por estar ya guardadas: {totales['total_omitidas']}. "
        f"Clickbait: {totales['total_clickbait']}. "
        f"NO Clickbait: {totales['total_no_clickbait']}."
    )

    st.info(
        "JSON actualizados por medio:\n"
        + "\n".join(
            f"- {medio}: {obtener_ruta_json_medio(medio)}"
            for medio in medios
        )
    )

    if ruta_log_ejecucion.exists():
        st.info(f"Log de razonamientos de esta ejecución: {ruta_log_ejecucion}")
    else:
        st.info(
            "No se creó CSV de razonamientos porque todas las noticias "
            "extraídas ya estaban guardadas y se omitieron."
        )

    guardar_ejecucion_en_estado(
        medios=medios,
        categorias=categorias,
        articulos=articulos,
        resultados=resultados,
        ruta_log_ejecucion=ruta_log_ejecucion,
    )


def main() -> None:
    st.set_page_config(
        page_title=f"Agente detector de clickbait v{APP_VERSION}",
        layout="wide",
    )

    DATA_DIR.mkdir(exist_ok=True)
    RAZONAMIENTOS_DIR.mkdir(exist_ok=True)
    inicializar_estado_interfaz()

    st.title("Agente detector de clickbait en noticias")
    st.caption(
        f"Versión {APP_VERSION}: scrapea uno o varios medios, clasifica noticias nuevas, "
        "guarda cada medio en su JSON correspondiente y crea un CSV/TSV por ejecución."
    )

    st.sidebar.header("Configuración")

    medios = st.sidebar.multiselect(
        "Medios de comunicación",
        options=list(LECTORES.keys()),
        default=["ABC"],
    )

    if medios:
        categorias_disponibles = obtener_categorias_disponibles(medios)
    else:
        categorias_disponibles = []

    categorias = st.sidebar.multiselect(
        "Categorías",
        options=categorias_disponibles,
        default=["Nacional"] if "Nacional" in categorias_disponibles else categorias_disponibles[:1],
    )

    max_por_categoria = st.sidebar.slider(
        "Máximo de noticias por categoría y medio",
        min_value=1,
        max_value=15,
        value=5,
    )

    pausa_segundos = st.sidebar.slider(
        "Pausa entre peticiones",
        min_value=0.5,
        max_value=3.0,
        value=1.0,
        step=0.5,
    )

    if medios:
        rutas_salida = [
            f"- {medio}: {obtener_ruta_json_medio(medio).name}"
            for medio in medios
        ]
        st.sidebar.info(
            "JSON de salida por medio:\n\n"
            + "\n".join(rutas_salida)
            + "\n\nLogs por ejecución: razonamientos/yyyy-mm-dd-HH_mm.csv"
            + "\n\nSeparador de logs: tabulador"
        )
    else:
        st.sidebar.info("Selecciona un medio para ver sus JSON de salida.")

    ejecucion_realizada_ahora = False

    if st.button("Ejecutar agente"):
        if not medios:
            st.warning("Selecciona al menos un medio de comunicación.")
            return

        if not categorias:
            st.warning("Selecciona al menos una categoría.")
            return

        try:
            ejecutar_y_mostrar_agente(
                medios=medios,
                categorias=categorias,
                max_por_categoria=max_por_categoria,
                pausa_segundos=pausa_segundos,
            )
            ejecucion_realizada_ahora = True

        except Exception as exc:
            st.error(f"No se pudo ejecutar el agente: {exc}")

    if not ejecucion_realizada_ahora:
        mostrar_ejecucion_guardada()

    st.divider()

    st.subheader("JSON actuales por medio")

    medio_para_ver = st.selectbox(
        "Elige un medio para ver o descargar su JSON",
        options=list(LECTORES.keys()),
        index=0,
    )

    ruta_json_ver = obtener_ruta_json_medio(medio_para_ver)

    if st.button("Ver JSON guardado"):
        datos = cargar_json(ruta_json_ver)
        st.json(datos)

    if ruta_json_ver.exists():
        st.download_button(
            label=f"Descargar {ruta_json_ver.name}",
            data=ruta_json_ver.read_text(encoding="utf-8"),
            file_name=ruta_json_ver.name,
            mime="application/json",
        )

    logs_disponibles = sorted(RAZONAMIENTOS_DIR.glob("*.csv"), reverse=True)

    if logs_disponibles:
        st.subheader("Logs de razonamientos")
        log_seleccionado = st.selectbox(
            "Elige un CSV de razonamientos",
            options=logs_disponibles,
            format_func=lambda ruta: ruta.name,
        )

        st.download_button(
            label=f"Descargar {log_seleccionado.name}",
            data=log_seleccionado.read_text(encoding="utf-8-sig"),
            file_name=log_seleccionado.name,
            mime="text/tab-separated-values",
        )


if __name__ == "__main__":
    main()
