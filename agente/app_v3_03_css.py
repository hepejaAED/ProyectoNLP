from __future__ import annotations

import csv
import json
import os
import re
import time
from datetime import datetime
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

APP_VERSION = "3.4"

HEADERS = {
    "User-Agent": "ProyectoAcademicoClickbait/3.0"
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
# 2. ESTILO VISUAL
# ============================================================

def aplicar_estilo_neobrutalist() -> None:
    """Aplica estilo neobrutalist sin tocar la lógica del agente."""
    st.markdown(
        """
        <style>
        /* =========================
           BARRA SUPERIOR STREAMLIT
           Oculta la barra, pero mantiene visible el botón de abrir sidebar.
        ========================= */

        header[data-testid="stHeader"] {
            height: 0rem !important;
            min-height: 0rem !important;
            background: transparent !important;
            pointer-events: none !important;
            overflow: visible !important;
        }

        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        div[data-testid="stStatusWidget"] {
            display: none !important;
        }

        #MainMenu {
            visibility: hidden !important;
        }

        div[data-testid="collapsedControl"] {
            display: flex !important;
            visibility: visible !important;
            opacity: 1 !important;
            position: fixed !important;
            top: 0.75rem !important;
            left: 0.75rem !important;
            z-index: 999999 !important;
            pointer-events: auto !important;
        }

        div[data-testid="collapsedControl"] button {
            background: #ff4d6d !important;
            color: #111111 !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 4px 4px 0 #111111 !important;
            font-weight: 900 !important;
        }

        div[data-testid="collapsedControl"] button:hover {
            background: #ffbe0b !important;
            transform: translate(2px, 2px);
            box-shadow: 2px 2px 0 #111111 !important;
        }

        /* =========================
           ESTILO GENERAL
        ========================= */

        html, body {
            font-family: Arial, Helvetica, sans-serif;
        }

        .stApp {
            background:
                radial-gradient(circle at top left, #ffe45e 0, #ffe45e 17%, transparent 17%),
                linear-gradient(135deg, #f7f3e8 0%, #f7f3e8 100%);
            color: #111111;
        }

        .block-container {
            max-width: 1180px;
            padding-top: 1.5rem !important;
            padding-bottom: 4rem !important;
        }

        h1 {
            font-size: 3rem !important;
            font-weight: 900 !important;
            line-height: 1.05 !important;
            color: #111111 !important;
            background: #ffffff;
            border: 4px solid #111111;
            box-shadow: 8px 8px 0 #111111;
            padding: 1rem 1.25rem;
            margin-bottom: 1.25rem;
        }

        h2, h3 {
            font-weight: 900 !important;
            color: #111111 !important;
        }

        p, label {
            color: #111111 !important;
        }

        div[data-testid="stMarkdownContainer"] {
            color: #111111 !important;
        }

        /* =========================
           SIDEBAR
        ========================= */

        section[data-testid="stSidebar"] {
            background: #8ecae6;
            border-right: 5px solid #111111;
        }

        section[data-testid="stSidebar"] > div {
            padding-top: 2rem;
        }

        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label {
            color: #111111 !important;
            font-weight: 800 !important;
        }

        section[data-testid="stSidebar"] .stAlert {
            background: #ffdd00;
            border: 3px solid #111111;
            box-shadow: 5px 5px 0 #111111;
            border-radius: 0;
        }

        /* =========================
           BOTONES
        ========================= */

        .stButton > button,
        .stDownloadButton > button {
            background: #ff4d6d !important;
            color: #111111 !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 5px 5px 0 #111111 !important;
            font-weight: 900 !important;
            text-transform: uppercase;
            transition: all 0.08s ease-in-out;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover {
            transform: translate(3px, 3px);
            box-shadow: 2px 2px 0 #111111 !important;
            background: #ffbe0b !important;
            color: #111111 !important;
            border-color: #111111 !important;
        }

        .stButton > button:active,
        .stDownloadButton > button:active {
            transform: translate(5px, 5px);
            box-shadow: none !important;
        }

        /* =========================
           SELECTS Y MULTISELECTS
        ========================= */

        div[data-baseweb="select"] {
            margin-bottom: 1rem !important;
        }

        div[data-baseweb="select"] > div {
            background: #ffffff !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 4px 4px 0 #111111 !important;
            color: #111111 !important;
            min-height: 3.2rem !important;
            height: auto !important;
            padding: 0.35rem 0.5rem !important;
            align-items: center !important;
            overflow: visible !important;
        }

        div[data-baseweb="select"] div[role="combobox"] {
            flex-wrap: wrap !important;
            gap: 0.25rem !important;
            align-items: center !important;
            min-height: 2rem !important;
        }

        div[data-baseweb="select"] input,
        div[data-baseweb="select"] input:focus {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            outline: none !important;
            padding: 0 !important;
            min-width: 7rem !important;
            height: 1.8rem !important;
            color: #111111 !important;
        }

        div[data-baseweb="select"] svg {
            color: #111111 !important;
        }

        div[data-baseweb="tag"] {
            background: #fb5607 !important;
            color: #ffffff !important;
            border: 2px solid #111111 !important;
            border-radius: 0 !important;
            font-weight: 800 !important;
            height: auto !important;
            min-height: 1.8rem !important;
            margin: 0.15rem 0.25rem 0.15rem 0 !important;
            max-width: 100% !important;
            display: flex !important;
            align-items: center !important;
        }

        div[data-baseweb="tag"] span {
            color: #ffffff !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }

        ul[role="listbox"] {
            background: #ffffff !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 5px 5px 0 #111111 !important;
        }

        li[role="option"] {
            color: #111111 !important;
            font-weight: 700 !important;
        }

        li[role="option"]:hover {
            background: #ffdd00 !important;
        }

        /* =========================
           INPUTS NORMALES
           No se aplica a todos los input para no romper multiselects.
        ========================= */

        div[data-baseweb="input"] > div {
            background: #ffffff !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 4px 4px 0 #111111 !important;
            color: #111111 !important;
        }

        div[data-baseweb="input"] input {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #111111 !important;
        }

        textarea {
            background: #ffffff !important;
            border: 3px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 4px 4px 0 #111111 !important;
            color: #111111 !important;
        }

        /* =========================
           SLIDERS
        ========================= */

        div[data-testid="stSlider"] {
            background: #ffffff;
            border: 3px solid #111111;
            box-shadow: 4px 4px 0 #111111;
            padding: 1rem;
            margin-bottom: 1rem;
        }

        div[data-testid="stSlider"] label {
            font-weight: 800 !important;
        }

        /* =========================
           EXPANDERS / TARJETAS
        ========================= */

        div[data-testid="stExpander"] {
            background: #ffffff;
            border: 4px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 7px 7px 0 #111111;
            margin-bottom: 1.25rem;
        }

        div[data-testid="stExpander"] summary {
            font-weight: 900 !important;
            background: #ffdd00;
            border-bottom: 3px solid #111111;
            padding: 0.75rem 1rem;
        }

        div[data-testid="stExpander"] details {
            border-radius: 0 !important;
        }

        /* =========================
           MÉTRICAS
        ========================= */

        div[data-testid="metric-container"] {
            background: #ffffff;
            border: 4px solid #111111;
            border-radius: 0;
            box-shadow: 6px 6px 0 #111111;
            padding: 1rem;
        }

        div[data-testid="metric-container"] label {
            font-weight: 900 !important;
            color: #111111 !important;
        }

        div[data-testid="metric-container"] [data-testid="stMetricValue"] {
            font-size: 2rem !important;
            font-weight: 900 !important;
            color: #111111 !important;
        }

        /* =========================
           ALERTAS
        ========================= */

        div[data-testid="stAlert"] {
            border: 4px solid #111111;
            border-radius: 0;
            box-shadow: 6px 6px 0 #111111;
            font-weight: 700;
        }

        /* =========================
           TABLAS
        ========================= */

        div[data-testid="stDataFrame"] {
            border: 4px solid #111111;
            box-shadow: 7px 7px 0 #111111;
            background: #ffffff;
            padding: 0.25rem;
        }

        /* =========================
           PROGRESS BAR
        ========================= */

        div[data-testid="stProgress"] > div {
            background: #ffffff;
            border: 3px solid #111111;
            border-radius: 0;
        }

        div[data-testid="stProgress"] div div div {
            background-color: #3a86ff !important;
        }

        /* =========================
           DIVIDERS
        ========================= */

        hr {
            border: none;
            border-top: 5px solid #111111;
            margin: 2rem 0;
        }

        /* =========================
           LINKS
        ========================= */

        a {
            color: #3a0ca3 !important;
            font-weight: 800;
            text-decoration: underline;
        }

        a:hover {
            color: #fb5607 !important;
        }

        /* =========================
           CAPTION
        ========================= */

        div[data-testid="stCaptionContainer"] {
            background: #ffffff;
            border: 3px solid #111111;
            box-shadow: 5px 5px 0 #111111;
            padding: 0.75rem 1rem;
            margin-bottom: 1.5rem;
            font-weight: 700;
        }

        /* =========================
           JSON VIEWER / CODE
        ========================= */

        pre {
            background: #ffffff !important;
            border: 4px solid #111111 !important;
            border-radius: 0 !important;
            box-shadow: 6px 6px 0 #111111 !important;
        }

        code {
            color: #111111 !important;
        }

        /* =========================
           RESPONSIVE
        ========================= */

        @media (max-width: 768px) {
            h1 {
                font-size: 2.1rem !important;
            }

            .block-container {
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }

            div[data-testid="metric-container"] [data-testid="stMetricValue"] {
                font-size: 1.4rem !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ============================================================
# 3. FUNCIONES DE LIMPIEZA, JSON Y LOGS
# ============================================================

def limpiar_texto(texto: str | None) -> str | None:
    """Limpia espacios raros y saltos de línea."""
    if texto is None:
        return None

    texto = str(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def limpiar_campo_tsv(valor: object) -> str:
    """
    Limpia un valor antes de escribirlo en el log separado por tabuladores.

    Motivo:
    - Los tabuladores dentro de un campo rompen columnas.
    - Los saltos de línea dentro de RespuestaAgente hacen que Excel/editores
      parezcan desalinear filas.
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

    parsed = urlparse(str(url))
    parsed = parsed._replace(fragment="")
    return urlunparse(parsed)


def cargar_json(ruta: Path) -> list[dict]:
    """Carga un JSON si existe. Si no existe, devuelve lista vacía."""
    DATA_DIR.mkdir(exist_ok=True)

    if not ruta.exists():
        return []

    contenido = ruta.read_text(encoding="utf-8").strip()

    if not contenido:
        return []

    return json.loads(contenido)


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
    cb_bool = bool(cb)

    try:
        score = float(cb_score)
    except Exception:
        score = 0.0

    score = max(0.0, min(1.0, score))
    score = round(score, 4)

    etiqueta = "Clickbait" if cb_bool else "NO Clickbait"

    # Si el modelo manda una etiqueta contradictoria, priorizamos cb.
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

    Los nombres respetan la estructura de ficheros del proyecto:
    - ABC -> data/ABC.json
    - HuffPost -> data/elhuffpost.json
    """
    rutas = {
        "ABC": DATA_DIR / "ABC.json",
        "HuffPost": DATA_DIR / "elhuffpost.json",
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

    Criterio v3:
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

    Si se lanzan dos ejecuciones en el mismo minuto, se añade sufijo -02,
    -03, etc. para no sobrescribir ni mezclar ejecuciones.
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

    # Caso muy improbable: si hay más de 98 ejecuciones en un minuto,
    # añadimos segundos para seguir evitando sobrescrituras.
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

    # Importante: limpiamos cada campo para que cada noticia ocupe una sola línea
    # y no se rompan las columnas al abrirlo en Excel, LibreOffice o editores de texto.
    fila = {
        campo: limpiar_campo_tsv(fila_sin_limpiar.get(campo, ""))
        for campo in CAMPOS_LOG
    }

    existe = ruta_log.exists()

    # utf-8-sig ayuda a que Excel reconozca mejor acentos y eñes.
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
# 4. DESCARGA HTML
# ============================================================

def obtener_soup(url: str) -> BeautifulSoup:
    """Descarga una página y la transforma en objeto BeautifulSoup."""
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


# ============================================================
# 5. LECTORES DE MEDIOS
# ============================================================

class LectorABC:
    """
    Lector específico para ABC.

    Devuelve cada noticia con la estructura común:
    Link, Periódico, Fecha, Título, Subtítulo, Categoría, Contenido.
    """

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
    """
    Lector específico para HuffPost.

    Está preparado con la misma interfaz que LectorABC para poder
    añadir más medios sin tocar el agente.
    """

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

            # Pequeña pausa entre páginas de listado del mismo medio.
            time.sleep(0.3)

            if len(links) >= max_links:
                break

        return links

    def extraer_fecha_json_ld(self, soup: BeautifulSoup) -> str | None:
        """
        Intenta obtener datePublished de JSON-LD.
        Si no aparece, se usará la fecha actual.
        """
        scripts = soup.find_all("script", type="application/ld+json")

        for script in scripts:
            texto = script.get_text(strip=True)

            if not texto:
                continue

            try:
                data = json.loads(texto, strict=False)
            except Exception:
                continue

            candidatos = data if isinstance(data, list) else [data]

            for item in candidatos:
                if not isinstance(item, dict):
                    continue

                fecha = item.get("datePublished") or item.get("dateModified")

                if fecha:
                    return str(fecha)[:10]

        return None

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

            # En HuffPost, la sección Virales se guarda como Cultura
            # para mantener la taxonomía común del dataset.
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


LECTORES = {
    "ABC": LectorABC,
    "HuffPost": LectorHuffPost,
}


# Relación explícita entre medios de la interfaz y ficheros de salida.
# Para añadir más medios en el futuro, añadid el lector a LECTORES y su ruta aquí.
ARCHIVOS_JSON_POR_MEDIO = {
    "ABC": DATA_DIR / "ABC.json",
    "HuffPost": DATA_DIR / "elhuffpost.json",
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

            links = lector.obtener_links_categoria(
                categoria=categoria,
                max_links=max_por_categoria,
            )

            for link in links:
                articulo = lector.extraer_articulo(link, categoria)

                if articulo:
                    articulos.append(articulo)

                time.sleep(pausa_segundos)

    return deduplicar_articulos(articulos)


# ============================================================
# 6. MODELO LLM
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

    # ChatOpenRouter lee OPENROUTER_API_KEY desde el entorno.
    return ChatOpenRouter(
        model=modelo,
        temperature=temperatura,
        max_tokens=900,
        max_retries=2,
    )


# ============================================================
# 7. TOOL DEL AGENTE
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
                cb=bool(cb),
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
        # Si ocurre, normalmente significa que el modelo elegido no soporta bien tool calling.
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
# 8. INTERFAZ STREAMLIT
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

    aplicar_estilo_neobrutalist()

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

    # Si el usuario cambia otro widget después de ejecutar, Streamlit rerenderiza.
    # Gracias a session_state, los resultados no desaparecen.
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
