# Garmin Watch Scraper

Scraper automatico de relojes deportivos reacondicionados de [El Corte Ingles](https://www.elcorteingles.es/deportes/reacondicionados/relojes-deportivos-y-smartwatch/8/). Te notifica cuando aparece un reloj que te interesa.

## Arquitectura

```
CronJob (cada 30 min)
  -> Playwright (headless Chromium) scrapea la pagina
  -> Compara con tu lista de relojes deseados
  -> Si hay match nuevo -> Notificacion (ntfy.sh / Telegram)
  -> Guarda estado en PVC para no repetir alertas
```

## Requisitos

- Docker
- Kubernetes (k3s, minikube, etc.)
- Una cuenta en [ntfy.sh](https://ntfy.sh) (gratis) o un bot de Telegram

## Inicio rapido

### 1. Configurar notificaciones

Edita `k8s/secret.yaml` con tus credenciales:

**Opcion A - ntfy.sh (recomendado para Arch Linux):**
```bash
# Instala la app en tu movil/PC
sudo pacman -S ntfy  # o usa la web/app

# Elige un topic unico
NTFY_TOPIC: "mis-relojes-garmin-abc123"
```

**Opcion B - Telegram:**
```bash
# 1. Crea un bot con @BotFather y obten el token
# 2. Enviame un mensaje al bot y obten tu chat_id desde:
#    https://api.telegram.org/bot<TOKEN>/getUpdates

TELEGRAM_BOT_TOKEN: "123456:ABC..."
TELEGRAM_CHAT_ID: "987654321"
```

### 2. Personalizar relojes

Edita `k8s/configmap.yaml` o `config/watches.yaml`:

```yaml
watches:
  - "Garmin Fenix 7"
  - "Garmin Fenix 8"
  - "Garmin Epix"
max_price: 400  # 0 = sin limite
```

### 3. Build y deploy

```bash
# Construir la imagen
docker build -t watch-scraper:latest .

# Si usas un registry privado:
# docker tag watch-scraper:latest mi-registry.com/watch-scraper:latest
# docker push mi-registry.com/watch-scraper:latest

# Desplegar en Kubernetes
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/cronjob.yaml

# Verificar
kubectl get cronjob -n watch-scraper

# Ejecutar manualmente para probar
kubectl create job --from=cronjob/watch-scraper test-run -n watch-scraper
kubectl logs -f job/test-run -n watch-scraper
```

### 4. Probar localmente (sin Kubernetes)

```bash
pip install -r requirements.txt
playwright install chromium

# Con ntfy.sh
NTFY_TOPIC="mi-topic" CONFIG_PATH="config/watches.yaml" SEEN_FILE="/tmp/seen.json" python src/scraper.py

# Solo consola (sin notificaciones externas)
CONFIG_PATH="config/watches.yaml" SEEN_FILE="/tmp/seen.json" python src/scraper.py
```

## Estructura del proyecto

```
.
├── config/
│   └── watches.yaml          # Config local (dev)
├── k8s/
│   ├── namespace.yaml         # Namespace dedicado
│   ├── configmap.yaml         # Lista de relojes
│   ├── secret.yaml            # Tokens de notificacion
│   ├── pvc.yaml               # Persistencia de estado
│   └── cronjob.yaml           # CronJob cada 30 min
├── src/
│   ├── scraper.py             # Logica de scraping
│   └── notifier.py            # Notificaciones
├── Dockerfile
└── requirements.txt
```

## Notas

- El scraper usa Playwright (Chromium headless) porque El Corte Ingles bloquea requests HTTP simples (403).
- El estado de relojes ya vistos se guarda en un PVC para evitar notificaciones duplicadas.
- El CronJob esta configurado con `concurrencyPolicy: Forbid` para evitar ejecuciones simultaneas.
