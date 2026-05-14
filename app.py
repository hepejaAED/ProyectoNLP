from __future__ import annotations

import os
import json
import re
import glob

from difflib import SequenceMatcher

import streamlit as st
from dotenv import load_dotenv
from langchain_groq import ChatGroq

from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

st.set_page_config(
    page_title="Agente Clickbait",
    page_icon="📰",
    layout="wide"
)


# ============================================================
# LLM
# ============================================================

@st.cache_resource
def cargar_llm():

    if not GROQ_API_KEY:
        return None

    return ChatGroq(
        model="llama-3.1-8b-instant",
        groq_api_key=GROQ_API_KEY,
        temperature=0.2
    )


def llamar_llm(llm, prompt: str):

    if llm is None:
        return "ERROR: No se encontró GROQ_API_KEY en .env"

    try:
        respuesta = llm.invoke(prompt)
        return respuesta.content.strip()

    except Exception as e:
        return f"ERROR: {e}"


# ============================================================
# UTILIDADES
# ============================================================

def normalizar_texto(texto: str):

    texto = texto.lower()

    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


def cargar_noticias_json(ruta_json: str):

    with open(ruta_json, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# BUSCAR TÍTULO EN JSON
# ============================================================

def buscar_noticia_por_titulo(
    ruta_json: str,
    titulo_usuario: str
):

    try:
        noticias = cargar_noticias_json(
            ruta_json
        )

    except Exception:
        return None

    titulo_usuario_norm = normalizar_texto(
        titulo_usuario
    )

    mejor_noticia = None
    mejor_score = 0

    for noticia in noticias:

        titulo_json = normalizar_texto(
            noticia.get("Título", "")
        )

        score = SequenceMatcher(
            None,
            titulo_usuario_norm,
            titulo_json
        ).ratio()

        if score > mejor_score:
            mejor_score = score
            mejor_noticia = noticia

    if mejor_score >= 0.70:

        mejor_noticia["_match_score"] = round(
            mejor_score,
            3
        )

        return mejor_noticia

    return None


# ============================================================
# TANIWA
# ============================================================

def leer_taniwa(noticia: dict):

    cb = noticia.get("cb", None)

    cb_score = noticia.get("cb_score", "")

    cb_label = noticia.get("cb_label", "")

    if cb is True:

        label = "Clickbait"

    elif cb is False:

        label = "No clickbait"

    else:

        texto = str(cb_label).lower()

        if "no" in texto:

            label = "No clickbait"

        elif "clickbait" in texto:

            label = "Clickbait"

        else:

            label = "No disponible"

    return {
        "label": label,
        "score": cb_score,
        "original": cb_label
    }


# ============================================================
# CLASIFICACIÓN LLM
# ============================================================

def clasificar_clickbait_llm(
    llm,
    titulo: str
):

    prompt = f"""
Eres un experto en detección de clickbait.

Analiza este titular periodístico:

"{titulo}"

Responde EXACTAMENTE con este formato:

Etiqueta: Clickbait o No clickbait
Explicación: breve explicación
"""

    respuesta = llamar_llm(
        llm,
        prompt
    )

    texto = respuesta.lower()

    if respuesta.startswith("ERROR"):

        etiqueta = "Error"

    elif "no clickbait" in texto:

        etiqueta = "No clickbait"

    elif "clickbait" in texto:

        etiqueta = "Clickbait"

    else:

        etiqueta = "No identificado"

    return {
        "etiqueta": etiqueta,
        "respuesta": respuesta
    }


# ============================================================
# GENERAR NUEVO TITULAR
# ============================================================

def generar_titulo_neutral(
    llm,
    titulo_original: str,
    contenido: str
):

    prompt = f"""
Este titular ha sido identificado como clickbait.

Genera un nuevo titular:
- neutral
- periodístico
- fiel al contenido
- sin exageraciones

Titular original:
"{titulo_original}"

Contenido:
"{contenido}"

Responde SOLO con el nuevo titular.
"""

    return llamar_llm(
        llm,
        prompt
    )


# ============================================================
# INTERFAZ
# ============================================================

st.title("📰 Agente de análisis de clickbait")


# ============================================================
# DATASETS JSON
# ============================================================

json_files = glob.glob(
    "data/*.json"
)

if len(json_files) == 0:

    st.error(
        "No se encontraron archivos JSON dentro de la carpeta data/"
    )

    st.stop()

ruta_json = st.selectbox(
    "Selecciona un dataset JSON",
    json_files
)


# ============================================================
# INPUT USUARIO
# ============================================================

titulo_usuario = st.text_input(
    "Título"
)


llm = cargar_llm()


# ============================================================
# SESSION STATE
# ============================================================

if "resultado_llm" not in st.session_state:

    st.session_state.resultado_llm = None

if "titulo_analizado" not in st.session_state:

    st.session_state.titulo_analizado = ""


# ============================================================
# BOTÓN ANALIZAR
# ============================================================

if st.button("Analizar título"):

    if not titulo_usuario.strip():

        st.warning(
            "Introduce un título."
        )

    else:

        with st.spinner(
            "Analizando título..."
        ):

            resultado_llm = clasificar_clickbait_llm(
                llm,
                titulo_usuario
            )

        st.session_state.resultado_llm = resultado_llm

        st.session_state.titulo_analizado = titulo_usuario


# ============================================================
# RESULTADO LLM
# ============================================================

if st.session_state.resultado_llm is not None:

    resultado_llm = st.session_state.resultado_llm

    etiqueta_llm = resultado_llm["etiqueta"]

    st.subheader(
        "Resultado del LLM"
    )

    st.write(
        f"Clasificación: **{etiqueta_llm}**"
    )

    st.write(
        resultado_llm["respuesta"]
    )


    # ========================================================
    # COMPARACIÓN TANIWA
    # ========================================================

    noticia_encontrada = buscar_noticia_por_titulo(
        ruta_json,
        st.session_state.titulo_analizado
    )

    if noticia_encontrada is not None:

        taniwa = leer_taniwa(
            noticia_encontrada
        )

        st.subheader(
            "Comparación con Taniwa"
        )

        st.write(
            "Título encontrado:"
        )

        st.write(
            noticia_encontrada.get(
                "Título",
                ""
            )
        )

        st.write(
            f"Similitud: {noticia_encontrada.get('_match_score', '')}"
        )

        st.write(
            f"Taniwa: **{taniwa['label']}**"
        )

        st.write(
            f"Score Taniwa: {taniwa['score']}"
        )

        if taniwa["label"] == etiqueta_llm:

            st.success(
                "LLM y Taniwa coinciden."
            )

        else:

            st.warning(
                "LLM y Taniwa NO coinciden."
            )

    else:

        st.info(
            "No se encontró un título parecido en el JSON."
        )


    # ========================================================
    # GENERAR NUEVO TITULAR
    # ========================================================

    if etiqueta_llm == "Clickbait":

        st.subheader(
            "Generar título neutral"
        )

        contenido_usuario = st.text_area(
            "Contenido",
            height=250,
            placeholder="Pega aquí el contenido de la noticia..."
        )

        if st.button(
            "Generar nuevo título"
        ):

            if not contenido_usuario.strip():

                st.warning(
                    "Introduce el contenido."
                )

            else:

                with st.spinner(
                    "Generando nuevo titular..."
                ):

                    nuevo_titulo = generar_titulo_neutral(
                        llm,
                        st.session_state.titulo_analizado,
                        contenido_usuario
                    )

                st.subheader(
                    "Nuevo titular"
                )

                st.success(
                    nuevo_titulo
                )