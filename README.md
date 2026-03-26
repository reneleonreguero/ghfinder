# ghfinder

CLI para buscar y analizar repositorios de GitHub por nombre, autor, lenguaje, país, tópicos y estrellas.

## Instalación

```bash
pip install -e .
```

## Uso

```bash
# Buscar por palabras clave y lenguaje
ghfinder search --keywords "machine learning" --language python --stars-min 1000

# Buscar por usuario/organización
ghfinder search --user microsoft --language typescript

# Buscar por país
ghfinder search --country Spain --language python --stars-min 100

# Buscar por tópico
ghfinder search --topic web-framework --language go --sort updated

# Exportar resultados
ghfinder search --keywords fastapi --export resultados.md

# Ver estado del token
ghfinder token-status
```

## Opciones de búsqueda

| Opción | Descripción |
|--------|-------------|
| `-k/--keywords` | Palabras clave o nombre del repo |
| `-u/--user` | Usuario u organización de GitHub |
| `-l/--language` | Lenguaje de programación |
| `-c/--country` | País/ubicación de los autores |
| `-t/--topic` | Etiqueta de tema (repetible) |
| `--stars-min/max` | Rango de estrellas |
| `--forks-min` | Mínimo de forks |
| `-n/--max-results` | Máximo de resultados |
| `--sort` | Ordenar por `stars`, `forks` o `updated` |
| `--analyze/--no-analyze` | Análisis detallado (por defecto: sí con token, no sin token) |
| `--detail` | Panel completo por repo |
| `--export` | Exportar a `.json`, `.csv` o `.md` |

## Token de GitHub (opcional)

Sin token: 60 llamadas API/hora, modo rápido automático.
Con token: 5000 llamadas API/hora, análisis completo.

```bash
export GITHUB_TOKEN=ghp_tu_token_aqui
```

Crea uno en: https://github.com/settings/tokens (no requiere scopes para repos públicos).
