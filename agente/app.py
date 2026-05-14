from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

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
ARCHIVO_CLICKBAIT = DATA_DIR / "ABC_clickbait.json"

HEADERS = {
    "User-Agent": "ProyectoAcademicoClickbait/1.0"
}

ABC_CATEGORIAS = {
    "Nacional": "https://www.abc.es/espana/",
    "Internacional": "https://www.abc.es/internacional/",
    "Cultura": "https://www.abc.es/cultura/",
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


# ============================================================
# 2. FUNCIONES DE LIMPIEZA Y JSON
# ============================================================

def limpiar_texto(texto: str | None) -> str | None:
    """Limpia espacios raros y saltos de línea."""
    if texto is None:
        return None

    texto = str(texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


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
    """
    Mantiene exactamente la estructura que ya usáis.

    No añadimos aquí 'motivo', 'confianza' ni 'label' para no romper
    vuestra estructura original.
    """
    return {
        campo: articulo.get(campo)
        for campo in CAMPOS_NOTICIA
    }


def guardar_articulo_clickbait(ruta_json: Path, articulo: dict) -> bool:
    """
    Guarda una noticia clickbait evitando duplicados por Link.

    Devuelve True si se añadió.
    Devuelve False si ya existía.
    """
    articulos_existentes = cargar_json(ruta_json)

    links_existentes = {
        articulo_existente.get("Link")
        for articulo_existente in articulos_existentes
    }

    link = articulo.get("Link")

    if link in links_existentes:
        return False

    articulos_existentes.append(normalizar_articulo_para_json(articulo))
    guardar_json(ruta_json, articulos_existentes)

    return True


# ============================================================
# 3. LECTOR DE ABC
# ============================================================

def obtener_soup(url: str) -> BeautifulSoup:
    """Descarga una página y la transforma en objeto BeautifulSoup."""
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


class LectorABC:
    """
    Lector específico para ABC.

    En el futuro podéis crear LectorElPais, LectorElMundo, etc.,
    siempre devolviendo los artículos con la misma estructura.
    """

    periodico = "ABC"

    def obtener_links_categoria(self, url_categoria: str, max_links: int = 5) -> list[str]:
        soup = obtener_soup(url_categoria)

        links: list[str] = []

        for a in soup.select("a.v-a-lnk, h2.v-a-t a"):
            href = a.get("href")

            if not href:
                continue

            url_absoluta = urljoin(url_categoria, href)
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
                "Link": link,
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


def obtener_articulos_abc(
    categorias: list[str],
    max_por_categoria: int,
    pausa_segundos: float,
) -> list[dict]:
    """Obtiene artículos de ABC para las categorías seleccionadas."""
    lector = LectorABC()
    articulos: list[dict] = []

    for categoria in categorias:
        url_categoria = ABC_CATEGORIAS[categoria]
        links = lector.obtener_links_categoria(
            url_categoria=url_categoria,
            max_links=max_por_categoria,
        )

        for link in links:
            articulo = lector.extraer_articulo(link, categoria)

            if articulo:
                articulos.append(articulo)

            time.sleep(pausa_segundos)

    return articulos


# ============================================================
# 4. MODELO LLM
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
        max_tokens=800,
        max_retries=2,
    )


# ============================================================
# 5. TOOL DEL AGENTE
# ============================================================

class GuardarClickbaitArgs(BaseModel):
    """
    Argumentos que el LLM debe generar cuando decida guardar
    una noticia como clickbait.
    """

    motivo: str = Field(
        description="Explicación breve de por qué la noticia parece clickbait."
    )

    confianza: int = Field(
        description="Confianza de 0 a 100 en que la noticia es clickbait."
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

    La herramienta de guardado usa una clausura: el LLM no puede inventarse
    ni modificar la noticia guardada. Si decide guardar, Python guarda
    exactamente el artículo extraído por el scraper.
    """

    @tool("guardar_noticia_clickbait", args_schema=GuardarClickbaitArgs)
    def guardar_noticia_clickbait(motivo: str, confianza: int) -> str:
        """
        Guarda la noticia actual en el JSON de clickbait.

        Usa esta herramienta solo si la noticia analizada es clickbait.
        """
        anadida = guardar_articulo_clickbait(ARCHIVO_CLICKBAIT, articulo)

        if anadida:
            estado = "Noticia añadida al JSON de clickbait."
        else:
            estado = "La noticia ya estaba en el JSON. No se duplicó."

        return (
            f"{estado}\n"
            f"Confianza indicada por el agente: {confianza}\n"
            f"Motivo: {motivo}"
        )

    herramientas = [guardar_noticia_clickbait]

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
    - Si hay mucha redundancia en el contenido que no aporta información real.
3. Si ES clickbait, llama exactamente una vez a la herramienta guardar_noticia_clickbait.
4. Si NO es clickbait, no llames a ninguna herramienta.
5. Después, responde con un resumen breve de tu decisión.

Definición operativa de clickbait:
Una noticia puede considerarse clickbait si el titular o el subtítulo intentan atraer clics
mediante exageración, ambigüedad, suspense artificial, carga emocional excesiva,
promesas vagas, curiosidad incompleta o desajuste entre titular y contenido.

Ejemplos de señales de clickbait:
- Titulares que ocultan información clave para provocar curiosidad.
- Expresiones tipo "no vas a creer", "la razón te sorprenderá", "lo que ocurrió después".
- Exageración emocional o sensacionalista.
- Titular muy alarmista para un contenido normal.
- Promesa de revelación que el contenido no justifica.

No consideres clickbait una noticia solo por ser interesante, polémica o importante.
Si el titular es informativo, concreto y proporcional al contenido, no es clickbait.

Formato de tu respuesta final:
Veredicto: CLICKBAIT o NO CLICKBAIT
Confianza: número de 0 a 100
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


def analizar_articulo_con_agente(llm: ChatOpenRouter, articulo: dict) -> dict:
    """Ejecuta el agente sobre una noticia y devuelve un resumen."""
    agente = crear_agente_para_articulo(llm, articulo)

    resultado = agente.invoke({
        "input": construir_input_articulo(articulo)
    })

    pasos = resultado.get("intermediate_steps", [])

    herramienta_usada = any(
        getattr(accion, "tool", "") == "guardar_noticia_clickbait"
        for accion, _observacion in pasos
    )

    return {
        "Título": articulo.get("Título"),
        "Categoría": articulo.get("Categoría"),
        "Link": articulo.get("Link"),
        "Guardada como clickbait": herramienta_usada,
        "Respuesta del agente": resultado.get("output"),
    }


# ============================================================
# 6. INTERFAZ STREAMLIT
# ============================================================

def main() -> None:
    st.set_page_config(
        page_title="Agente detector de clickbait",
        layout="wide",
    )

    DATA_DIR.mkdir(exist_ok=True)

    st.title("Agente detector de clickbait en noticias")
    st.caption(
        "MVP académico: scrapea ABC, el LLM analiza las noticias y el agente guarda "
        "solo las que considera clickbait."
    )

    st.sidebar.header("Configuración")

    categorias = st.sidebar.multiselect(
        "Categorías de ABC",
        options=list(ABC_CATEGORIAS.keys()),
        default=["Nacional"],
    )

    max_por_categoria = st.sidebar.slider(
        "Máximo de noticias por categoría",
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

    if st.button("Ejecutar agente"):
        if not categorias:
            st.warning("Selecciona al menos una categoría.")
            return

        try:
            llm = crear_llm(temperatura=0.0)

            st.subheader("1. Obteniendo noticias de ABC")
            articulos = obtener_articulos_abc(
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

                with st.expander(f"{indice}. {titulo}"):
                    resultado = analizar_articulo_con_agente(llm, articulo)
                    resultados.append(resultado)

                    st.write("**Guardada como clickbait:**", resultado["Guardada como clickbait"])
                    st.write("**Respuesta del agente:**")
                    st.write(resultado["Respuesta del agente"])
                    st.write("**Link:**", resultado["Link"])

                progreso.progress(indice / len(articulos))

            st.subheader("3. Resumen")
            st.dataframe(resultados, use_container_width=True)

            total_clickbait = sum(
                1 for resultado in resultados
                if resultado["Guardada como clickbait"]
            )

            st.success(
                f"Proceso terminado. Noticias guardadas como clickbait en esta ejecución: "
                f"{total_clickbait}"
            )

            st.info(f"Archivo actualizado: {ARCHIVO_CLICKBAIT}")

        except Exception as exc:
            st.error(f"No se pudo ejecutar el agente: {exc}")

    st.divider()

    st.subheader("JSON actual de noticias clickbait")

    if st.button("Ver JSON guardado"):
        datos = cargar_json(ARCHIVO_CLICKBAIT)
        st.json(datos)

    if ARCHIVO_CLICKBAIT.exists():
        st.download_button(
            label="Descargar ABC_clickbait.json",
            data=ARCHIVO_CLICKBAIT.read_text(encoding="utf-8"),
            file_name="ABC_clickbait.json",
            mime="application/json",
        )


if __name__ == "__main__":
    main()