# Detección de *clickbait* en noticias
## Proyecto Procesado de Lenguaje Natural - Máster en Ciencia de Datos, Universitat de València

Juan Alcaraz Otón, Xueyao An, Fabián Calvo Castillo, Adrián Carrasco Alcalá, Javier Herrero Pérez, Mario Martínez Guillén y Clara Montalvá Barcenilla

### Pipeline del proyecto

![image](img/pipeline_proyecto.png)

## Medios de comunicación

Este proyecto cubre los siguientes periódicos y medios:

- **ABC**
- **elDiario**
- **El Confidencial**
- **La Vanguardia**
- **20minutos**
- **OkDiario**
- **RTVE**
- **Mediterráneo Digital**
- **El HuffPost**

## Categorías de noticias

Los artículos se clasifican en las siguientes categorías:

- **Internacional** - Noticias de ámbito mundial
- **Nacional** - Noticias de España
- **Cultura** - Artes, cine, literatura, entretenimiento

## Estructura de datos

Los artículos extraídos se almacenan en formato JSON con la siguiente estructura:

```json
{
  "Link": "string",
  "Periódico": "string",
  "Fecha": "string (YYYY-MM-DD)",
  "Título": "string",
  "Subtítulo": "string o null",
  "Categoría": "string",
  "Contenido": "string"
}
```

### Descripción de campos:

| Campo | Tipo | Descripción |
|-------|------|-------------|
| Link | string | URL del artículo original |
| Periódico | string | Nombre del medio de comunicación |
| Fecha | string | Fecha de publicación (formato YYYY-MM-DD) |
| Título | string | Título principal del artículo |
| Subtítulo | string o null | Subtítulo o descripción breve |
| Categoría | string | Categoría o sección del artículo |
| Contenido | string | Texto completo del artículo |
