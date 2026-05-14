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

# Ahora guardamos TODAS las noticias clasificadas, no solo las clickbait.
ARCHIVO_CLASIFICADO = DATA_DIR / "noticias_clasificadas.json"

HEADERS = {
    "User-Agent": "ProyectoAcademicoClickbait/2.0"
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

CAMPOS_LOG = [
    "FechaAnalisis",
    "Modelo",
    "Link",
    "Periódico",
    "Fecha",
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

    texto = str(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def normalizar_url(url: str) -> str:
    """Elimina fragmentos de URL para evitar duplicados del tipo #int=..."""
    parsed = urlparse(url)
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
    return {
        campo: articulo.get(campo)
        for campo in CAMPOS_NOTICIA
    }


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


def guardar_articulo_clasificado(
    ruta_json: Path,
    articulo: dict,
    cb: bool,
    cb_score: float,
    cb_label: str,
) -> str:
    """
    Guarda o actualiza una noticia clasificada evitando duplicados por Link.

    Devuelve:
    - "añadida" si no existía.
    - "actualizada" si ya existía y se sobrescribió su clasificación.
    """
    articulos_existentes = cargar_json(ruta_json)
    articulo_clasificado = construir_articulo_clasificado(
        articulo=articulo,
        cb=cb,
        cb_score=cb_score,
        cb_label=cb_label,
    )

    link = articulo_clasificado.get("Link")

    for indice, articulo_existente in enumerate(articulos_existentes):
        if articulo_existente.get("Link") == link:
            articulos_existentes[indice] = articulo_clasificado
            guardar_json(ruta_json, articulos_existentes)
            return "actualizada"

    articulos_existentes.append(articulo_clasificado)
    guardar_json(ruta_json, articulos_existentes)
    return "añadida"


def obtener_ruta_log_diario() -> Path:
    """Devuelve la ruta del CSV diario de razonamientos."""
    RAZONAMIENTOS_DIR.mkdir(exist_ok=True)
    fecha = datetime.now().strftime("%Y-%m-%d")
    return RAZONAMIENTOS_DIR / f"{fecha}-criterios.csv"


def guardar_razonamiento_csv(
    articulo: dict,
    modelo: str,
    cb: bool,
    cb_score: float,
    cb_label: str,
    motivo: str,
    respuesta_agente: str,
) -> Path:
    """Añade una fila al CSV diario de razonamientos."""
    ruta_log = obtener_ruta_log_diario()
    clasificacion = normalizar_clasificacion(cb, cb_score, cb_label)

    fila = {
        "FechaAnalisis": datetime.now().isoformat(timespec="seconds"),
        "Modelo": modelo,
        "Link": articulo.get("Link"),
        "Periódico": articulo.get("Periódico"),
        "Fecha": articulo.get("Fecha"),
        "Título": articulo.get("Título"),
        "Subtítulo": articulo.get("Subtítulo"),
        "Categoría": articulo.get("Categoría"),
        "cb": clasificacion["cb"],
        "cb_score": clasificacion["cb_score"],
        "cb_label": clasificacion["cb_label"],
        "Motivo": motivo,
        "RespuestaAgente": respuesta_agente,
    }

    existe = ruta_log.exists()

    with ruta_log.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_LOG)

        if not existe:
            writer.writeheader()

        writer.writerow(fila)

    return ruta_log


# ============================================================
# 3. DESCARGA HTML
# ============================================================

def obtener_soup(url: str) -> BeautifulSoup:
    """Descarga una página y la transforma en objeto BeautifulSoup."""
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


# ============================================================
# 4. LECTORES DE MEDIOS
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

            articulo = {
                "Link": normalizar_url(url_articulo),
                "Periódico": self.periodico,
                "Fecha": fecha,
                "Título": limpiar_texto(titulo),
                "Subtítulo": limpiar_texto(subtitulo),
                "Categoría": categoria,
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

    return articulos


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

    # ChatOpenRouter lee OPENROUTER_API_KEY desde el entorno.
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


def crear_agente_para_articulo(llm: ChatOpenRouter, articulo: dict) -> AgentExecutor:
    """
    Crea un agente para analizar una noticia concreta.

    La herramienta usa una clausura: el LLM clasifica, pero Python guarda
    exactamente la noticia extraída por el scraper.
    """

    @tool("guardar_clasificacion_noticia", args_schema=GuardarClasificacionArgs)
    def guardar_clasificacion_noticia(
        cb: bool,
        cb_score: float,
        cb_label: str,
        motivo: str,
    ) -> str:
        """
        Guarda la noticia actual en el JSON con su clasificación.

        Debes usar esta herramienta exactamente una vez para cada noticia analizada.
        """
        estado = guardar_articulo_clasificado(
            ruta_json=ARCHIVO_CLASIFICADO,
            articulo=articulo,
            cb=cb,
            cb_score=cb_score,
            cb_label=cb_label,
        )

        clasificacion = normalizar_clasificacion(cb, cb_score, cb_label)

        return (
            f"Clasificación guardada correctamente.\n"
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

    return AgentExecutor(
        agent=agente,
        tools=herramientas,
        verbose=True,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
        max_iterations=3,
    )


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


def analizar_articulo_con_agente(llm: ChatOpenRouter, articulo: dict) -> dict:
    """Ejecuta el agente sobre una noticia y devuelve un resumen."""
    agente = crear_agente_para_articulo(llm, articulo)

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
            "Título": articulo.get("Título"),
            "Categoría": articulo.get("Categoría"),
            "Link": articulo.get("Link"),
            "cb": None,
            "cb_score": None,
            "cb_label": "SIN CLASIFICAR",
            "Motivo": "El agente no llamó a la herramienta de guardado.",
            "Respuesta del agente": respuesta_agente,
            "Guardada en JSON": False,
            "Log CSV": "",
        }

    ruta_log = guardar_razonamiento_csv(
        articulo=articulo,
        modelo=os.getenv("OPENROUTER_MODEL", ""),
        cb=clasificacion["cb"],
        cb_score=clasificacion["cb_score"],
        cb_label=clasificacion["cb_label"],
        motivo=clasificacion["Motivo"],
        respuesta_agente=respuesta_agente,
    )

    return {
        "Periódico": articulo.get("Periódico"),
        "Título": articulo.get("Título"),
        "Categoría": articulo.get("Categoría"),
        "Link": articulo.get("Link"),
        "cb": clasificacion["cb"],
        "cb_score": clasificacion["cb_score"],
        "cb_label": clasificacion["cb_label"],
        "Motivo": clasificacion["Motivo"],
        "Respuesta del agente": respuesta_agente,
        "Guardada en JSON": True,
        "Log CSV": str(ruta_log),
    }


# ============================================================
# 7. INTERFAZ STREAMLIT
# ============================================================

def main() -> None:
    st.set_page_config(
        page_title="Agente detector de clickbait v2",
        layout="wide",
    )

    DATA_DIR.mkdir(exist_ok=True)
    RAZONAMIENTOS_DIR.mkdir(exist_ok=True)

    st.title("Agente detector de clickbait en noticias")
    st.caption(
        "Versión 2: scrapea uno o varios medios, clasifica todas las noticias "
        "y guarda el JSON final con cb, cb_score y cb_label."
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

    st.sidebar.info(
        f"JSON de salida: {ARCHIVO_CLASIFICADO.name}\n\n"
        f"Logs diarios: razonamientos/YYYY-MM-DD-criterios.csv"
    )

    if st.button("Ejecutar agente"):
        if not medios:
            st.warning("Selecciona al menos un medio de comunicación.")
            return

        if not categorias:
            st.warning("Selecciona al menos una categoría.")
            return

        try:
            llm = crear_llm(temperatura=0.0)

            st.subheader("1. Obteniendo noticias")
            articulos = obtener_articulos(
                medios=medios,
                categorias=categorias,
                max_por_categoria=max_por_categoria,
                pausa_segundos=pausa_segundos,
            )

            st.write(f"Noticias extraídas: {len(articulos)}")

            if not articulos:
                st.warning("No se encontraron artículos.")
                return

            st.subheader("2. Analizando noticias con el agente")

            resultados = []
            progreso = st.progress(0)

            for indice, articulo in enumerate(articulos, start=1):
                titulo = articulo.get("Título", "Sin título")
                periodico = articulo.get("Periódico", "Medio")
                categoria = articulo.get("Categoría", "Categoría")

                with st.expander(f"{indice}. [{periodico} | {categoria}] {titulo}"):
                    resultado = analizar_articulo_con_agente(llm, articulo)
                    resultados.append(resultado)

                    st.write("**Etiqueta:**", resultado["cb_label"])
                    st.write("**cb:**", resultado["cb"])
                    st.write("**cb_score:**", resultado["cb_score"])
                    st.write("**Motivo:**", resultado["Motivo"])
                    st.write("**Guardada en JSON:**", resultado["Guardada en JSON"])
                    st.write("**Respuesta del agente:**")
                    st.write(resultado["Respuesta del agente"])
                    st.write("**Link:**", resultado["Link"])

                progreso.progress(indice / len(articulos))

            st.subheader("3. Resumen")
            st.dataframe(resultados, use_container_width=True)

            total_clasificadas = sum(
                1 for resultado in resultados
                if resultado["Guardada en JSON"]
            )

            total_clickbait = sum(
                1 for resultado in resultados
                if resultado["cb"] is True
            )

            total_no_clickbait = sum(
                1 for resultado in resultados
                if resultado["cb"] is False
            )

            st.success(
                "Proceso terminado. "
                f"Noticias clasificadas y guardadas: {total_clasificadas}. "
                f"Clickbait: {total_clickbait}. "
                f"NO Clickbait: {total_no_clickbait}."
            )

            st.info(f"JSON actualizado: {ARCHIVO_CLASIFICADO}")
            st.info(f"Log de razonamientos actualizado: {obtener_ruta_log_diario()}")

        except Exception as exc:
            st.error(f"No se pudo ejecutar el agente: {exc}")

    st.divider()

    st.subheader("JSON actual de noticias clasificadas")

    if st.button("Ver JSON guardado"):
        datos = cargar_json(ARCHIVO_CLASIFICADO)
        st.json(datos)

    if ARCHIVO_CLASIFICADO.exists():
        st.download_button(
            label="Descargar noticias_clasificadas.json",
            data=ARCHIVO_CLASIFICADO.read_text(encoding="utf-8"),
            file_name="noticias_clasificadas.json",
            mime="application/json",
        )

    ruta_log = obtener_ruta_log_diario()

    if ruta_log.exists():
        st.download_button(
            label="Descargar CSV de razonamientos de hoy",
            data=ruta_log.read_text(encoding="utf-8"),
            file_name=ruta_log.name,
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
