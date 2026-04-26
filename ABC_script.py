# %% [markdown]
# # Webscraping a ABC
# 
# ABC parece scrapeable con `request` y `BeautifulSoup`. La página de categoría (nacional, internacional o cultura) contiene artículos en HTML estático. El patrón más útil parece ser:
# 
# ```HTML
# <article>
#   ...
#   <a class="v-a-lnk" href="..." title="...">
#   ...
#   <h2 class="v-a-t">
#   ...
#   <p class="v-a-s-t">...</p>
# </article>
# ```
# 
# | Campo     | De dónde saldría                           |
# | --------- | ------------------------------------------ |
# | Link      | `a.v-a-lnk["href"]` o `h2.v-a-t a["href"]` |
# | Título    | atributo `title` o texto del `h2`          |
# | Subtítulo | `p.v-a-s-t`                                |
# | Categoría | la asignamos nosotros: `"Nacional"`        |
# | Periódico | fijo: `"ABC"`                              |
# 
# Dentro de cada artículo, ABC nos da casi todo ya limpio dentro de:
# 
# ```html
# <script type="application/ld+json" id="evo-swg-markup">
# ```
# 
# De aquí podemos extraer directamente:
# 
# | Campo JSON nuestro | Campo en ABC                                  |
# | ------------------ | --------------------------------------------- |
# | `Link`             | `mainEntityOfPage["@id"]`                     |
# | `Periódico`        | fijo: `"ABC"`                                 |
# | `Fecha`            | `datePublished`, recortando solo `YYYY-MM-DD` |
# | `Título`           | `headline`                                    |
# | `Subtítulo`        | `description`                                 |
# | `Categoría`        | la asignamos según la sección: `"Nacional"`   |
# | `Contenido`        | `articleBody`                                 |
# 
# Se consultó el archivo robots.txt del medio. Las secciones públicas usadas para el estudio no aparecen bloqueadas para User-agent general. El scraping se limita a un máximo de 15 artículos diarios, con pausas entre peticiones, sin acceder a zonas privadas, de pago ni endpoints bloqueados. Los datos se emplean exclusivamente con fines académicos.
# 

# %%
# Cargamos las librerías necesarias

import requests               #para descargar HTML
from bs4 import BeautifulSoup #para parsear el HTML
import json                   #para guardar los datos en formato JSON
import re                     #limpiar texto con expresiones regulares
import time                   #para hacer pausas entre peticiones
from datetime import datetime #para manejar fechas
import pandas as pd           #para revisar resultados en formato tabular
import os                     #para manejar archivos y directorios

# %%
# Configuaramos headers para simular un navegador y que ABC no piense que somos un bot
headers = {
    'User-Agent': 'ProyectoAcademico/1.0'
}

# %%
#probamos la conexión a la página apartado de noticias nacionales
#url = 'https://www.abc.es/espana/'

#r=requests.get(url, headers=headers)

#print(r.status_code) #debería imprimir 200 si todo va bien
#print(r.text[:500]) #imprime los primeros 500 caracteres del HTML para verificar que se ha descargado correctamente

# %%
#Funcion para descargar una página y parsearla con BeautifulSoup
def obtener_soup(url):
    response = requests.get(url, headers=headers, timeout=10) #timeout para evitar que se quede colgado si la página no responde
    response.raise_for_status() #lanzar excepción si la respuesta no es 200
    return BeautifulSoup(response.text, 'html.parser')

# %%
#Funcion para obtener links de una categoría dada su URL
def obtener_links_categoria(url_categoria, max_links=5):
    soup = obtener_soup(url_categoria) #llamamos a la función para obtener el soup de la página de la categoría
    links = [] #lista para almacenar los links de los artículos

    for a in soup.select("a.v-a-lnk"):
        href = a.get('href') #obtenemos el atributo href del enlace

        if not href:
            continue #si no hay href, saltamos este enlace

        if href.startswith(url_categoria):
            url_valida = href #si el link ya es absoluto, lo usamos tal cual
        elif href.startswith('/'):
            url_valida = url_categoria + href #si el link es relativo, lo convertimos a absoluto
        else:
            continue #si el link no es ni absoluto ni relativo, lo ignoramos

        if url_valida not in links and url_valida.endswith(".html"):
            links.append(url_valida) #agregamos el link a la lista si no está repetido y termina en .html
        
        if len(links) >= max_links:
            break #si ya tenemos suficientes links, salimos del bucle

    return links

#Probamos la función con la categoría de noticias nacionales
#url_categoria = 'https://www.abc.es/espana/'

#links_obtenidos = obtener_links_categoria(url_categoria, max_links=5)
#print("Links obtenidos:")
#for link in links_obtenidos:
#    print(link)
    
    

# %%
#Función para extraer un artículo dado su URL

def extraer_articulo(url_articulo, categoria):
    soup = obtener_soup(url_articulo) #obtenemos el soup de la página del artículo

    script = soup.find("script", id="evo-swg-markup") #buscamos el script que contiene los datos estructurados del artículo

    if script is None:
        print(f"No se encontró el script con datos estructurados en {url_articulo}")
        return None
    
    data = json.loads(script.string) #cargamos el contenido del script como JSON

    fecha_completa = data.get('datePublished') #obtenemos la fecha de publicación completa

    fecha = fecha_completa[:10] if fecha_completa else None #extraemos solo la parte de la fecha (YYYY-MM-DD)

    articulo = {
        "Link": url_articulo, #obtenemos el link del artículo
        "Periódico": "ABC", #el periódico es ABC
        "Fecha": fecha, #la fecha de publicación del artículo
        "Título": data.get('headline'), #el título del artículo
        "Subtítulo": data.get('description'), #el subtítulo del artículo
        "Categoria": categoria, #la categoría a la que pertenece el artículo
        "Contenido": data.get('articleBody') #el contenido del artículo
    }

    return articulo

#probar con el primer artículo obtenido

#articulo_ejemplo = extraer_articulo(links_obtenidos[0], "Nacional")

#print("Artículo extraído:")
#print(json.dumps(articulo_ejemplo, indent=2, ensure_ascii=False))

# %%
#Scrapear 5 noticias nacionales

#articulos_nacionales = []

#for link in links_obtenidos:
#    articulo = extraer_articulo(link, "Nacional")
#    if articulo:
#        articulos_nacionales.append(articulo)
#    time.sleep(1) #pausa de 1 segundo entre peticiones para no saturar el servidor

#df_nacionales = pd.DataFrame(articulos_nacionales)
#df_nacionales

# %%
# Automatizar las 3 categorías principales: Nacional, Internacional y Deportes

ARCHIVO_JSON = "data/ABC.json"

# Funcion para cargar datos existentes desde el archivo JSON

def cargar_json(nombre_archivo):
    try:
        with open(nombre_archivo, "r", encoding="utf-8") as f: #abrimos el archivo en modo lectura
            return json.load(f)
    except FileNotFoundError: #si el archivo no existe, devolvemos una lista vacía
        return []
    
# Funcion para guardar datos en el archivo JSON
def guardar_json(nombre_archivo, articulos):
    with open(nombre_archivo, "w", encoding="utf-8") as f: #abrimos el archivo en modo escritura
        json.dump(articulos, f, ensure_ascii=False, indent=2) #guardamos la lista de artículos en formato JSON con indentación para que sea legible

# Funcion para añadir evitando duplicados por Link

def actualizar_json(nombre_archivo, nuevos_articulos):
    articulos_existentes = cargar_json(nombre_archivo) #cargamos los artículos existentes desde el archivo JSON

    links_existentes = {articulo["Link"] for articulo in articulos_existentes} #creamos un conjunto de los links existentes para facilitar la comparación

    articulos_a_anadir = [
        articulo for articulo in nuevos_articulos #filtramos los nuevos artículos para quedarnos solo con los que no están ya en el archivo JSON
        if articulo["Link"] not in links_existentes #si el link del artículo no está en el conjunto de links existentes, lo añadimos a la lista de artículos a añadir
    ]

    articulos_totales = articulos_existentes + articulos_a_anadir #combinamos los artículos existentes con los nuevos artículos que no estaban repetidos

    guardar_json(nombre_archivo, articulos_totales) #guardamos la lista total de artículos en el archivo JSON

    print(f"Artículos nuevos añadidos: {len(articulos_a_anadir)}") 
    #print(f"Total artículos en {nombre_archivo}: {len(articulos_totales)}")


# %%
categorias = {
    "Nacional": "https://www.abc.es/espana/",
    "Internacional": "https://www.abc.es/internacional/",
    "Cultura": "https://www.abc.es/cultura/"
}

for categoria, url_categoria in categorias.items():
    print(f"Procesando categoría: {categoria}")
    links = obtener_links_categoria(url_categoria, max_links=5) #obtenemos los links de la categoría
    articulos = []
    
    for link in links:
        articulo = extraer_articulo(link, categoria) #extraemos el artículo de cada link
        if articulo:
            articulos.append(articulo)
        time.sleep(1) #pausa de 1 segundo entre peticiones para no saturar el servidor
    
    actualizar_json(ARCHIVO_JSON, articulos) #actualizamos el archivo JSON con los nuevos artículos obtenidos

#comprobamos que se han guardado correctamente los datos en el archivo JSON
articulos_guardados = cargar_json(ARCHIVO_JSON) #cargamos los artículos guardados desde el archivo JSON
print(f"Total artículos guardados en {ARCHIVO_JSON}: {len(articulos_guardados)}") #imprimimos el total de artículos guardados


