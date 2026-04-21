# ProyectoNLP


Juan Alcaráz Otón, Xueyao An, Fabián Calvo Castillo, Adrián Carrasco Alcalá, Javier Herrero Pérez, Clara Montalvá Barcenilla y Mario Martinez Guillen


## Medios de Comunicación

Este proyecto cubre los siguientes periódicos y medios:

- **ABC**
- **ElDiario**
- **Europa Press**
- **La Vanguardia**
- **20minutos**
- **OK Diario**
- **RTVE**

## Categorías de Noticias

Los artículos se clasifican en las siguientes categorías:

- **Internacional** - Noticias de ámbito mundial
- **Nacional** - Noticias de España
- **Cultura** - Artes, cine, literatura, entretenimiento


## Estructura de Datos

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