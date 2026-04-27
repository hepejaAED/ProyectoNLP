import feedparser
import trafilatura
import dateutil.parser
import json
import re
import os
from datetime import datetime

RSS_VANGUARDIA = {
    "Internacional": "https://www.lavanguardia.com/rss/internacional.xml",
    "Nacional": "https://www.lavanguardia.com/rss/politica.xml",  #no existe categoria Nacional entonces se usa Politica
    "Cultura": "https://www.lavanguardia.com/rss/cultura.xml"
}

def limpiar_html(texto):
    if not texto:
        return None
    texto_limpio = re.sub(r'<[^>]+>', '', texto) #se busca cualquier cosa que empiece por < y termine por > Sirve para quitar etiquetas como <p>, <br>, <strong>, <img src="...">
    return texto_limpio.strip() if texto_limpio.strip() else None

def extraer_contenido(url):
    try:
        descargado = trafilatura.fetch_url(url)
        if not descargado:
            return None #por si la noticia o página web está caida, borrada o da error
        texto = trafilatura.extract( #con trafilatura se mete al url de la noticia (sacado del xml del RSS) y saca el cuerpo de la noticia
            descargado,
            include_comments=False,
            include_tables=False,
            no_fallback=False
        )
        return texto if texto and len(texto) > 100 else None #para que efectivamente se quede con el cuerpo de la noticia y no con mensajes de Suscripciion o cookies
    except Exception:
        return None


def guardar_sin_duplicados(nuevos_datos, archivo='data/lavanguardia.json'):

    carpeta = os.path.dirname(archivo)
    if carpeta and not os.path.exists(carpeta):
        os.makedirs(carpeta)

    # Cargar datos existentes
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            datos_existentes = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"Archivo no existe o está vacío. Iniciando desde cero en {archivo}.")
        datos_existentes = []

    links_existentes = {item['Link'] for item in datos_existentes}

    nuevos_agregados = 0
    for item in nuevos_datos:
        if item['Link'] not in links_existentes:
            datos_existentes.append(item)
            links_existentes.add(item['Link'])
            nuevos_agregados += 1
            
    
    with open(archivo, 'w', encoding='utf-8') as f:
        json.dump(datos_existentes, f, ensure_ascii=False, indent=4)
        
    return datos_existentes

def obtener_noticias_vanguardia(num_por_categoria=5, archivo_salida='data/lavanguardia.json'):
    
    noticias_finales = []

    for categoria, url_rss in RSS_VANGUARDIA.items():
        feed = feedparser.parse(url_rss) #ingresa al RSS de cada categoría
        
        entradas = feed.entries[:num_por_categoria]
        
        for entry in entradas:
            titulo = entry.get("title", "").strip()
            link = entry.get("link", "")
            
            try: #si no hay fecha pone desconocida
                fecha_dt = dateutil.parser.parse(entry.get("published", ""))
                fecha_str = fecha_dt.strftime("%Y-%m-%d") #formateo de fecha a YYYY-MM-DD
            except Exception:
                fecha_str = "Desconocida"
            
            subtitulo = limpiar_html(entry.get("summary", ""))
            contenido = extraer_contenido(link)
            
            if not contenido:
                contenido = subtitulo if subtitulo else "No se pudo extraer el contenido."
            
            if contenido:
                contenido = contenido.replace('\n', ' ')
            
            articulo = { #diccionario con todo
                "Link": link,
                "Periódico": "La Vanguardia",
                "Fecha": fecha_str,
                "Título": titulo,
                "Subtítulo": subtitulo,
                "Categoría": categoria,
                "Contenido": contenido
            }
            
            noticias_finales.append(articulo)

    datos_actualizados = guardar_sin_duplicados(noticias_finales, archivo=archivo_salida)

    return datos_actualizados